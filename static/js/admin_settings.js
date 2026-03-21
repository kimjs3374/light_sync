/* admin_settings.js — 관리자 설정 페이지 전용 JS */

/* 개인 추가 메뉴 모달 */
function openExtraMenuModal(userId, userName, currentMenus) {
    document.getElementById('extraMenuUserId').value = userId;
    document.getElementById('extraMenuUserName').textContent = userName;
    var menus = currentMenus ? currentMenus.split(',') : [];
    document.querySelectorAll('.extra-menu-cb').forEach(function(cb) {
        cb.checked = menus.indexOf(cb.value) !== -1;
    });
    new bootstrap.Modal(document.getElementById('extraMenuModal')).show();
}

/* 비밀번호 초기화 모달 */
function openResetPwModal(userId, userName) {
    document.getElementById('resetPwUserName').textContent = userName;
    document.getElementById('resetPwForm').action = window.ADMIN_RESET_PW_URL.replace('/0', '/' + userId);
    new bootstrap.Modal(document.getElementById('resetPwModal')).show();
}

/* 사용자 검색 필터 */
function filterUsers() {
    var keyword = document.getElementById('userSearchInput').value.trim().toLowerCase();
    var group = document.getElementById('groupFilter').value;
    document.querySelectorAll('#userTableBody tr').forEach(function(row) {
        var name = (row.getAttribute('data-name') || '').toLowerCase();
        var rowGroup = row.getAttribute('data-group') || '';
        row.style.display = (!keyword || name.includes(keyword)) && (!group || rowGroup === group) ? '' : 'none';
    });
}

/* 삭제요청 반려 사유 */
function submitRejectReason(form) {
    var reason = prompt('반려 사유를 입력하세요. (선택)');
    if (reason !== null) {
        form.querySelector('input[name="reject_reason"]').value = reason.trim();
    }
    return confirm('삭제요청을 반려할까요?');
}

/* 퇴사/복구 토글 */
function submitToggleUserActive(form) {
    var isCurrentlyActive = form.getAttribute('data-current-active') === '1';
    if (isCurrentlyActive) {
        var reason = prompt('퇴사/비활성 사유를 입력하세요. (선택)');
        if (reason === null) return false;
        form.querySelector('input[name="deactivated_reason"]').value = (reason || '').trim();
        return confirm('해당 계정을 비활성화(로그인 차단)할까요?');
    }
    return confirm('해당 계정을 재활성화할까요?');
}

/* URL 해시로 탭 복원 */
(function() {
    var hash = window.location.hash;
    if (hash) {
        var tab = document.querySelector('#adminTab button[data-bs-target="' + hash + '"]');
        if (tab) new bootstrap.Tab(tab).show();
    }
    document.querySelectorAll('#adminTab button[data-bs-toggle="tab"]').forEach(function(btn) {
        btn.addEventListener('shown.bs.tab', function(e) {
            history.replaceState(null, null, e.target.getAttribute('data-bs-target'));
        });
    });
})();

function updatePosition(userId, position) {
    var form = new FormData();
    form.append('position', position);
    fetch('/update_position/' + userId, { method: 'POST', body: form })
        .then(function(r) { return r.json(); })
        .then(function(d) { if (!d.ok) alert(d.error || '실패'); })
        .catch(function() { alert('직급 변경 실패'); });
}

function saveOps(key, value) {
    var form = new FormData();
    form.append('key', key);
    form.append('value', value);
    fetch('/admin/update_ops_setting', { method: 'POST', body: form })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.ok) alert('저장되었습니다.');
            else alert(d.error || '저장 실패');
        })
        .catch(function() { alert('저장 실패'); });
}
