/**
 * 한글(.hwp/.hwpx) 첨부 → 미리보기 HTML.
 *
 * 왜 이 파일이 Node 인가: 한글 파서(@rhwp/core)는 Rust+WASM 이고 npm 으로만 온다.
 * ERP 는 파이썬이라 여기만 따로 떼어 subprocess 로 부른다
 * (modules/services/hwp_preview.py).
 *
 * **getPageText 가 아니라 getPageTextLayout 을 쓴다.** getPageText 는 표 안의
 * 글자를 통째로 버린다 — 실측에서 심사기준표 .hwpx 가 493자로 나왔고 「배점」이
 * 아예 없었다. 공고문·서식은 표가 알맹이라 그걸 잃으면 미리보기를 볼 이유가 없다.
 * getPageTextLayout 은 글자마다 x·y·크기를 주므로, 표를 복원하지 않아도
 * **그 자리에 그대로 세우면** 원본과 같은 모양이 나온다.
 *
 * 쓰기: node render.mjs <파일경로> [최대쪽수]  → stdout 으로 HTML
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import init, { HwpDocument } from '@rhwp/core';

const here = dirname(fileURLToPath(import.meta.url));
const esc = (s) => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

const [, , filePath, maxPagesArg] = process.argv;
if (!filePath) {
  console.error('사용법: node render.mjs <파일경로> [최대쪽수]');
  process.exit(2);
}
const MAX_PAGES = Math.max(1, Math.min(Number(maxPagesArg) || 30, 100));

// wasm 은 **바이트를 직접 넘긴다**. README 의 '/rhwp_bg.wasm' 경로 방식은 브라우저용이라
// Node 에서는 못 찾는다.
await init({ module_or_path: readFileSync(join(here, 'node_modules/@rhwp/core/rhwp_bg.wasm')) });

const doc = new HwpDocument(new Uint8Array(readFileSync(filePath)));
const pageCount = doc.pageCount();
const shown = Math.min(pageCount, MAX_PAGES);

const pages = [];
for (let i = 0; i < shown; i++) {
  let runs = [];
  try {
    runs = JSON.parse(doc.getPageTextLayout(i)).runs || [];
  } catch {
    runs = [];   // 한 쪽이 깨져도 나머지는 보여 준다
  }
  // 쪽 크기는 글자 위치에서 거꾸로 잡는다 — 파서가 용지 크기를 따로 주지 않는다
  let w = 0;
  let h = 0;
  for (const r of runs) {
    w = Math.max(w, (r.x || 0) + (r.w || 0));
    h = Math.max(h, (r.y || 0) + (r.h || 0));
  }
  const spans = runs.map((r) => {
    const style = [
      `left:${(r.x || 0).toFixed(1)}px`,
      `top:${(r.y || 0).toFixed(1)}px`,
      `font-size:${(r.fontSize || 10).toFixed(1)}px`,
      r.bold ? 'font-weight:700' : '',
      r.italic ? 'font-style:italic' : '',
      r.textColor && r.textColor !== '#000000' ? `color:${esc(r.textColor)}` : '',
      r.fontFamily ? `font-family:'${esc(r.fontFamily)}',sans-serif` : '',
    ].filter(Boolean).join(';');
    return `<span style="${style}">${esc(r.text)}</span>`;
  }).join('');
  pages.push(
    `<div class="pg" style="width:${Math.ceil(w + 40)}px;height:${Math.ceil(h + 40)}px">${spans}</div>`,
  );
}

const note = pageCount > shown
  ? `<p class="more">${pageCount}쪽 가운데 앞 ${shown}쪽만 보여 드립니다. 전체는 내려받아 보십시오.</p>`
  : '';

process.stdout.write(`<!doctype html><meta charset="utf-8"><style>
 body{margin:0;background:#525659;font-family:'맑은 고딕','Malgun Gothic',sans-serif}
 .pg{position:relative;background:#fff;margin:14px auto;box-shadow:0 2px 10px rgba(0,0,0,.4)}
 .pg span{position:absolute;white-space:pre}
 .more{margin:14px;color:#e2e8f0;font-size:13px;text-align:center}
</style>${pages.join('')}${note}`);
