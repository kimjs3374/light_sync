/* 금액 입력 공용 모듈 — 천단위 콤마 표시 + 정수만 (소수점 불가)
 *
 * 쓰는 법: <input type="text" class="money-input" inputmode="numeric" name="unit_price[]">
 *   · 타이핑하는 대로 1,234,567 로 포맷된다
 *   · 숫자 외 문자는 전부 무시 -> 소수점·문자 입력 자체가 불가능
 *   · JS로 나중에 추가한 행도 자동으로 잡힌다 (MutationObserver)
 *
 * 값 읽기는 반드시 Money.val(el) 을 쓸 것.
 * el.value 는 '1,234' 라서 parseFloat 하면 1 이 된다.
 *
 * type=number 를 못 쓰는 이유: 브라우저가 '1,234' 를 유효값으로 인정하지 않아
 * .value 가 빈 문자열이 되어버린다. 그래서 text + inputmode=numeric 이다.
 */
(function (global) {
    'use strict';

    function digits(v) {
        return String(v == null ? '' : v).replace(/[^0-9]/g, '');
    }

    function fmt(v) {
        var s = digits(v);
        if (!s) return '';
        s = s.replace(/^0+(?=\d)/, '');           // 0012 -> 12
        return parseInt(s, 10).toLocaleString('ko-KR');
    }

    function val(el) {
        var s = digits(el && el.value);
        return s ? parseInt(s, 10) : 0;
    }

    // 콤마를 다시 넣으면 캐럿이 끝으로 튄다.
    // 캐럿 앞의 '숫자 개수'를 세어두고 포맷 후 같은 자리로 되돌린다.
    function reformat(el) {
        var raw = el.value;
        var before = digits(raw.slice(0, el.selectionStart || 0)).length;
        var next = fmt(raw);
        if (next === raw) return;
        el.value = next;
        var pos = 0, seen = 0;
        while (pos < next.length && seen < before) {
            if (next.charCodeAt(pos) >= 48 && next.charCodeAt(pos) <= 57) seen++;
            pos++;
        }
        try { el.setSelectionRange(pos, pos); } catch (e) { /* 일부 브라우저는 미지원 */ }
    }

    function init(root) {
        var scope = root && root.querySelectorAll ? root : document;
        var list = scope.querySelectorAll ? scope.querySelectorAll('.money-input') : [];
        Array.prototype.forEach.call(list, function (el) {
            if (el.dataset.moneyReady === '1') return;
            el.dataset.moneyReady = '1';
            if (el.type === 'number') el.type = 'text';      // 실수로 남은 것 구제
            el.setAttribute('inputmode', 'numeric');
            el.setAttribute('autocomplete', 'off');
            el.value = fmt(el.value);
        });
    }

    document.addEventListener('input', function (e) {
        if (e.target && e.target.classList && e.target.classList.contains('money-input')) {
            reformat(e.target);
        }
    });

    // 붙여넣기·자동완성으로 들어온 값도 정리
    document.addEventListener('change', function (e) {
        if (e.target && e.target.classList && e.target.classList.contains('money-input')) {
            e.target.value = fmt(e.target.value);
        }
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { init(document); });
    } else {
        init(document);
    }

    // JS로 행을 추가하는 화면(견적/발주/입고)이 많아 새 노드를 감시한다
    if (global.MutationObserver) {
        new MutationObserver(function (muts) {
            for (var i = 0; i < muts.length; i++) {
                var added = muts[i].addedNodes;
                for (var j = 0; j < added.length; j++) {
                    if (added[j].nodeType === 1) init(added[j]);
                }
            }
        }).observe(document.documentElement, { childList: true, subtree: true });
    }

    global.Money = { fmt: fmt, val: val, init: init, digits: digits };
})(window);
