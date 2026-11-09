// Taskly — progressive enhancement. Every action also works without JavaScript.
(function () {
    'use strict';

    var $ = function (sel, root) { return (root || document).querySelector(sel); };
    var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
    var csrf = ($('meta[name="csrf-token"]') || {}).content || '';

    // Header gains a backdrop once the page scrolls.
    var header = $('.site-header');
    if (header) {
        var onScroll = function () { header.classList.toggle('is-scrolled', window.scrollY > 8); };
        window.addEventListener('scroll', onScroll, { passive: true });
        onScroll();
    }

    // ---------------------------------------------------------------- Toasts
    var toastRoot = $('.toasts');

    function dismiss(toast) {
        if (!toast || toast.classList.contains('is-leaving')) return;
        toast.classList.add('is-leaving');
        setTimeout(function () { toast.remove(); }, 400);
    }

    function armToast(toast) {
        var close = $('.toast-close', toast);
        if (close) close.addEventListener('click', function () { dismiss(toast); });
        var delay = toast.classList.contains('toast-error') ? 7000 : 4000;
        setTimeout(function () { dismiss(toast); }, delay);
    }

    function toast(message, category) {
        if (!toastRoot) return;
        var el = document.createElement('div');
        el.className = 'toast toast-' + (category || 'success');
        el.innerHTML = '<span class="toast-dot" aria-hidden="true"></span><span class="toast-text"></span>' +
            '<button type="button" class="toast-close" aria-label="Dismiss">&times;</button>';
        $('.toast-text', el).textContent = message;
        toastRoot.appendChild(el);
        armToast(el);
    }

    $$('.toast').forEach(armToast);

    // ------------------------------------------------------- Keyboard shortcuts
    var newTask = $('#new-task');
    var search = $('[data-search]');

    document.addEventListener('keydown', function (e) {
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        var t = e.target;
        var typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
        if (e.key === 'Escape' && typing) { t.blur(); return; }
        if (typing) return;
        if ((e.key === 'n' || e.key === 'N') && newTask) { e.preventDefault(); newTask.focus(); }
        if (e.key === '/' && search) { e.preventDefault(); search.focus(); search.select(); }
    });

    // ------------------------------------------------------------- Search & sort
    var searchForm = $('[data-search-form]');
    if (searchForm && search) {
        var timer;
        var submit = function () {
            try { sessionStorage.setItem('taskly:refocus-search', '1'); } catch (e) {}
            searchForm.submit();
        };
        search.addEventListener('input', function () {
            clearTimeout(timer);
            timer = setTimeout(submit, 450);
        });
        searchForm.addEventListener('submit', function () { clearTimeout(timer); });

        // Restore focus after a search-triggered reload so typing can continue.
        try {
            if (sessionStorage.getItem('taskly:refocus-search')) {
                sessionStorage.removeItem('taskly:refocus-search');
                search.focus();
                var len = search.value.length;
                search.setSelectionRange(len, len);
            }
        } catch (e) {}
    }
    $$('[data-autosubmit]').forEach(function (el) {
        el.addEventListener('change', function () { el.form.submit(); });
    });

    // ---------------------------------------------------------------- Capture
    function isoDate(offsetDays) {
        var d = new Date();
        d.setDate(d.getDate() + offsetDays);
        var m = String(d.getMonth() + 1).padStart(2, '0');
        var day = String(d.getDate()).padStart(2, '0');
        return d.getFullYear() + '-' + m + '-' + day;
    }

    var dueInput = $('#new-due');
    var quick = $$('[data-quick-date]');
    function syncQuick() {
        quick.forEach(function (b) {
            b.classList.toggle('is-active', dueInput && dueInput.value === isoDate(+b.dataset.quickDate));
        });
    }
    quick.forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (!dueInput) return;
            var value = isoDate(+btn.dataset.quickDate);
            dueInput.value = dueInput.value === value ? '' : value;
            syncQuick();
        });
    });
    if (dueInput) dueInput.addEventListener('change', syncQuick);

    var notesToggle = $('[data-toggle-notes]');
    var notesWrap = $('[data-notes]');
    if (notesToggle && notesWrap) {
        notesToggle.addEventListener('click', function () {
            var open = notesWrap.hidden;
            notesWrap.hidden = !open;
            notesToggle.setAttribute('aria-expanded', String(open));
            if (open) $('textarea', notesWrap).focus();
        });
    }

    var capture = $('[data-capture]');
    if (capture) {
        capture.addEventListener('submit', function () {
            var btn = $('.capture-submit', capture);
            if (btn) btn.disabled = true;
        });
    }

    // ------------------------------------------------------ Confirmations etc.
    $$('form[data-confirm]').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            if (!window.confirm(form.dataset.confirm)) e.preventDefault();
        });
    });

    $$('[data-reveal]').forEach(function (btn) {
        var input = $(btn.dataset.reveal);
        if (!input) return;
        btn.addEventListener('click', function () {
            var show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            btn.textContent = show ? 'Hide' : 'Show';
            btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
        });
    });

    $$('[data-clear]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var input = $(btn.dataset.clear);
            if (input) { input.value = ''; input.focus(); }
        });
    });

    // ------------------------------------------------- Task list without reloads
    var list = $('[data-task-list]');
    if (!list) return;
    var view = list.dataset.view || 'all';

    function request(form) {
        return fetch(form.action, {
            method: 'POST',
            headers: { 'Accept': 'application/json', 'X-CSRF-Token': csrf },
            body: new FormData(form),
            credentials: 'same-origin'
        }).then(function (res) {
            return res.json().catch(function () { return {}; }).then(function (data) {
                if (!res.ok) throw new Error(data.error || 'Something went wrong. Please try again.');
                return data;
            });
        });
    }

    function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

    function updateStats(s) {
        if (!s) return;
        Object.keys(s).forEach(function (key) {
            $$('[data-stat="' + key + '"]').forEach(function (el) { el.textContent = s[key]; });
        });
        var fill = $('[data-progress]');
        if (fill) {
            fill.style.width = s.percent + '%';
            fill.parentNode.setAttribute('aria-valuenow', s.percent);
        }
        var overdueWrap = $('[data-overdue-wrap]');
        if (overdueWrap) overdueWrap.classList.toggle('has-alert', s.overdue > 0);

        var counts = { all: s.total, today: s.today + s.overdue, upcoming: s.upcoming, overdue: s.overdue, completed: s.completed };
        $$('[data-count]').forEach(function (el) {
            var n = counts[el.dataset.count];
            el.textContent = n;
            if (el.dataset.count === 'overdue') el.parentNode.classList.toggle('has-alert', n > 0);
        });

        var summary = $('[data-summary]');
        if (summary) {
            var text;
            if (s.overdue && s.today) text = s.overdue + ' overdue, ' + s.today + ' due today.';
            else if (s.overdue) text = s.overdue + (s.overdue === 1 ? ' task needs' : ' tasks need') + ' catching up.';
            else if (s.today) text = plural(s.today, 'thing', 'things') + ' for today.';
            else if (s.active) text = 'Nothing due today.';
            else text = 'A clear list.';
            summary.textContent = text;
        }
        document.title = (s.active ? '(' + s.active + ') ' : '') + 'Tasks · Taskly';
    }

    function removeItem(li) {
        li.classList.add('is-leaving');
        setTimeout(function () {
            li.remove();
            if (!$('.task', list)) {
                list.hidden = true;
                var empty = $('[data-empty]');
                if (empty) empty.hidden = false;
            }
        }, 380);
    }

    list.addEventListener('submit', function (e) {
        var form = e.target;
        var li = form.closest('.task');
        if (!li) return;

        if (form.hasAttribute('data-toggle')) {
            e.preventDefault();
            var btn = $('.check', form);
            var wasDone = li.classList.contains('is-done');
            li.classList.toggle('is-done', !wasDone);          // optimistic
            btn.setAttribute('aria-pressed', String(!wasDone));
            request(form).then(function (data) {
                var done = data.task.completed;
                li.classList.toggle('is-done', done);
                li.classList.toggle('is-overdue', false);
                btn.setAttribute('aria-pressed', String(done));
                btn.setAttribute('aria-label', (done ? 'Mark as not done: ' : 'Mark as done: ') + data.task.content);
                updateStats(data.stats);
                if (view !== 'all') removeItem(li);
            }).catch(function (err) {
                li.classList.toggle('is-done', wasDone);
                btn.setAttribute('aria-pressed', String(wasDone));
                toast(err.message, 'error');
            });
        }

        if (form.hasAttribute('data-delete')) {
            e.preventDefault();
            var title = ($('.task-title', li) || {}).textContent || 'this task';
            if (!window.confirm('Delete “' + title.trim() + '”?')) return;
            request(form).then(function (data) {
                updateStats(data.stats);
                removeItem(li);
                toast('Task deleted.');
            }).catch(function (err) { toast(err.message, 'error'); });
        }
    });
})();
