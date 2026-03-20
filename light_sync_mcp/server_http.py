"""MCP 서버 — Streamable HTTP (Claude Web) + SSE (LM Studio) 동시 지원

포트:
  5010 → Streamable HTTP  (Claude Web: https://mcp.mgnt.kr/mcp)
  5011 → SSE              (LM Studio:  http://localhost:5011/sse)

실행:
  python -m light_sync_mcp.server_http
"""
import os
import threading
import uvicorn
from .server import mcp

HTTP_PORT = int(os.environ.get("MCP_PORT", 5010))
SSE_PORT  = int(os.environ.get("MCP_SSE_PORT", 5011))


def run_http():
    """Streamable HTTP — lifespan 포함 (Claude Web)"""
    app = mcp.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="info")


def run_sse():
    """SSE — LM Studio / Open WebUI"""
    app = mcp.sse_app()
    uvicorn.run(app, host="0.0.0.0", port=SSE_PORT, log_level="info")


if __name__ == "__main__":
    print("Light-Sync MCP 서버 시작")
    print(f"  HTTP (Claude Web) → http://0.0.0.0:{HTTP_PORT}/mcp")
    print(f"  SSE  (LM Studio)  → http://0.0.0.0:{SSE_PORT}/sse")

    t = threading.Thread(target=run_sse, daemon=True)
    t.start()

    run_http()  # 메인 스레드에서 HTTP 실행
