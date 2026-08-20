/* ═══ 중복 제출 방지 (전역) ═══
 *
 * 두 가지 경로를 각각 막는다.
 *   1) <form method="POST"> 이중 제출 — 더블클릭으로 DB 행이 2건 생기는 사고
 *   2) onclick 핸들러가 쏘는 non-GET fetch — 응답 올 때까지 해당 버튼 잠금
 *
 * csrf-inject.js 다음에 로드할 것 (fetch 래퍼가 CSRF 래퍼를 감싸야 토큰이 실린다).
 *
 * 예외가 필요하면 form 에 data-allow-resubmit, 버튼에 data-allow-doubleclick.
 */
(function () {
    'use strict';

    var BUSY_TEXT = '처리 중...';
    var FAILSAFE_MS = 15000;   // 제출 후 페이지 전환이 없을 때 버튼이 영구히 죽는 것 방지

    // ────────────────────────────────────────────────
    // 공통 잠금/해제
    // ────────────────────────────────────────────────
    function lock(el, swapText) {
        if (el.__lsLocked) return;
        el.__lsLocked = true;
        if (el.tagName === 'A') {
            el.classList.add('disabled');          // Bootstrap: pointer-events 차단
            el.setAttribute('aria-disabled', 'true');
        } else {
            el.disabled = true;
        }
        if (swapText && el.tagName === 'BUTTON') {
            el.__lsHtml = el.innerHTML;
            el.innerHTML = BUSY_TEXT;
        }
    }

    function unlock(el) {
        if (!el.__lsLocked) return;
        el.__lsLocked = false;
        if (el.tagName === 'A') {
            el.classList.remove('disabled');
            el.removeAttribute('aria-disabled');
        } else {
            el.disabled = false;
        }
        if (el.__lsHtml != null) {
            el.innerHTML = el.__lsHtml;
            el.__lsHtml = null;
        }
    }

    // ────────────────────────────────────────────────
    // 1. 폼 이중 제출 차단
    // ────────────────────────────────────────────────
    function submitButtonsOf(form) {
        // type 없는 <button>은 기본이 submit. type="button"(행추가 등)은 건드리지 않는다.
        return form.querySelectorAll(
            'button[type="submit"], button:not([type]), input[type="submit"], input[type="image"]'
        );
    }

    function unlockForm(form) {
        form.__lsSubmitting = false;
        submitButtonsOf(form).forEach(unlock);
    }
    window.LS_unlockForm = unlockForm;   // AJAX 폼에서 실패 시 직접 풀 수 있게 노출

    // bubble 단계 — 폼 자신의 검증 리스너가 먼저 돌고 나서 여기로 온다.
    document.addEventListener('submit', function (ev) {
        var form = ev.target;
        if (!form || form.tagName !== 'FORM') return;
        if ((form.getAttribute('method') || 'get').toLowerCase() === 'get') return;  // 검색폼 제외
        if (form.hasAttribute('data-allow-resubmit')) return;

        if (form.__lsSubmitting) {          // 이미 제출 중 → 두 번째 제출 차단
            ev.preventDefault();
            return;
        }
        // 검증 실패·confirm 취소로 이미 막힌 제출은 잠그지 않는다 (버튼이 죽어버림)
        if (ev.defaultPrevented) return;

        form.__lsSubmitting = true;

        // 지금 당장 disable 하면 제출 버튼의 name/value 가 payload 에서 빠진다.
        // 직렬화가 끝난 다음 tick 에 잠근다.
        var btns = submitButtonsOf(form);
        setTimeout(function () {
            btns.forEach(function (b) { lock(b, true); });
        }, 0);

        setTimeout(function () { unlockForm(form); }, FAILSAFE_MS);
    });

    // 뒤로가기(bfcache)로 돌아왔을 때 잠긴 채로 남지 않게
    window.addEventListener('pageshow', function (ev) {
        if (!ev.persisted) return;
        document.querySelectorAll('form').forEach(unlockForm);
    });

    // ────────────────────────────────────────────────
    // 2. onclick → fetch 버튼 잠금
    //    클릭을 capture 로 먼저 잡아 "지금 눌린 버튼"을 기록해두고,
    //    그 핸들러가 동기적으로 쏜 non-GET fetch 가 끝날 때까지 그 버튼을 잠근다.
    // ────────────────────────────────────────────────
    var activeBtn = null;

    document.addEventListener('click', function (ev) {
        var t = ev.target;
        var b = (t && t.closest) ? t.closest('button, input[type="button"], a.btn') : null;
        if (b && !b.disabled && !b.hasAttribute('data-allow-doubleclick')) {
            activeBtn = b;
            // 핸들러가 동기적으로 도는 동안만 유효. 끝나면 해제.
            setTimeout(function () { activeBtn = null; }, 0);
        }
    }, true);

    // ────────────────────────────────────────────────
    // 3. 업로드 중복 실행 차단 헬퍼
    //    파일 업로드는 버튼이 아니라 input change / drop 이벤트로 시작해서
    //    위의 클릭 가드가 안 걸린다. 호출부에서 begin/end 로 직접 감싼다.
    //    키는 파일 신원(이름:크기:수정시각) — 같은 파일 재전송만 막고 다른 파일은 통과.
    // ────────────────────────────────────────────────
    var uploading = new Set();
    window.LSUpload = {
        key: function (prefix, file) {
            return prefix + ':' + file.name + ':' + file.size + ':' + (file.lastModified || 0);
        },
        begin: function (key) {
            if (uploading.has(key)) return false;   // 이미 올라가는 중
            uploading.add(key);
            return true;
        },
        end: function (key) { uploading.delete(key); }
    };

    var _fetch = window.fetch;
    window.fetch = function (url, opts) {
        var method = ((opts && opts.method) || 'GET').toUpperCase();
        if (method === 'GET' || method === 'HEAD' || !activeBtn) {
            return _fetch.apply(this, arguments);
        }

        var btn = activeBtn;
        btn.__lsPending = (btn.__lsPending || 0) + 1;
        lock(btn, false);   // 텍스트는 그대로 — 응답이 빠르면 깜빡임만 남는다

        var released = false;
        var release = function () {
            if (released) return;
            released = true;
            btn.__lsPending -= 1;
            if (btn.__lsPending <= 0) unlock(btn);
        };
        // 요청이 끝내 안 끝나도 버튼이 영구히 죽지 않게
        setTimeout(release, FAILSAFE_MS * 2);

        var p = _fetch.apply(this, arguments);
        p.then(release, release);   // 응답 본문은 손대지 않는다
        return p;
    };
})();
