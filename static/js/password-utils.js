/**
 * 비밀번호 공통 유틸: 마스킹 토글 + 규칙 검증
 * - 모든 input[type=password]에 눈 아이콘 자동 추가
 * - data-pw-rule 속성이 있는 input에 실시간 규칙 표시
 *
 * 규칙: 영문 소문자, 대문자, 특수문자, 숫자 중 3종 이상 조합 + 8자리 이상
 */
(function(){
    // ── 1. 마스킹 토글 (눈 아이콘) ──
    document.querySelectorAll('input[type="password"]').forEach(function(input){
        // 이미 처리됨
        if (input.dataset.pwToggled) return;
        input.dataset.pwToggled = '1';

        var wrapper = document.createElement('div');
        wrapper.style.cssText = 'position:relative;display:flex;align-items:center;';
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.tabIndex = -1;
        btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
        btn.style.cssText = 'position:absolute;right:8px;top:50%;transform:translateY(-50%);background:none;border:none;cursor:pointer;padding:2px;line-height:0;z-index:2;';
        btn.title = '비밀번호 보기';
        wrapper.appendChild(btn);
        input.style.paddingRight = '36px';

        btn.addEventListener('click', function(){
            if (input.type === 'password') {
                input.type = 'text';
                btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
            } else {
                input.type = 'password';
                btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
            }
            input.focus();
        });
    });

    // ── 2. 비밀번호 규칙 검증 (data-pw-rule 속성) ──
    document.querySelectorAll('[data-pw-rule]').forEach(function(input){
        if (input.dataset.pwRuleBound) return;
        input.dataset.pwRuleBound = '1';

        var hint = document.createElement('div');
        hint.style.cssText = 'font-size:.72rem;margin-top:4px;line-height:1.4;';
        hint.innerHTML =
            '<div data-r="len" style="color:#94a3b8">8자리 이상</div>' +
            '<div data-r="types" style="color:#94a3b8">영문 대문자, 소문자, 숫자, 특수문자 중 3종 이상</div>';
        // wrapper 뒤에 삽입
        var parent = input.closest('div[style*="position:relative"]') || input.parentNode;
        parent.parentNode.insertBefore(hint, parent.nextSibling);

        input.addEventListener('input', function(){
            var v = input.value;
            var lenOk = v.length >= 8;
            var types = 0;
            if (/[a-z]/.test(v)) types++;
            if (/[A-Z]/.test(v)) types++;
            if (/[0-9]/.test(v)) types++;
            if (/[^a-zA-Z0-9]/.test(v)) types++;
            var typesOk = types >= 3;

            var rLen = hint.querySelector('[data-r="len"]');
            var rTypes = hint.querySelector('[data-r="types"]');
            rLen.style.color = lenOk ? '#16a34a' : '#ef4444';
            rLen.innerHTML = (lenOk ? '&#10003; ' : '&#10007; ') + '8자리 이상';
            rTypes.style.color = typesOk ? '#16a34a' : '#ef4444';
            rTypes.innerHTML = (typesOk ? '&#10003; ' : '&#10007; ') + '영문 대문자, 소문자, 숫자, 특수문자 중 3종 이상';

            input.setCustomValidity(lenOk && typesOk ? '' : '비밀번호 규칙을 충족하지 않습니다.');
        });
    });

    // ── 3. 비밀번호 확인 매칭 (data-pw-match="selector") ──
    document.querySelectorAll('[data-pw-match]').forEach(function(confirmInput){
        if (confirmInput.dataset.pwMatchBound) return;
        confirmInput.dataset.pwMatchBound = '1';
        var srcSelector = confirmInput.dataset.pwMatch;

        function check(){
            var srcInput = document.querySelector(srcSelector);
            if (!srcInput) return;
            if (confirmInput.value && confirmInput.value !== srcInput.value) {
                confirmInput.setCustomValidity('비밀번호가 일치하지 않습니다.');
                confirmInput.classList.add('is-invalid');
            } else {
                confirmInput.setCustomValidity('');
                confirmInput.classList.remove('is-invalid');
            }
        }
        confirmInput.addEventListener('input', check);
        var srcInput = document.querySelector(srcSelector);
        if (srcInput) srcInput.addEventListener('input', check);
    });
})();
