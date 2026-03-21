/* ═══ 챗봇 슬라이드 패널 ═══ */
var _chatPanelBusy = false;
var _chatPanelLoaded = false;
var _panelChannelAllowed = false;
var _panelEngine = 'groq';

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
    _panelUpdateUI();

    if (_panelEngine === 'claude') {
        // 연결 확인은 비동기로 — UI는 이미 전환됨
        fetch('/channel-chat/history').then(function(r) {
            if (r.ok) return r.json();
            throw new Error();
        }).then(function(msgs) {
            msgs.forEach(function(m) { appendChatMsg(m.content, m.role === 'user' ? 'user' : 'bot'); });
            _chatPanelLoaded = true;
        }).catch(function() {
            appendChatMsg('Claude Channel 서버에 연결할 수 없습니다.', 'bot');
        });
    } else {
        _loadPanelHistory();
    }
}

function appendChatMsg(text, role) {
    var box = document.getElementById('chatPanelBox');
    var d = document.createElement('div');
    var cls = 'chat-msg ' + (role === 'user' ? 'chat-msg-user' : 'chat-msg-bot');
    if (role !== 'user' && _panelEngine === 'claude') cls += ' claude';
    d.className = cls;
    d.textContent = text;
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
    return d;
}

async function _loadPanelHistory() {
    var url = _PANEL_ENGINES[_panelEngine].historyUrl;
    if (!url) return;
    try {
        var res = await fetch(url);
        var msgs = await res.json();
        msgs.forEach(function(m) { appendChatMsg(m.content, m.role === 'user' ? 'user' : 'bot'); });
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
        var res = await fetch(e.sendUrl, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: text}) });
        var data = await res.json();
        thinking.remove();
        if (res.status === 502 && _panelEngine === 'claude') {
            appendChatMsg('Claude Channel 서버에 연결할 수 없습니다.', 'bot');
        } else {
            appendChatMsg(data.reply || data.error || '오류', 'bot');
        }
    } catch {
        thinking.remove();
        appendChatMsg('오류가 발생했습니다.', 'bot');
    } finally {
        _chatPanelBusy = false;
        input.focus();
    }
}

async function clearChatPanel() {
    var e = _PANEL_ENGINES[_panelEngine];
    await fetch(e.sendUrl, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: '초기화'}) });
    document.getElementById('chatPanelBox').innerHTML = '';
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
