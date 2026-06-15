import os
from flask import Blueprint, send_from_directory, abort
from modules.auth_decorators import login_required

mockups_bp = Blueprint("mockups", __name__, url_prefix="/mockups")

MOCKUPS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mockups")


@mockups_bp.route("/")
@login_required
def index():
    return send_from_directory(os.path.join(MOCKUPS_DIR, "chat_erp"), "index.html")


@mockups_bp.route("/<path:subpath>")
@login_required
def serve(subpath):
    full = os.path.normpath(os.path.join(MOCKUPS_DIR, subpath))
    if not full.startswith(MOCKUPS_DIR):
        abort(404)
    if os.path.isdir(full):
        full = os.path.join(full, "index.html")
    if not os.path.isfile(full):
        abort(404)
    rel_dir, fname = os.path.split(full)
    return send_from_directory(rel_dir, fname)
