"""메일 첨부 미리보기 — 내려받지 않고 화면에서 본다.

받는 것:
  한글(.hwp/.hwpx)  → HTML   (tools/hwp/render.mjs, rhwp Rust+WASM)
  오피스(.xlsx 등)  → PDF    (LibreOffice 변환)

**워드·엑셀·PPT 는 이제 화면이 이 길로 오지 않는다** — 회사 문서서버(ONLYOFFICE)가
원본 그대로 열어 주므로 그쪽이 낫다(modules/services/attach_office.py).
여기 남겨 둔 오피스→PDF 는 문서서버가 안 뜨는 날의 뒷길이다.

왜 한글만 따로인가: LibreOffice 에는 한글 필터가 아예 없고(2026-09-16 실측),
문서서버도 한글을 못 연다. rhwp 말고는 길이 없다.

지켜야 할 것
  - **임시파일을 /tmp 에 두지 않는다.** systemd PrivateTmp 때문에 서비스마다 /tmp 가
    따로 보여, 다른 프로세스가 만든 파일을 못 찾는다(대용량 첨부에서 한 번 겪었다).
    프로젝트 안의 .upload_tmp 를 쓴다.
  - **PATH 를 직접 넣어 준다.** systemd 가 주는 PATH 에는 venv 뿐이라
    node·libreoffice 래퍼가 dirname·sed 같은 것을 못 찾는다(routes/office.py 와 같은 사정).
  - 변환은 바깥 프로그램을 돌리는 일이다. 반드시 **시간·크기 제한**을 건다.
"""

import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_ROOT = os.path.join(_BASE, '.upload_tmp', 'preview')
HWP_RENDERER = os.path.join(_BASE, 'tools', 'hwp', 'render.mjs')

MAX_BYTES = 20 * 1024 * 1024      # 20MB 넘으면 화면에서 보는 것보다 받는 게 빠르다
TIMEOUT_SEC = 90
HWP_MAX_PAGES = 30                # 앞 30쪽까지만 — 그 이상은 미리보기가 아니라 열람이다

HWP_EXT = {'hwp', 'hwpx'}
# LibreOffice 로 PDF 가 되는 것들. 실제로 어떤 것이 되는지는 서버에 깔린 구성 요소에 달렸다
# (2026-09-16 현재 libreoffice-calc 만 있어 표 계열만 된다 — writer·impress 는 미설치).
OFFICE_EXT = {'xlsx', 'xls', 'csv', 'ods', 'docx', 'doc', 'rtf', 'odt', 'pptx', 'ppt', 'odp'}


def preview_kind(filename):
    """이 첨부를 화면에서 볼 수 있는가 — 'hwp' | 'office' | None"""
    ext = (filename or '').rsplit('.', 1)[-1].lower() if '.' in (filename or '') else ''
    if ext in HWP_EXT:
        return 'hwp'
    if ext in OFFICE_EXT:
        return 'office'
    return None


def _run_env():
    env = os.environ.copy()
    env['PATH'] = '/usr/bin:/bin:/usr/local/bin:' + env.get('PATH', '')
    env.setdefault('HOME', TMP_ROOT)
    return env


def _workdir():
    os.makedirs(TMP_ROOT, exist_ok=True)
    return tempfile.mkdtemp(dir=TMP_ROOT)


def render_hwp(data, filename):
    """한글 → HTML. 실패하면 (None, 사유)."""
    node = shutil.which('node') or '/usr/bin/node'
    if not os.path.isfile(HWP_RENDERER):
        return None, '한글 미리보기 변환기가 설치돼 있지 않습니다.'

    work = _workdir()
    try:
        src = os.path.join(work, 'in.' + (filename or 'x.hwp').rsplit('.', 1)[-1].lower())
        with open(src, 'wb') as f:
            f.write(data)
        proc = subprocess.run(
            [node, HWP_RENDERER, src, str(HWP_MAX_PAGES)],
            capture_output=True, timeout=TIMEOUT_SEC, env=_run_env(), cwd=work,
        )
        if proc.returncode != 0 or not proc.stdout:
            logger.warning("한글 미리보기 실패 (%s): %s", filename,
                           proc.stderr.decode('utf-8', 'replace')[:300])
            return None, '한글 문서를 여는 데 실패했습니다. 내려받아 보십시오.'
        return proc.stdout.decode('utf-8', 'replace'), None
    except subprocess.TimeoutExpired:
        return None, '문서가 커서 미리보기 시간이 초과됐습니다. 내려받아 보십시오.'
    except Exception as e:
        logger.warning("한글 미리보기 오류 (%s): %s", filename, e)
        return None, '미리보기를 만들지 못했습니다.'
    finally:
        shutil.rmtree(work, ignore_errors=True)


def render_office_pdf(data, filename):
    """오피스 문서 → PDF 바이트. 실패하면 (None, 사유)."""
    bin_path = (shutil.which('libreoffice') or shutil.which('soffice')
                or next((p for p in ('/usr/bin/libreoffice', '/usr/bin/soffice')
                         if os.path.isfile(p) and os.access(p, os.X_OK)), None))
    if not bin_path:
        return None, '문서 변환기가 설치돼 있지 않습니다.'

    work = _workdir()
    try:
        ext = (filename or 'x.xlsx').rsplit('.', 1)[-1].lower()
        src = os.path.join(work, f'in.{ext}')
        with open(src, 'wb') as f:
            f.write(data)
        # 호출마다 임시 프로필 — 워커가 ~/.config/libreoffice 를 함께 쓰면 락이 충돌한다
        profile = os.path.join(work, 'profile')
        proc = subprocess.run(
            [bin_path, f'-env:UserInstallation=file://{profile}', '--headless', '--norestore',
             '--nofirststartwizard', '--convert-to', 'pdf', '--outdir', work, src],
            capture_output=True, timeout=TIMEOUT_SEC, env=_run_env(), cwd=work,
        )
        out = os.path.join(work, 'in.pdf')
        if proc.returncode != 0 or not os.path.isfile(out):
            logger.warning("문서 미리보기 실패 (%s) rc=%s: %s", filename, proc.returncode,
                           proc.stderr.decode('utf-8', 'replace')[:300])
            # 서버에 그 종류를 여는 구성 요소가 없을 때가 대부분이다(워드·PPT)
            return None, '이 문서는 미리보기를 만들지 못했습니다. 내려받아 보십시오.'
        with open(out, 'rb') as f:
            return f.read(), None
    except subprocess.TimeoutExpired:
        return None, '문서가 커서 미리보기 시간이 초과됐습니다. 내려받아 보십시오.'
    except Exception as e:
        logger.warning("문서 미리보기 오류 (%s): %s", filename, e)
        return None, '미리보기를 만들지 못했습니다.'
    finally:
        shutil.rmtree(work, ignore_errors=True)
