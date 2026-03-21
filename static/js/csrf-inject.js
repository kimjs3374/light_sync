/* ═══ CSRF Token auto-injection for AJAX requests ═══ */
(function() {
    var csrfToken = document.querySelector('meta[name="csrf-token"]');
    if (!csrfToken) return;
    var token = csrfToken.getAttribute('content');

    // fetch override
    var _fetch = window.fetch;
    window.fetch = function(url, opts) {
        opts = opts || {};
        if (opts.method && opts.method.toUpperCase() !== 'GET') {
            opts.headers = opts.headers || {};
            if (opts.headers instanceof Headers) {
                if (!opts.headers.has('X-CSRFToken')) opts.headers.set('X-CSRFToken', token);
            } else {
                opts.headers['X-CSRFToken'] = opts.headers['X-CSRFToken'] || token;
            }
        }
        return _fetch(url, opts);
    };

    // XMLHttpRequest override
    var _open = XMLHttpRequest.prototype.open;
    var _send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method) {
        this._csrfMethod = method;
        return _open.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function() {
        if (this._csrfMethod && this._csrfMethod.toUpperCase() !== 'GET') {
            this.setRequestHeader('X-CSRFToken', token);
        }
        return _send.apply(this, arguments);
    };
})();
