#!/usr/bin/env node
/**
 * Light-Sync ERP Mattermost Bot Server
 *
 * Listener(WebSocket) → HTTP POST (localhost:8789) → Claude Code(MCP)
 * Claude channel_reply tool → Mattermost REST API (postMessage, threaded)
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import http from "node:http";
import https from "node:https";
import { URL } from "node:url";
import { spawn } from "node:child_process";

const MMBOT_PORT = parseInt(process.env.MMBOT_PORT || "8789", 10);
const MM_BASE_URL = process.env.MM_BASE_URL || "https://team.mgnt.kr";
const MM_BOT_TOKEN = process.env.MM_BOT_TOKEN || "";
const MM_BOT_USER_ID = process.env.MM_BOT_USER_ID || "";

// HEADLESS 모드: dev-channel inject 우회 — 요청당 `claude --print` 1회 spawn.
// 활성화 시 mcp.notification 경로를 건너뛰고 stdout을 그대로 Mattermost에 게시.
const USE_HEADLESS = process.env.MMBOT_USE_HEADLESS === "1";
const HEADLESS_CLAUDE_BIN =
  process.env.MMBOT_CLAUDE_BIN || "/home/magnatech/.local/bin/claude";
const HEADLESS_MCP_CFG =
  process.env.MMBOT_HEADLESS_MCP ||
  "/web/light_sync/light_sync_mmbot/mcp-headless.json";
const HEADLESS_SP =
  process.env.MMBOT_HEADLESS_SP ||
  "/web/light_sync/light_sync_mmbot/system-prompt-headless.md";
const HEADLESS_TIMEOUT_MS = parseInt(
  process.env.MMBOT_HEADLESS_TIMEOUT_MS || "120000",
  10
);

if (!MM_BOT_TOKEN) {
  process.stderr.write("[mmbot] FATAL: MM_BOT_TOKEN not set\n");
  process.exit(1);
}

// request_id → 원본 메타 (channel_id, root_id, user) 매핑
const requestMeta = new Map();

// ── MCP Server ────────────────────────────────────────────────────────
const mcp = new Server(
  { name: "lightsync-erp-mmbot", version: "0.1.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {} },
      tools: {},
    },
    instructions: `당신은 Light-Sync ERP Mattermost 봇입니다.
Mattermost 멘션/DM 메시지가 <channel source="lightsync-erp-mmbot" request_id="..." user="..." channel="..." channel_type="..."> 태그로 도착합니다.

**중요 규칙:**
1. 메시지를 받으면 light-sync-erp MCP 서버의 ERP 도구를 사용해 데이터를 조회하세요.
2. 조회 결과를 요약한 뒤, 반드시 channel_reply 도구로 Mattermost에 응답하세요.
3. channel_reply 호출 시 request_id를 태그에서 그대로 가져와 전달하세요.
4. 한국어로 간결하게 답변. 숫자는 한국 단위(건, 개, 원).
5. 메시지에 [채널: NAME, 허용도구: LIST]가 있으면 해당 도구만 사용. 권한 없는 도구는 "해당 기능은 이 채널에서 사용 불가입니다."로 응답.
6. **MCP 도구 2개 이상 호출이 필요한 복잡한 질문**은 먼저 channel_reply(partial=true)로 "조회 중입니다..." 안내 후 작업.
7. Mattermost 마크다운 사용 가능: **굵게**, \`코드\`, 표(|컬럼|), 링크.`,
  }
);

// ── channel_reply Tool ────────────────────────────────────────────────
mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "channel_reply",
      description:
        "Mattermost 채널/DM에 응답을 보냅니다. 반드시 request_id를 포함하세요. 작업 확인 버튼(등록/취소)이 필요하면 attachments 파라미터로 추가하세요.",
      inputSchema: {
        type: "object",
        properties: {
          request_id: {
            type: "string",
            description: "요청 시 전달받은 request_id (channel 태그)",
          },
          text: {
            type: "string",
            description: "유저에게 보낼 응답 메시지 (Mattermost 마크다운 허용)",
          },
          partial: {
            type: "boolean",
            description:
              "true면 중간 안내 메시지(작업 계속). 생략/false면 최종 답변.",
            default: false,
          },
          attachments: {
            type: "array",
            description:
              "Mattermost message attachments (interactive buttons 등). 납품공지·자재발주 등 사용자 승인이 필요한 작업에 사용. 각 attachment는 {title?, text?, color?, fields?, actions?} 구조. actions는 [{id, name, style, action_type, context}] 형태 — action_type=register_delivery 등으로 Flask가 분기.",
            items: {
              type: "object",
              properties: {
                title: { type: "string" },
                text: { type: "string" },
                color: { type: "string", description: "hex 색 (예: #36a64f)" },
                fields: {
                  type: "array",
                  items: {
                    type: "object",
                    properties: {
                      title: { type: "string" },
                      value: { type: "string" },
                      short: { type: "boolean" },
                    },
                  },
                },
                actions: {
                  type: "array",
                  description: "버튼 목록. 각 버튼은 Flask /mattermost/action 으로 클릭 이벤트 전송.",
                  items: {
                    type: "object",
                    properties: {
                      id: { type: "string" },
                      name: { type: "string", description: "버튼 라벨" },
                      style: { type: "string", description: "primary/danger/default/success" },
                      action_type: { type: "string", description: "예: register_delivery, cancel" },
                      context: { type: "object", description: "Flask로 전달할 데이터" },
                    },
                    required: ["name", "action_type"],
                  },
                },
              },
            },
          },
        },
        required: ["request_id", "text"],
      },
    },
  ],
}));

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  if (req.params.name !== "channel_reply") {
    throw new Error(`unknown tool: ${req.params.name}`);
  }
  const { request_id, text, partial, attachments } = req.params.arguments;
  const label = partial ? "partial" : "final";
  process.stderr.write(
    `[mmbot] reply tool called (${label}): ${request_id}\n`
  );

  let meta = null;
  for (const [key, value] of requestMeta) {
    if (key.startsWith(request_id) || request_id.startsWith(key)) {
      meta = value;
      break;
    }
  }
  if (!meta) {
    process.stderr.write(
      `[mmbot] WARN: meta not found for ${request_id} — cannot post\n`
    );
    return {
      content: [{ type: "text", text: `meta_not_found: ${request_id}` }],
    };
  }

  try {
    await postToMattermost(meta, text, attachments);
    process.stderr.write(`[mmbot] posted (${label}): ${request_id}\n`);
    if (!partial) {
      // 최종 응답이면 메타 정리
      for (const [key] of requestMeta) {
        if (key.startsWith(request_id) || request_id.startsWith(key)) {
          requestMeta.delete(key);
          break;
        }
      }
    }
    return { content: [{ type: "text", text: "posted" }] };
  } catch (err) {
    process.stderr.write(`[mmbot] post FAILED: ${err.message}\n`);
    return {
      content: [{ type: "text", text: `post_failed: ${err.message}` }],
    };
  }
});

// ── Mattermost REST: postMessage (threaded + attachments) ─────────────
const MMBOT_ACTION_URL =
  process.env.MMBOT_ACTION_URL || "https://work.mgnt.kr/mattermost/action";

function buildAttachments(attachments) {
  if (!Array.isArray(attachments) || attachments.length === 0) return null;
  return attachments.map((att) => {
    const a = { ...att };
    if (Array.isArray(att.actions)) {
      a.actions = att.actions.map((action) => ({
        id: action.id || action.action_type || action.name,
        name: action.name,
        style: action.style || "default",
        integration: {
          url: MMBOT_ACTION_URL,
          context: {
            action_type: action.action_type,
            data: action.context || {},
          },
        },
      }));
    }
    return a;
  });
}

function postToMattermost(meta, text, attachments) {
  return new Promise((resolve, reject) => {
    const props = {};
    const built = buildAttachments(attachments);
    if (built) props.attachments = built;
    const body = {
      channel_id: meta.channel_id,
      message: text,
      // 채널 멘션이면 thread reply, DM이면 일반 post (root_id 비움)
      root_id: meta.channel_type === "D" ? "" : meta.root_id || meta.post_id || "",
    };
    if (Object.keys(props).length > 0) body.props = props;
    const payload = JSON.stringify(body);
    const url = new URL(MM_BASE_URL + "/api/v4/posts");
    const transport = url.protocol === "https:" ? https : http;
    const options = {
      hostname: url.hostname,
      port: url.port || (url.protocol === "https:" ? 443 : 80),
      path: url.pathname,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${MM_BOT_TOKEN}`,
        "Content-Length": Buffer.byteLength(payload),
      },
    };
    const req = transport.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        if (res.statusCode >= 400) {
          process.stderr.write(`[mmbot] MM ${res.statusCode} body=${data.slice(0,300)}\n`);
          reject(new Error(`MM returned ${res.statusCode}: ${data.slice(0, 200)}`));
        } else {
          resolve(data);
        }
      });
    });
    req.on("error", (err) => {
      process.stderr.write(`[mmbot] MM req error: ${err.message}\n`);
      reject(err);
    });
    // 15초 timeout — hang 방지
    req.setTimeout(15000, () => {
      process.stderr.write(`[mmbot] MM req TIMEOUT (15s) — aborting\n`);
      req.destroy(new Error("MM post timeout 15s"));
    });
    req.write(payload);
    req.end();
  });
}

// MM 게시물 삭제 (조회중 안내 메시지 정리용)
function deleteMattermostPost(postId) {
  return new Promise((resolve, reject) => {
    const url = new URL(`${MM_BASE_URL}/api/v4/posts/${postId}`);
    const transport = url.protocol === "https:" ? https : http;
    const options = {
      hostname: url.hostname,
      port: url.port || (url.protocol === "https:" ? 443 : 80),
      path: url.pathname,
      method: "DELETE",
      headers: { Authorization: `Bearer ${MM_BOT_TOKEN}` },
    };
    const req = transport.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        if (res.statusCode >= 400) reject(new Error(`delete ${res.statusCode}`));
        else resolve(data);
      });
    });
    req.on("error", reject);
    req.setTimeout(8000, () => req.destroy(new Error("delete timeout")));
    req.end();
  });
}

// ── HEADLESS: 요청당 claude --print 1회 spawn ─────────────────────────
function runHeadlessClaude(prompt) {
  return new Promise((resolve, reject) => {
    const args = [
      "--print",
      "--model", "haiku",
      "--mcp-config", HEADLESS_MCP_CFG,
      "--strict-mcp-config",
      "--system-prompt-file", HEADLESS_SP,
      "--dangerously-skip-permissions",
      prompt,
    ];
    const child = spawn(HEADLESS_CLAUDE_BIN, args, {
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, CLAUDECODE: "1" },
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (c) => (stdout += c.toString("utf8")));
    child.stderr.on("data", (c) => (stderr += c.toString("utf8")));
    const timer = setTimeout(() => {
      try { child.kill("SIGKILL"); } catch {}
      reject(new Error(`claude --print timeout ${HEADLESS_TIMEOUT_MS}ms`));
    }, HEADLESS_TIMEOUT_MS);
    child.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve(stdout.trim());
      } else {
        reject(
          new Error(
            `claude --print exit=${code} stderr=${stderr.slice(0, 300)}`
          )
        );
      }
    });
  });
}

// ── stdio 연결 ────────────────────────────────────────────────────────
await mcp.connect(new StdioServerTransport());

// ── HTTP 수신 서버 (listener → channel notification) ──────────────────
const httpServer = http.createServer(async (req, res) => {
  if (req.method !== "POST") {
    res.writeHead(405);
    res.end("Method Not Allowed");
    return;
  }
  let body = "";
  for await (const chunk of req) body += chunk;

  try {
    const data = JSON.parse(body);
    const {
      request_id,
      user,
      channel_id,
      channel_name,
      channel_type, // "D" = DM, "O" = open, "P" = private
      post_id,
      root_id,
      text,
      mm_file_ids,
      allowed_tools,
      persona_name,
    } = data;

    if (!request_id || !channel_id || (!text && !(Array.isArray(mm_file_ids) && mm_file_ids.length))) {
      res.writeHead(400);
      res.end("request_id, channel_id, (text or mm_file_ids) required");
      return;
    }

    requestMeta.set(request_id, {
      user,
      channel_id,
      channel_name,
      channel_type,
      post_id,
      root_id,
      user_text: text,
    });
    // 오래된 메타 정리
    if (requestMeta.size > 100) {
      const oldest = requestMeta.keys().next().value;
      requestMeta.delete(oldest);
    }

    const personaNote = persona_name
      ? `\n[채널: ${persona_name}, 허용도구: ${allowed_tools || "all"}]`
      : "";

    // MM 첨부파일 ID — write_preview_email_send 의 mm_file_ids 파라미터로 그대로 전달해야
    // SMTP MIME 첨부로 발송됨. 본문 별도 처리 금지 (링크 변환 X).
    const mmFiles = Array.isArray(mm_file_ids) ? mm_file_ids : [];
    const filesNote = mmFiles.length
      ? `\n[MM_첨부_파일_ID: ${mmFiles.join(",")} — 이메일 발송 시 write_preview_email_send 의 mm_file_ids 파라미터로 그대로 전달하라. SMTP MIME 직접 첨부로 발송됨.]`
      : "";

    process.stderr.write(
      `[mmbot] incoming: ${request_id} ch=${channel_name || channel_id} user=${user} mm_files=${mmFiles.length} headless=${USE_HEADLESS}: ${(text || "").slice(0, 60)}\n`
    );

    if (USE_HEADLESS) {
      // 응답 path: claude --print 1회 spawn → stdout → MM post 직접
      // HTTP는 즉시 queued로 응답하고 백그라운드에서 처리
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "queued-headless", request_id }));

      const headlessMeta = {
        user,
        channel_id,
        channel_name,
        channel_type,
        post_id,
        root_id,
        user_text: text,
      };
      const prompt = (text || "") + personaNote + filesNote;
      (async () => {
        const started = Date.now();
        // 1) 즉시 "조회 중" 안내 게시 → post_id 보관 (이후 정리)
        let stubPostId = null;
        try {
          const stubResp = await postToMattermost(
            headlessMeta,
            "🔍 조회 중입니다...",
            null
          );
          try {
            stubPostId = JSON.parse(stubResp).id || null;
          } catch {
            stubPostId = null;
          }
        } catch (stubErr) {
          process.stderr.write(
            `[mmbot-headless] stub-post FAILED ${request_id}: ${stubErr.message}\n`
          );
        }

        // 2) claude --print 실행 → 3) 최종 답글 게시 → 4) 안내 메시지 삭제
        try {
          const reply = await runHeadlessClaude(prompt);
          if (!reply) {
            process.stderr.write(
              `[mmbot-headless] empty reply ${request_id} elapsed=${Date.now() - started}ms\n`
            );
            if (stubPostId) {
              try { await deleteMattermostPost(stubPostId); } catch {}
            }
            return;
          }
          await postToMattermost(headlessMeta, reply, null);
          process.stderr.write(
            `[mmbot-headless] posted ${request_id} elapsed=${Date.now() - started}ms len=${reply.length}\n`
          );
          if (stubPostId) {
            try { await deleteMattermostPost(stubPostId); } catch (delErr) {
              process.stderr.write(
                `[mmbot-headless] stub-delete FAILED ${request_id}: ${delErr.message}\n`
              );
            }
          }
        } catch (err) {
          process.stderr.write(
            `[mmbot-headless] FAILED ${request_id} elapsed=${Date.now() - started}ms err=${err.message}\n`
          );
          try {
            await postToMattermost(
              headlessMeta,
              `⚠️ (봇 처리 실패) ${String(err.message).slice(0, 200)}`,
              null
            );
          } catch (postErr) {
            process.stderr.write(
              `[mmbot-headless] error-post FAILED ${request_id}: ${postErr.message}\n`
            );
          }
          if (stubPostId) {
            try { await deleteMattermostPost(stubPostId); } catch {}
          }
        }
      })();
      return;
    }

    await mcp.notification({
      method: "notifications/claude/channel",
      params: {
        content: (text || "") + personaNote + filesNote,
        meta: {
          request_id,
          user: user || "anonymous",
          channel: channel_name || channel_id,
          channel_type: channel_type || "O",
          allowed_tools: allowed_tools || "",
          mm_file_ids: mmFiles,
        },
      },
    });

    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "queued", request_id }));
  } catch (err) {
    process.stderr.write(`[mmbot] http error: ${err.message}\n`);
    res.writeHead(500);
    res.end(err.message);
  }
});

httpServer.listen(MMBOT_PORT, "127.0.0.1", () => {
  process.stderr.write(
    `[mmbot] HTTP listening on 127.0.0.1:${MMBOT_PORT} (bot=${MM_BOT_USER_ID})\n`
  );
});
