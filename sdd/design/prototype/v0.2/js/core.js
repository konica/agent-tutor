/* Smart Tutor — core: helpers, icons, store, shell, router, dialogs, toasts. */
(function () {
  const ST = window.ST;

  /* ---------- helpers ---------- */
  ST.esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  ST.num = (n) => Number(n).toLocaleString('en-US');
  ST.clone = (o) => JSON.parse(JSON.stringify(o));
  ST.uid = (() => { let i = 0; return (p = 'id') => p + '-' + (++i); })();

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  ST.fmtDate = (iso, withTime = true) => {
    const [d, t] = iso.split('T');
    const [y, m, day] = d.split('-').map(Number);
    const today = new Date(ST.TODAY + 'T00:00');
    const that = new Date(d + 'T00:00');
    const diff = Math.round((today - that) / 86400000);
    const time = withTime && t ? ', ' + t : '';
    if (diff === 0) return 'Today' + time;
    if (diff === 1) return 'Yesterday' + time;
    return day + ' ' + MONTHS[m - 1] + (y !== 2026 ? ' ' + y : '');
  };

  /* ---------- icons (one outline family, 1.5px stroke) ---------- */
  const ICONS = {
    message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    note: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>',
    book: '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>',
    usage: '<path d="M3 3v18h18"/><path d="M8 16v-4M13 16V8M18 16v-7"/>',
    settings: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    quiz: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    report: '<path d="M21 12h-4l-3 9L10 3l-3 9H3"/>',
    archive: '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8M10 12h4"/>',
    restore: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    thumb: '<path d="M7 10v11"/><path d="M15 5.9 14 10h5.8a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 18.4 21H7V10l4-7.5a2.6 2.6 0 0 1 4 3.4z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    send: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    chevronUp: '<path d="m18 15-6-6-6 6"/>',
    chevronRight: '<path d="m9 18 6-6-6-6"/>',
    doc: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    alertCircle: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    checkCircle: '<circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/>',
    arrowLeft: '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    arrowRight: '<path d="M5 12h14M12 5l7 7-7 7"/>',
    retry: '<path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>',
    pen: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 6-10 7L2 6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/>',
    compass: '<circle cx="12" cy="12" r="10"/><path d="m16.2 7.8-2.1 6.3-6.3 2.1 2.1-6.3z"/>',
    external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3"/>',
    eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    filter: '<path d="M22 3H2l8 9.5V19l4 2v-8.5z"/>',
    lightbulb: '<path d="M9 18h6M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2V17h6v-.3c0-.8.4-1.5 1-2A7 7 0 0 0 12 2z"/>'
  };
  ST.ICONS = ICONS;
  ST.ic = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICONS[name] || ''}</svg>`;
  ST.subjectIcon = (subject, cls = 'sm') => ST.ic(subject === 'IELTS' ? 'pen' : 'cpu', cls);
  ST.subjectChip = (subject, extra = '') => `<span class="chip ${extra}">${ST.subjectIcon(subject)}${ST.esc(subject)}</span>`;

  /* Logo: open book with a citation tick on the right page. */
  ST.logo = (cls = 'logo', label = '') => `<svg class="${cls}" viewBox="0 0 32 32" ${label ? `role="img" aria-label="${ST.esc(label)}"` : 'aria-hidden="true" focusable="false"'}>
    <rect width="32" height="32" rx="8" fill="var(--accent)"/>
    <path d="M6.5 10.2c3-.9 6.2-.5 9.5 1.3v11.3c-3.3-1.8-6.5-2.2-9.5-1.3z" fill="none" stroke="var(--on-accent)" stroke-width="1.6" stroke-linejoin="round"/>
    <path d="M25.5 10.2c-3-.9-6.2-.5-9.5 1.3v11.3c3.3-1.8 6.5-2.2 9.5-1.3z" fill="none" stroke="var(--on-accent)" stroke-width="1.6" stroke-linejoin="round"/>
    <path d="m18.6 16.4 1.7 1.7 3-3.4" fill="none" stroke="var(--on-accent)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;

  /* ---------- lightweight markdown ---------- */
  const inline = (s) => ST.esc(s)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>');
  ST.inline = inline;
  ST.mdParas = (text) => text.split(/\n\n+/).map((p) => `<p>${inline(p)}</p>`).join('');
  ST.md = (src) => {
    const lines = src.split('\n');
    let html = '', list = null;
    const close = () => { if (list) { html += `</${list}>`; list = null; } };
    for (const raw of lines) {
      const l = raw.trimEnd();
      let m;
      if (!l.trim()) { close(); continue; }
      if ((m = l.match(/^(#{1,3})\s+(.*)$/))) { close(); const n = m[1].length; html += `<h${n}>${inline(m[2])}</h${n}>`; continue; }
      if ((m = l.match(/^>\s?(.*)$/))) { close(); html += `<blockquote>${inline(m[1])}</blockquote>`; continue; }
      if ((m = l.match(/^[-*]\s+(.*)$/))) { if (list !== 'ul') { close(); html += '<ul>'; list = 'ul'; } html += `<li>${inline(m[1])}</li>`; continue; }
      if ((m = l.match(/^\d+\.\s+(.*)$/))) { if (list !== 'ol') { close(); html += '<ol>'; list = 'ol'; } html += `<li>${inline(m[1])}</li>`; continue; }
      close(); html += `<p>${inline(l)}</p>`;
    }
    close();
    return html;
  };

  /* ---------- store ---------- */
  const ls = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };
  ST.ls = ls;
  ST.S = {
    theme: ls.get('st_theme', 'light'),
    citations: ls.get('st_citations', 'on') !== 'off',
    enrolled: ['IELTS', 'AI Agents'],
    convs: [], notes: [], thread: null, userMenu: false, r2: false
  };
  ST.resetData = () => {
    const S = ST.S;
    S.enrolled = ['IELTS', 'AI Agents'];
    S.convs = ST.clone(ST.CONVERSATIONS);
    S.notes = ST.clone(ST.NOTES);
    S.userMenu = false;
    S.r2 = false;
    S.citations = ls.get('st_citations', 'on') !== 'off';
  };
  ST.resetData();
  ST.conv = (id) => ST.S.convs.find((c) => c.id === id);
  ST.note = (id) => ST.S.notes.find((n) => n.id === id);

  ST.setTheme = (t) => {
    ST.S.theme = t;
    document.documentElement.setAttribute('data-theme', t);
    ls.set('st_theme', t);
    const b = document.getElementById('rb-theme');
    if (b) b.innerHTML = t === 'dark' ? `${ST.ic('sun', 'sm')}Light` : `${ST.ic('moon', 'sm')}Dark`;
  };

  /* ---------- announcer & toasts ---------- */
  ST.announce = (msg) => {
    const a = document.getElementById('announcer');
    a.textContent = '';
    setTimeout(() => { a.textContent = msg; }, 60);
  };
  ST.toast = (msg, opts = {}) => {
    const box = document.getElementById('toasts');
    const id = ST.uid('toast');
    const el = document.createElement('div');
    el.className = 'toast'; el.id = id;
    el.innerHTML = `<span>${ST.esc(msg)}</span>${opts.undo ? `<button class="btn btn-sm" type="button">Undo</button>` : ''}`;
    if (opts.undo) el.querySelector('button').addEventListener('click', () => { opts.undo(); el.remove(); });
    box.appendChild(el);
    setTimeout(() => el.remove(), 6000);
  };

  /* ---------- dialogs ---------- */
  let lastFocus = null;
  ST.openDialog = ({ title, body, actions = [], wide = false, onClose }) => {
    lastFocus = document.activeElement;
    const root = document.getElementById('overlay-root');
    const tid = ST.uid('dlg-title');
    root.innerHTML = `<div class="dialog-scrim" data-scrim>
      <div class="dialog ${wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-labelledby="${tid}">
        <header><h2 id="${tid}">${title}</h2>
          <button class="icon-btn sm" type="button" data-dlg-close aria-label="Close dialog">${ST.ic('x')}</button></header>
        <div class="d-body">${body}</div>
        <footer>${actions.map((a, i) => `<button type="button" class="btn ${a.cls || 'btn-secondary'}" data-dlg-act="${i}" ${a.autofocus ? 'data-autofocus' : ''}>${a.label}</button>`).join('')}</footer>
      </div></div>`;
    const dlg = root.querySelector('.dialog');
    const close = () => ST.closeDialog(onClose);
    root.querySelector('[data-dlg-close]').addEventListener('click', close);
    root.querySelector('[data-scrim]').addEventListener('mousedown', (e) => { if (e.target.hasAttribute('data-scrim')) close(); });
    actions.forEach((a, i) => root.querySelector(`[data-dlg-act="${i}"]`).addEventListener('click', () => { if (a.onClick) a.onClick(dlg); if (!a.keepOpen) ST.closeDialog(); }));
    dlg.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); close(); }
      if (e.key === 'Tab') {
        const f = [...dlg.querySelectorAll('button, [href], input, select, textarea')].filter((x) => !x.disabled);
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
    (dlg.querySelector('[data-autofocus]') || dlg.querySelector('footer .btn') || dlg).focus();
    return dlg;
  };
  ST.closeDialog = (cb) => {
    document.getElementById('overlay-root').innerHTML = '';
    if (cb) cb();
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
    lastFocus = null;
  };

  /* ---------- app shell ---------- */
  ST.NAV = [
    { id: 'chat', label: 'Chat', icon: 'message', href: '#/chat-empty', hint: 'New conversation' },
    { id: 'conversations', label: 'Conversations', icon: 'list', href: '#/conversations-active' },
    { id: 'notes', label: 'Notes', icon: 'note', href: '#/notes-active' },
    { id: 'subjects', label: 'Subjects', icon: 'book', href: '#/subjects-manage' },
    { id: 'usage', label: 'Usage', icon: 'usage', href: '#/usage-overview' },
    { id: 'settings', label: 'Settings', icon: 'settings', href: '#/settings-default' }
  ];
  ST.NAV_R2 = [
    { id: 'quizzes', label: 'Quizzes', icon: 'quiz', href: '#/r2-quizzes-list' },
    { id: 'reports', label: 'Reports', icon: 'report', href: '#/r2-reports-list' }
  ];

  ST.shell = ({ nav = '', content = '', currentConv = null }) => {
    const S = ST.S;
    const link = (n) => `<li><a class="nav-link" href="${n.href}" ${nav === n.id ? 'aria-current="page"' : ''}>${ST.ic(n.icon)}<span>${n.label}</span>${n.id === 'chat' ? `<span class="nav-tag" aria-hidden="true">New</span>` : ''}${n.id === 'chat' ? '<span class="vh">: start a new conversation</span>' : ''}</a></li>`;
    const r2 = (n) => S.r2
      ? `<li><a class="nav-link" href="${n.href}" ${nav === n.id ? 'aria-current="page"' : ''}>${ST.ic(n.icon)}<span>${n.label}</span><span class="nav-tag">R2</span></a></li>`
      : `<li><span class="nav-link" aria-disabled="true">${ST.ic(n.icon)}<span>${n.label}</span><span class="nav-tag">Soon</span></span></li>`;
    const recent = S.convs.filter((c) => !c.archived).sort((a, b) => b.last.localeCompare(a.last)).slice(0, 4);
    return `<div class="app">
      <nav class="sidenav" aria-label="Main">
        <a class="brand" href="#/chat-empty" aria-label="Smart Tutor home">${ST.logo()}<span class="word">Smart Tutor</span></a>
        <ul class="nav-list">${ST.NAV.map(link).join('')}</ul>
        <p class="nav-section" id="recent-h">Recent</p>
        <ul class="nav-list recent" aria-labelledby="recent-h">${recent.map((c) => `<li><a class="od-truncate" href="#/open/${c.id}" ${currentConv === c.id ? 'aria-current="page"' : ''}>${ST.esc(c.title)}</a></li>`).join('')}</ul>
        <p class="nav-section" id="r2-h">Release 2</p>
        <ul class="nav-list" aria-labelledby="r2-h">${ST.NAV_R2.map(r2).join('')}</ul>
        <div class="nav-foot">
          ${S.userMenu ? `<div class="user-menu" id="user-menu">
            <div class="um-head od-stack" style="--od-gap:0"><strong>${ST.esc(ST.USER.name)}</strong><span class="small muted od-truncate">${ST.esc(ST.USER.email)}</span></div>
            <button class="menu-item" type="button" data-action="theme-toggle">${ST.ic(S.theme === 'dark' ? 'sun' : 'moon')}${S.theme === 'dark' ? 'Light theme' : 'Dark theme'}</button>
            <a class="menu-item" href="#/settings-default" style="text-decoration:none">${ST.ic('settings')}Settings</a>
            <button class="menu-item" type="button" data-action="sign-out">${ST.ic('logout')}Sign out</button>
          </div>` : ''}
          <button class="user-btn" type="button" data-action="user-menu" data-fk="user-btn" aria-expanded="${S.userMenu}" aria-controls="user-menu">
            <span class="avatar" aria-hidden="true">${ST.USER.initials}</span>
            <span class="od-fill od-stack" style="--od-gap:0"><span class="small" style="font-weight:600">${ST.esc(ST.USER.name)}</span><span class="xsmall muted">Learner</span></span>
            ${ST.ic(S.userMenu ? 'chevronDown' : 'chevronUp', 'sm')}
          </button>
        </div>
      </nav>
      <main class="main" id="main-content" tabindex="-1">${content}</main>
    </div>`;
  };

  /* ---------- mount with focus preservation ---------- */
  ST.mount = (html, { navigated = false } = {}) => {
    const root = document.getElementById('root');
    const active = document.activeElement;
    const fk = active && active.dataset ? active.dataset.fk : null;
    const scrollers = {};
    root.querySelectorAll('[data-keep-scroll]').forEach((el) => { scrollers[el.dataset.keepScroll] = el.scrollTop; });
    root.innerHTML = html;
    if (!navigated) {
      Object.keys(scrollers).forEach((k) => { const el = root.querySelector(`[data-keep-scroll="${k}"]`); if (el) el.scrollTop = scrollers[k]; });
      if (fk) { const el = root.querySelector(`[data-fk="${fk}"]`); if (el) { el.focus(); if (el.setSelectionRange && el.value != null && el.type !== 'date') { try { el.setSelectionRange(el.value.length, el.value.length); } catch (e) {} } } }
    }
  };

  /* ---------- delegated actions ---------- */
  ST.actions = {};
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    if (el && ST.actions[el.dataset.action] && !el.disabled && el.getAttribute('aria-disabled') !== 'true') {
      ST.actions[el.dataset.action](el, e);
    } else if (ST.S.userMenu && !e.target.closest('.nav-foot')) {
      ST.S.userMenu = false; ST.render();
    }
  });
  document.addEventListener('change', (e) => {
    const el = e.target.closest('[data-change]');
    if (el && ST.actions[el.dataset.change]) ST.actions[el.dataset.change](el, e);
  });
  document.addEventListener('input', (e) => {
    const el = e.target.closest('[data-input]');
    if (el && ST.actions[el.dataset.input]) ST.actions[el.dataset.input](el, e);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && ST.S.userMenu) { ST.S.userMenu = false; ST.render(); const b = document.querySelector('[data-fk="user-btn"]'); if (b) b.focus(); }
  });

  Object.assign(ST.actions, {
    'user-menu': () => { ST.S.userMenu = !ST.S.userMenu; ST.render(); if (ST.S.userMenu) { const m = document.querySelector('#user-menu .menu-item'); if (m) m.focus(); } },
    'theme-toggle': () => { ST.setTheme(ST.S.theme === 'dark' ? 'light' : 'dark'); ST.S.userMenu = false; ST.render(); },
    'sign-out': () => { ST.S.userMenu = false; location.hash = '#/auth-sign-in'; },
    'rb-theme': () => { ST.setTheme(ST.S.theme === 'dark' ? 'light' : 'dark'); ST.render(); },
    'go': (el) => { location.hash = el.dataset.href; }
  });

  /* ---------- router ---------- */
  ST.timers = [];
  ST.clearTimers = () => { ST.timers.forEach((t) => { clearTimeout(t); clearInterval(t); }); ST.timers = []; };
  ST.later = (fn, ms) => { const t = setTimeout(fn, ms); ST.timers.push(t); return t; };
  ST.every = (fn, ms) => { const t = setInterval(fn, ms); ST.timers.push(t); return t; };

  ST.current = null;
  ST.render = () => { if (ST.current) { ST.mount(ST.current.view()); if (ST.current.afterRender) ST.current.afterRender(); } };

  ST.resolve = (hash) => {
    const id = hash.replace(/^#\/?/, '') || 'index';
    const fixed = ST.STATES.find((s) => s.id === id);
    if (fixed) return fixed;
    let m;
    if ((m = id.match(/^open\/(c\d+)$/))) return ST.dynamicConversation(m[1]);
    if ((m = id.match(/^note\/(n\d+)$/))) return ST.dynamicNote(m[1]);
    return ST.STATES[0];
  };

  ST.route = () => {
    ST.clearTimers();
    if (ST.stopStream) ST.stopStream(true);
    document.getElementById('overlay-root').innerHTML = '';
    closeDrawer(false);
    const st = ST.resolve(location.hash);
    ST.current = st;
    ST.S.userMenu = false;
    ST.S.r2 = false;
    ST.emptyDemo = false;
    if (st.setup) st.setup();
    ST.mount(st.view(), { navigated: true });
    if (st.afterRender) st.afterRender();
    updateReviewBar(st);
    const main = document.getElementById('main-content');
    const auto = document.querySelector('#root [data-autofocus]');
    if (st.afterEnter) st.afterEnter();
    if (document.getElementById('overlay-root').children.length) { /* a dialog owns focus */ }
    else if (auto) auto.focus({ preventScroll: true });
    else if (main) main.focus({ preventScroll: true });
    else { const h = document.querySelector('#root h1'); if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); } }
    document.title = (st.fixed !== false ? st.id + '@' + ST.BRIEF + ' · ' : '') + 'Smart Tutor';
  };

  /* ---------- review chrome ---------- */
  function updateReviewBar(st) {
    const el = document.getElementById('rb-state');
    const label = st.fixed === false ? st.label : `${st.id}@${ST.BRIEF}`;
    el.innerHTML = `<code>${ST.esc(label)}</code><span class="rb-desc">${ST.esc(st.desc || '')}</span>`;
  }
  const idx = () => ST.STATES.findIndex((s) => ST.current && s.id === ST.current.id);
  ST.actions['rb-prev'] = () => { const i = idx(); const n = i <= 0 ? ST.STATES.length - 1 : i - 1; location.hash = '#/' + ST.STATES[n].id; };
  ST.actions['rb-next'] = () => { const i = idx(); const n = i < 0 || i >= ST.STATES.length - 1 ? 0 : i + 1; location.hash = '#/' + ST.STATES[n].id; };

  let drawerOpener = null;
  function closeDrawer(restore = true) {
    const d = document.getElementById('index-drawer-wrap');
    if (d) { d.remove(); if (restore && drawerOpener) drawerOpener.focus(); }
  }
  ST.actions['rb-index'] = (el) => {
    drawerOpener = el;
    const groups = [];
    ST.STATES.forEach((s) => { let g = groups.find((x) => x.name === s.group); if (!g) { g = { name: s.group, items: [] }; groups.push(g); } g.items.push(s); });
    const wrap = document.createElement('div');
    wrap.id = 'index-drawer-wrap';
    wrap.innerHTML = `<div class="drawer-scrim" data-drawer-close></div>
      <aside class="index-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-h">
        <header><h2 id="drawer-h">All states · ${ST.STATES.length}</h2><button class="rb-btn" type="button" data-drawer-close aria-label="Close index">${ST.ic('x', 'sm')}</button></header>
        <nav aria-label="States">${groups.map((g) => `<h3>${ST.esc(g.name)}</h3>${g.items.map((s) => `<a href="#/${s.id}" ${ST.current && ST.current.id === s.id ? 'aria-current="page"' : ''}>${s.id}@${ST.BRIEF}</a>`).join('')}`).join('')}</nav>
      </aside>`;
    document.body.appendChild(wrap);
    wrap.querySelectorAll('[data-drawer-close]').forEach((b) => b.addEventListener('click', () => closeDrawer()));
    const aside = wrap.querySelector('.index-drawer');
    aside.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeDrawer();
      if (e.key === 'Tab') {
        const f = [...aside.querySelectorAll('button, a')];
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    });
    const cur = aside.querySelector('[aria-current="page"]');
    (cur || aside.querySelector('a')).focus();
    if (cur) cur.scrollIntoView({ block: 'center' });
  };

  ST.boot = () => {
    ST.setTheme(ST.S.theme);
    window.addEventListener('hashchange', ST.route);
    ST.route();
  };
})();
