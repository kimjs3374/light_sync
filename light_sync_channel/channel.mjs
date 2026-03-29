#!/usr/bin/env node
/**
 * Light-Sync ERP Channel Server
 *
 * 웹 채팅 UI → HTTP POST (localhost:8788) → Claude Code session
 * Claude reply tool → HTTP POST → Flask (/channel-chat/channel-reply)
 *
 * 양방향 Channel: 웹 유저의 질문을 Claude Code에 전달하고,
 * Claude의 응답을 Flask 서버로 돌려보냄
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import http from "node:http";

const FLASK_PORT = parseInt(process.env.FLASK_PORT || "5000", 10);
const CHANNEL_PORT = parseInt(process.env.CHANNEL_PORT || "8788", 10);

// ── MCP Server (Channel) ─────────────────────────────────────────────
const mcp = new Server(
  { name: "lightsync-erp-chat", version: "0.1.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {} },
      tools: {},
    },
    instructions: `당신은 Light-Sync ERP 어시스턴트입니다.
웹 채팅 메시지가 <channel source="lightsync-erp-chat" request_id="..." user="..." session_id="..."> 태그로 도착합니다.

**중요 규칙:**
1. 메시지를 받으면 기존 MCP tool(light-sync-erp 서버)을 사용하여 ERP 데이터를 조회하세요.
2. 조회 결과를 요약한 뒤, 반드시 channel_reply 도구를 호출하여 웹 유저에게 응답을 보내세요.
3. channel_reply 호출 시 request_id를 반드시 태그에서 가져와 전달하세요.
4. 한국어로 간결하게 답변하세요. 숫자는 한국 단위(건, 개, 원)로 표시하세요.
5. 데이터 조회가 필요 없는 일반 질문도 channel_reply로 응답하세요.
6. 메시지에 [허용 도구: ...] 목록이 있으면 해당 도구만 사용하세요. 목록에 없는 도구 호출 시 "해당 기능은 사용 권한이 없습니다."라고 channel_reply하세요.
7. **MCP 도구를 2개 이상 호출해야 하는 복잡한 질문이면**, 먼저 channel_reply(partial=true)로 "분석 중입니다. 잠시만 기다려주세요." 같은 안내 메시지를 보낸 뒤 작업을 시작하세요. 마지막 최종 답변은 partial 없이 보내세요.`,
  }
);

// ── Reply Tool ────────────────────────────────────────────────────────
mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "channel_reply",
      description:
        "웹 채팅 유저에게 응답을 보냅니다. 반드시 request_id를 포함하세요.",
      inputSchema: {
        type: "object",
        properties: {
          request_id: {
            type: "string",
            description: "요청 시 전달받은 request_id (channel 태그 속성)",
          },
          text: {
            type: "string",
            description: "유저에게 보낼 응답 메시지",
          },
          partial: {
            type: "boolean",
            description:
              "true면 중간 안내 메시지 (작업 계속 진행). 생략 또는 false면 최종 답변.",
            default: false,
          },
        },
        required: ["request_id", "text"],
      },
    },
  ],
}));

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  if (req.params.name === "channel_reply") {
    const { request_id, text, partial } = req.params.arguments;
    const label = partial ? "partial" : "final";
    process.stderr.write(`[channel] reply tool called (${label}): ${request_id} → Flask:${FLASK_PORT}\n`);
    try {
      await postToFlask(request_id, text, !!partial);
      process.stderr.write(`[channel] reply delivered (${label}): ${request_id}\n`);
      return { content: [{ type: "text", text: "sent" }] };
    } catch (err) {
      process.stderr.write(`[channel] reply FAILED: ${err.message}\n`);
      return {
        content: [{ type: "text", text: `reply failed: ${err.message}` }],
      };
    }
  }
  throw new Error(`unknown tool: ${req.params.name}`);
});

// ── Flask 서버로 POST ─────────────────────────────────────────────────
function postToFlask(requestId, text, partial = false) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({ request_id: requestId, text, partial });
    const options = {
      hostname: "127.0.0.1",
      port: FLASK_PORT,
      path: "/channel-chat/channel-reply",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
      },
    };
    const req = http.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        if (res.statusCode >= 400) {
          reject(new Error(`Flask returned ${res.statusCode}: ${data}`));
        } else {
          resolve(data);
        }
      });
    });
    req.on("error", reject);
    req.write(payload);
    req.end();
  });
}

// ── stdio 연결 ────────────────────────────────────────────────────────
await mcp.connect(new StdioServerTransport());

// ── HTTP 서버 (Flask → Channel) ──────────────────────────────────────
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
    const { request_id, user, session_id, text, allowed_tools } = data;

    if (!request_id || !text) {
      res.writeHead(400);
      res.end("request_id and text required");
      return;
    }

    // 허용 도구 제한 메시지 구성
    const toolNote = allowed_tools
      ? `\n[허용 도구: ${allowed_tools}]\n위 목록에 없는 MCP 도구는 사용하지 마세요.`
      : "";

    // Claude Code 세션에 channel notification 전송
    process.stderr.write(`[channel] incoming: ${request_id} from ${user}: ${text.slice(0, 50)}\n`);
    await mcp.notification({
      method: "notifications/claude/channel",
      params: {
        content: text + toolNote,
        meta: {
          request_id: request_id,
          user: user || "anonymous",
          session_id: session_id || "unknown",
          allowed_tools: allowed_tools || "",
        },
      },
    });

    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "queued", request_id }));
  } catch (err) {
    res.writeHead(500);
    res.end(err.message);
  }
});

httpServer.listen(CHANNEL_PORT, "127.0.0.1", () => {
  // stderr로 출력 (stdout은 MCP stdio가 사용)
  process.stderr.write(
    `[channel] HTTP listening on 127.0.0.1:${CHANNEL_PORT}\n`
  );
});
