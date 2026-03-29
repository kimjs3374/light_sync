/* ═══ 챗봇 슬라이드 패널 ═══ */
var _chatPanelBusy = false;
var _chatPanelLoaded = false;
var _panelChannelAllowed = false;
var _panelEngine = 'groq';
var _panelLastDateLabel = '';

var _PANEL_ENGINES = {
    groq:   { title: '\uD83D\uDCAC 매그니',      badge: 'Groq',    sendUrl: '/chatbot/send',       historyUrl: '/chatbot/history' },
    claude: { title: '\uD83D\uDCAC 고사양 매그니', badge: 'Channel', sendUrl: '/channel-chat/send', historyUrl: '/channel-chat/history' },
};

function _panelUpdateUI() {
    var e = _PANEL_ENGINES[_panelEngine];
    document.getElementById('panelTitle').textContent = e.title;
    document.getElementById('panelBadge').textContent = e.badge;
    document.getElementById('panelBadge').style.background = _panelEngine === 'claude' ? '#d97706' : 'rgba(255,255,255,.2)';
    document.getElementById('panelLblGroq').style.fontWeight = _panelEngine === 'groq' ? '700' : '400';
    document.getElementById('panelLblGroq').style.color = _panelEngine === 'groq' ? '#fff' : 'rgba(255,255,255,.5)';
    document.getElementById('panelLblClaude').style.fontWeight = _panelEngine === 'claude' ? '700' : '400';
    document.getElementById('panelLblClaude').style.color = _panelEngine === 'claude' ? '#fbbf24' : 'rgba(255,255,255,.5)';
    document.getElementById('panelEngineSwitch').checked = _panelEngine === 'claude';
    var isClaude = _panelEngine === 'claude';
    document.getElementById('panelTrack').style.background = isClaude ? '#d97706' : 'rgba(255,255,255,.3)';
    document.getElementById('panelThumb').style.left = isClaude ? '16px' : '2px';
}

function panelSwitchEngine() {
    var sw = document.getElementById('panelEngineSwitch');
    if (sw.checked && !_panelChannelAllowed) { sw.checked = false; return; }
    _panelEngine = sw.checked ? 'claude' : 'groq';
    localStorage.setItem('chatEngine', _panelEngine);
    document.getElementById('chatPanelBox').innerHTML = '';
    _chatPanelLoaded = false;
    _panelLastDateLabel = '';
    _panelUpdateUI();

    if (_panelEngine === 'claude') {
        fetch('/channel-chat/history').then(function(r) {
            if (r.ok) return r.json();
            throw new Error();
        }).then(function(msgs) {
            msgs.forEach(function(m) { appendChatMsg(m.content, m.role === 'user' ? 'user' : 'bot', m.ts || null); });
            _chatPanelLoaded = true;
        }).catch(function() {
            appendChatMsg('Claude Channel 서버에 연결할 수 없습니다.', 'bot');
        });
    } else {
        _loadPanelHistory();
    }
}

function _panelFormatTime(ts) {
    if (!ts) return '';
    var d = new Date(ts);
    if (isNaN(d)) return '';
    return d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0') + ':' + d.getSeconds().toString().padStart(2,'0');
}

function _panelDateLabel(ts) {
    if (!ts) return '';
    var d = new Date(ts);
    if (isNaN(d)) return '';
    var now = new Date();
    var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var target = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    var diff = (today - target) / 86400000;
    if (diff === 0) return '오늘';
    if (diff === 1) return '어제';
    return d.getFullYear() + '년 ' + (d.getMonth()+1) + '월 ' + d.getDate() + '일';
}

function _panelInsertDateDivider(ts) {
    var label = _panelDateLabel(ts);
    if (!label || label === _panelLastDateLabel) return;
    _panelLastDateLabel = label;
    var box = document.getElementById('chatPanelBox');
    var div = document.createElement('div');
    div.className = 'chat-date-divider';
    div.textContent = label;
    box.appendChild(div);
}

function appendChatMsg(text, role, ts) {
    var box = document.getElementById('chatPanelBox');
    // 날짜 구분선
    if (ts) _panelInsertDateDivider(ts);
    var d = document.createElement('div');
    var cls = 'chat-msg ' + (role === 'user' ? 'chat-msg-user' : 'chat-msg-bot');
    if (role !== 'user' && _panelEngine === 'claude') cls += ' claude';
    d.className = cls;
    // 내용
    var content = document.createElement('div');
    content.textContent = text;
    d.appendChild(content);
    // 시간
    var timeStr = ts ? _panelFormatTime(ts) : _panelFormatTime(new Date().toISOString());
    if (timeStr) {
        var timeEl = document.createElement('div');
        timeEl.className = 'chat-msg-time';
        timeEl.textContent = timeStr;
        d.appendChild(timeEl);
    }
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
    return d;
}

async function _loadPanelHistory() {
    var url = _PANEL_ENGINES[_panelEngine].historyUrl;
    if (!url) return;
    _panelLastDateLabel = '';
    try {
        var res = await fetch(url);
        var msgs = await res.json();
        msgs.forEach(function(m) { appendChatMsg(m.content, m.role === 'user' ? 'user' : 'bot', m.ts || null); });
    } catch(e) {}
    _chatPanelLoaded = true;
}

async function openChatbotPanel() {
    document.getElementById('chatbotPanel').classList.add('open');
    document.getElementById('chatbotBackdrop').classList.add('show');
    setTimeout(function() { document.getElementById('chatPanelInput').focus(); }, 300);
    if (!_chatPanelLoaded) _loadPanelHistory();
}

function closeChatbotPanel() {
    document.getElementById('chatbotPanel').classList.remove('open');
    document.getElementById('chatbotBackdrop').classList.remove('show');
}

async function sendChatPanel() {
    if (_chatPanelBusy) return;
    var input = document.getElementById('chatPanelInput');
    var text = input.value.trim();
    if (!text) return;
    input.value = '';
    appendChatMsg(text, 'user');
    _chatPanelBusy = true;
    var label = _panelEngine === 'claude' ? 'Claude가 처리 중...' : '...';
    var thinking = appendChatMsg(label, 'bot');
    thinking.style.color = '#999';
    try {
        var e = _PANEL_ENGINES[_panelEngine];
        var csrf = document.querySelector('meta[name="csrf-token"]')?.content;
        var headers = {'Content-Type': 'application/json'};
        if (csrf) headers['X-CSRFToken'] = csrf;
        var res = await fetch(e.sendUrl, { method: 'POST', headers: headers, body: JSON.stringify({text: text}) });
        var data = await res.json();
        if (res.status === 502 && _panelEngine === 'claude') {
            thinking.remove();
            appendChatMsg('Claude Channel 서버에 연결할 수 없습니다.', 'bot');
        } else if (_panelEngine === 'claude' && data.request_id) {
            thinking.textContent = 'Claude가 처리 중...';
            var reply = await _pollPanelReply(data.request_id, thinking, csrf);
            thinking.remove();
            if (reply) appendChatMsg(reply, 'bot');
        } else {
            thinking.remove();
            appendChatMsg(data.reply || data.error || '응답 없음', 'bot');
        }
    } catch(err) {
        thinking.remove();
        appendChatMsg('네트워크 오류: ' + err.message, 'bot');
    } finally {
        _chatPanelBusy = false;
        input.focus();
    }
}

async function _pollPanelReply(requestId, thinkingEl, csrf) {
    for (var i = 0; i < 60; i++) {
        try {
            var headers = {'Content-Type': 'application/json'};
            if (csrf) headers['X-CSRFToken'] = csrf;
            var res = await fetch('/channel-chat/poll', {
                method: 'POST', headers: headers,
                body: JSON.stringify({request_id: requestId})
            });
            if (!res.ok && res.status !== 404) { await new Promise(function(r){setTimeout(r,2000)}); continue; }
            var data = await res.json();
            if (data.status === 'done') return data.reply;
            if (data.status === 'timeout') return data.reply;
            if (data.status === 'partial') { thinkingEl.textContent = data.reply; thinkingEl.style.color = '#666'; continue; }
            if (data.status === 'not_found') { await new Promise(function(r){setTimeout(r,2000)}); continue; }
            if (data.elapsed != null) thinkingEl.textContent = 'Claude가 처리 중... (' + data.elapsed + '초)';
        } catch(e) { await new Promise(function(r){setTimeout(r,2000)}); }
    }
    return '응답 시간이 초과되었습니다.';
}

async function clearChatPanel() {
    var e = _PANEL_ENGINES[_panelEngine];
    await fetch(e.sendUrl, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: '초기화'}) });
    document.getElementById('chatPanelBox').innerHTML = '';
    _panelLastDateLabel = '';
    _chatPanelLoaded = true;
}

// 초기화: 채널 권한 확인 후 스위치 표시
fetch('/chatbot/channel-allowed').then(function(r){ return r.json(); }).then(function(d){
    _panelChannelAllowed = d.allowed;
    if (_panelChannelAllowed) {
        document.getElementById('panelSwitchWrap').style.display = '';
        document.getElementById('panelSwitchWrap').classList.add('d-flex');
        _panelEngine = localStorage.getItem('chatEngine') || 'groq';
    } else {
        _panelEngine = 'groq';
    }
    _panelUpdateUI();
}).catch(function(){ _panelUpdateUI(); });
