"""OIDC Provider — 사내 SSO

ERP 사용자 계정으로 외부 도구(Mattermost 등)에 OpenID Connect 로그인을 제공.

엔드포인트:
- GET  /.well-known/openid-configuration   discovery
- GET  /oauth/jwks                          공개키
- GET  /oauth/authorize                     authorization (login 강제)
- POST /oauth/token                         code → access_token + id_token
- GET  /oauth/userinfo                      access_token으로 사용자 정보
"""
import os
import time
import secrets
import datetime
import bcrypt
from urllib.parse import urlencode, urlparse

from flask import Blueprint, request, redirect, jsonify, session, url_for, abort, render_template_string
from authlib.jose import jwt, JsonWebKey

from modules.db_context import get_db
from modules.models import User, OAuthClient, OAuthCode, OAuthToken


oauth_bp = Blueprint("oauth", __name__)


# ===== 키 로드 =====
_KEY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".oidc_keys")
with open(os.path.join(_KEY_DIR, "private.pem"), "rb") as f:
    _PRIVATE_KEY_PEM = f.read()
with open(os.path.join(_KEY_DIR, "public.pem"), "rb") as f:
    _PUBLIC_KEY_PEM = f.read()
_JWK = JsonWebKey.import_key(_PUBLIC_KEY_PEM, {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": "erp-key-1"})


def _issuer():
    """OIDC issuer URL — 외부에서 보는 ERP 주소"""
    return os.environ.get("OIDC_ISSUER", "https://work.mgnt.kr")


def _now():
    return datetime.datetime.utcnow()


def _user_claims(user):
    """OIDC standard claims + GitLab 호환 필드(id, username) 동시 반환"""
    return {
        # OIDC standard
        "sub": str(user.id),
        "preferred_username": user.username,
        "name": user.full_name or user.username,
        "email": user.email or f"{user.username}@mgnt.kr",
        "email_verified": True,
        "given_name": user.full_name or user.username,
        # GitLab 호환 (Mattermost가 GitLab 모드일 때 사용)
        "id": user.id,
        "username": user.username,
        # ERP 추가 정보
        "groups": [user.user_group] if user.user_group else [],
        "position": user.position or "",
        "role": user.role or "user",
    }


# ============================================================
# Discovery
# ============================================================
@oauth_bp.route("/.well-known/openid-configuration")
def discovery():
    iss = _issuer()
    return jsonify({
        "issuer": iss,
        "authorization_endpoint": f"{iss}/oauth/authorize",
        "token_endpoint": f"{iss}/oauth/token",
        "userinfo_endpoint": f"{iss}/oauth/userinfo",
        "jwks_uri": f"{iss}/oauth/jwks",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "profile", "email"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        "claims_supported": [
            "sub", "iss", "aud", "exp", "iat",
            "preferred_username", "name", "email", "email_verified",
            "given_name", "groups", "position", "role",
        ],
        "code_challenge_methods_supported": ["S256", "plain"],
    })


@oauth_bp.route("/oauth/jwks")
def jwks():
    return jsonify({"keys": [_JWK.as_dict()]})


# ============================================================
# Authorize
# ============================================================
@oauth_bp.route("/oauth/authorize")
def authorize():
    response_type = request.args.get("response_type")
    client_id = request.args.get("client_id")
    redirect_uri = request.args.get("redirect_uri")
    scope = request.args.get("scope", "openid")
    state = request.args.get("state", "")
    nonce = request.args.get("nonce", "")
    code_challenge = request.args.get("code_challenge")
    code_challenge_method = request.args.get("code_challenge_method")

    if response_type != "code":
        return jsonify({"error": "unsupported_response_type"}), 400
    if not client_id or not redirect_uri:
        return jsonify({"error": "invalid_request"}), 400

    with get_db() as db:
        client = db.query(OAuthClient).filter(
            OAuthClient.client_id == client_id, OAuthClient.is_active.is_(True)
        ).first()
        if not client:
            return jsonify({"error": "invalid_client"}), 400

        allowed = [u.strip() for u in (client.redirect_uris or "").split() if u.strip()]
        if redirect_uri not in allowed:
            return jsonify({"error": "invalid_redirect_uri", "got": redirect_uri, "allowed": allowed}), 400

        # 비로그인 시 ERP 로그인으로 보내고 다시 돌아오게
        if "user_id" not in session:
            return_to = request.full_path  # 쿼리포함
            return redirect(url_for("auth.login", next=return_to))

        user = db.get(User, session["user_id"])
        if not user or not user.is_active:
            return jsonify({"error": "user_inactive"}), 403

        # Authorization code 발급
        code_value = secrets.token_urlsafe(48)
        oc = OAuthCode(
            code=code_value,
            client_id=client_id,
            user_id=user.id,
            redirect_uri=redirect_uri,
            scope=scope,
            nonce=nonce or None,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            expires_at=_now() + datetime.timedelta(minutes=5),
        )
        db.add(oc)
        db.commit()

        params = {"code": code_value}
        if state:
            params["state"] = state
        sep = "&" if "?" in redirect_uri else "?"
        return redirect(f"{redirect_uri}{sep}{urlencode(params)}")


# ============================================================
# Token
# ============================================================
def _verify_client(db, client_id, client_secret):
    client = db.query(OAuthClient).filter(
        OAuthClient.client_id == client_id, OAuthClient.is_active.is_(True)
    ).first()
    if not client:
        return None
    try:
        ok = bcrypt.checkpw(client_secret.encode("utf-8"), client.client_secret_hash.encode("utf-8"))
    except Exception:
        return None
    return client if ok else None


@oauth_bp.route("/oauth/token", methods=["POST"])
def token():
    # client auth — Basic 또는 form
    client_id = request.form.get("client_id")
    client_secret = request.form.get("client_secret")
    if not client_id or not client_secret:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            import base64
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                client_id, client_secret = decoded.split(":", 1)
            except Exception:
                return jsonify({"error": "invalid_client"}), 401

    grant_type = request.form.get("grant_type")
    if grant_type != "authorization_code":
        return jsonify({"error": "unsupported_grant_type"}), 400

    code = request.form.get("code")
    redirect_uri = request.form.get("redirect_uri")
    if not code or not redirect_uri:
        return jsonify({"error": "invalid_request"}), 400

    with get_db() as db:
        client = _verify_client(db, client_id, client_secret)
        if not client:
            return jsonify({"error": "invalid_client"}), 401

        oc = db.query(OAuthCode).filter(
            OAuthCode.code == code, OAuthCode.client_id == client_id
        ).first()
        if not oc or oc.used or oc.expires_at < _now() or oc.redirect_uri != redirect_uri:
            return jsonify({"error": "invalid_grant"}), 400

        user = db.get(User, oc.user_id)
        if not user or not user.is_active:
            return jsonify({"error": "user_inactive"}), 403

        oc.used = True

        # access_token (opaque) — userinfo 조회용
        access_token = secrets.token_urlsafe(48)
        ttl = 3600
        tok = OAuthToken(
            access_token=access_token,
            client_id=client_id,
            user_id=user.id,
            scope=oc.scope,
            expires_at=_now() + datetime.timedelta(seconds=ttl),
        )
        db.add(tok)
        db.commit()

        # id_token (signed JWT)
        iss = _issuer()
        now_ts = int(time.time())
        claims = _user_claims(user)
        claims.update({
            "iss": iss,
            "aud": client_id,
            "iat": now_ts,
            "exp": now_ts + ttl,
            "auth_time": now_ts,
        })
        if oc.nonce:
            claims["nonce"] = oc.nonce
        header = {"alg": "RS256", "kid": "erp-key-1", "typ": "JWT"}
        id_token = jwt.encode(header, claims, _PRIVATE_KEY_PEM).decode("utf-8")

        return jsonify({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": ttl,
            "id_token": id_token,
            "scope": oc.scope,
        })


# ============================================================
# Userinfo
# ============================================================
@oauth_bp.route("/oauth/userinfo")
def userinfo():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "invalid_token"}), 401
    access_token = auth[7:].strip()

    with get_db() as db:
        tok = db.query(OAuthToken).filter(
            OAuthToken.access_token == access_token, OAuthToken.revoked.is_(False)
        ).first()
        if not tok or tok.expires_at < _now():
            return jsonify({"error": "invalid_token"}), 401
        user = db.get(User, tok.user_id)
        if not user or not user.is_active:
            return jsonify({"error": "user_inactive"}), 403
        return jsonify(_user_claims(user))
