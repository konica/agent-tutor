/* Smart Tutor v0.9 — core: helpers, icons, store, shell, overlays, upload tray, router, review chrome. */
(function () {
  const ST = window.ST;

  /* ---------- helpers ---------- */
  ST.esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  ST.num = (n) => Number(n).toLocaleString('en-US');
  ST.clone = (o) => JSON.parse(JSON.stringify(o));
  ST.uid = (() => { let i = 0; return (p = 'id') => p + '-' + (++i); })();
  ST.plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + 's')}`;
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  ST.fmtDate = (iso, withTime = true) => {
    const [d, t] = iso.split('T');
    const [y, m, day] = d.split('-').map(Number);
    const diff = Math.round((new Date(ST.TODAY + 'T00:00') - new Date(d + 'T00:00')) / 86400000);
    const time = withTime && t ? ', ' + t : '';
    if (diff === 0) return 'Today' + time;
    if (diff === 1) return 'Yesterday' + time;
    return day + ' ' + MONTHS[m - 1] + (y !== 2026 ? ' ' + y : '');
  };
  ST.fmtLong = (iso) => { const [y, m, d] = iso.slice(0, 10).split('-').map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };

  /* ---------- icons (one outline family, 1.5px stroke) ---------- */
  const ICONS = {
    message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    maximize: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    trash: '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    note: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>',
    library: '<path d="M4 19.5V4.5A1.5 1.5 0 0 1 5.5 3H8v18H5.5A1.5 1.5 0 0 1 4 19.5z"/><path d="M8 3h4v18H8M12 4.5l4-1 4 16-4 1z"/>',
    tag: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><path d="M7.5 7.5h.01"/>',
    usage: '<path d="M3 3v18h18"/><path d="M8 16v-4M13 16V8M18 16v-7"/>',
    settings: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    quiz: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    report: '<path d="M21 12h-4l-3 9L10 3l-3 9H3"/>',
    map: '<path d="M1 6v16l7-4 8 4 7-4V2l-7 4-8-4z"/><path d="M8 2v16M16 6v16"/>',
    archive: '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8M10 12h4"/>',
    restore: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    thumb: '<path d="M7 10v11"/><path d="M15 5.9 14 10h5.8a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 18.4 21H7V10l4-7.5a2.6 2.6 0 0 1 4 3.4z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    send: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5M12 3v12"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    chevronUp: '<path d="m18 15-6-6-6 6"/>',
    chevronRight: '<path d="m9 18 6-6-6-6"/>',
    chevronLeft: '<path d="m15 18-6-6 6-6"/>',
    doc: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    book: '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>',
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
    more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
    mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 6-10 7L2 6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/>',
    compass: '<circle cx="12" cy="12" r="10"/><path d="m16.2 7.8-2.1 6.3-6.3 2.1 2.1-6.3z"/>',
    filter: '<path d="M22 3H2l8 9.5V19l4 2v-8.5z"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    layers: '<path d="M12 2 2 7l10 5 10-5z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
    plusCircle: '<circle cx="12" cy="12" r="10"/><path d="M12 8v8M8 12h8"/>',
    quote: '<path d="M3 21c3 0 7-1 7-8V5H3v8h4M14 21c3 0 7-1 7-8V5h-7v8h4"/>'
  };
  ST.ICONS = ICONS;
  ST.ic = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICONS[name] || ''}</svg>`;

  /* Logo: open book with a citation tick on the right page. */
  ST.logo = (cls = 'logo', label = '') => `<svg class="${cls}" viewBox="0 0 32 32" ${label ? `role="img" aria-label="${ST.esc(label)}"` : 'aria-hidden="true" focusable="false"'}>
    <rect width="32" height="32" rx="8" fill="var(--accent)"/>
    <path d="M6.5 10.2c3-.9 6.2-.5 9.5 1.3v11.3c-3.3-1.8-6.5-2.2-9.5-1.3z" fill="none" stroke="var(--on-accent)" stroke-width="1.6" stroke-linejoin="round"/>
    <path d="M25.5 10.2c-3-.9-6.2-.5-9.5 1.3v11.3c3.3-1.8 6.5-2.2 9.5-1.3z" fill="none" stroke="var(--on-accent)" stroke-width="1.6" stroke-linejoin="round"/>
    <path d="m18.6 16.4 1.7 1.7 3-3.4" fill="none" stroke="var(--on-accent)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;

  /* ---------- markdown ---------- */
  const inline = (s) => ST.esc(s).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\*(.+?)\*/g, '<em>$1</em>');
  ST.inline = inline;
  ST.mdParas = (text) => text.split(/\n\n+/).map((p) => `<p>${inline(p)}</p>`).join('');
  ST.md = (src) => {
    let html = '', list = null;
    const close = () => { if (list) { html += `</${list}>`; list = null; } };
    for (const raw of src.split('\n')) {
      const l = raw.trimEnd(); let m;
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
  ST.S = { theme: ls.get('st_theme', 'light'), citations: ls.get('st3_citations', 'on') !== 'off', userMenu: false, rowMenu: null, tray: [], trayCollapsed: false, uploadLimit: false };
  ST.resetData = () => {
    const S = ST.S;
    S.docs = ST.clone(ST.DOCS);
    S.catalog = ST.clone(ST.CATALOG);
    S.convs = ST.clone(ST.CONVERSATIONS);
    S.deletedNotice = null;
    S.notes = ST.clone(ST.NOTES);
    S.tray = []; S.trayCollapsed = false; S.uploadLimit = false;
    S.rowMenu = null; S.userMenu = false;
    S.convs.forEach((c) => ST.syncConvSubjects(c));
  };
  ST.doc = (id) => ST.S.docs.find((d) => d.id === id);
  ST.conv = (id) => ST.S.convs.find((c) => c.id === id);
  ST.note = (id) => ST.S.notes.find((n) => n.id === id);
  ST.subj = (id) => ST.S.catalog.find((s) => s.id === id);
  ST.sname = (id) => { const s = ST.subj(id); return s ? (s.mine || s.shared) : id; };
  ST.hueKey = (id) => (['llm', 'agents', 'rag', 'rl', 'tool'].includes(id) ? id : 'other');
  ST.schip = (id, cls = '') => `<span class="schip ${cls}" data-s="${ST.hueKey(id)}"><span class="dot" aria-hidden="true"></span>${ST.esc(ST.sname(id))}</span>`;
  ST.chips = (ids, cls = '') => `<span class="chips">${ids.map((i) => ST.schip(i, cls)).join('')}</span>`;
  /* "My subjects": subjects of ready, non-archived, not deleted documents */
  ST.mySubjects = () => { const set = []; ST.S.docs.forEach((d) => { if (d.state === 'ready' && !d.archived && !d.deleted) d.subjects.forEach((s) => { if (!set.includes(s)) set.push(s); }); }); return set; };
  ST.needsAction = () => ST.S.docs.filter((d) => !d.archived && !d.deleted && (d.state === 'choose' || d.state === 'failed')).length;
  ST.stillProcessing = () => ST.S.docs.filter((d) => !d.archived && !d.deleted && ['uploading', 'processing', 'choose'].includes(d.state)).length;
  /* K1: a conversation's subjects (list chips, filters, Subjects counts) come from the documents it used. */
  ST.subjectsOfDocs = (ids) => { const set = []; ids.forEach((id) => { const d = ST.doc(id); if (d) d.subjects.forEach((s) => { if (!set.includes(s)) set.push(s); }); }); return set; };
  ST.convDocs = (c) => { const ids = []; (c.answers || []).forEach((k) => (ST.ANSWERS[k] ? ST.ANSWERS[k].cites : []).forEach((x) => { if (!ids.includes(x.doc)) ids.push(x.doc); })); return ids; };
  ST.syncConvSubjects = (c) => { c.subjects = ST.subjectsOfDocs(ST.convDocs(c)); };
  ST.docTitle = (id) => { const d = ST.doc(id); return d ? d.title : ''; };
  ST.resetData();

  ST.setTheme = (t) => {
    ST.S.theme = t;
    document.documentElement.setAttribute('data-theme', t);
    ls.set('st_theme', t);
    const b = document.getElementById('rb-theme');
    if (b) b.innerHTML = t === 'dark' ? `${ST.ic('sun', 'sm')}Light` : `${ST.ic('moon', 'sm')}Dark`;
  };

  /* ---------- announcer & toasts ---------- */
  ST.announce = (msg) => { const a = document.getElementById('announcer'); a.textContent = ''; setTimeout(() => { a.textContent = msg; }, 60); };
  ST.toast = (msg, opts = {}) => {
    const box = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = `<span>${ST.esc(msg)}</span>${opts.undo ? '<button class="btn btn-sm" type="button">Undo</button>' : ''}`;
    if (opts.undo) el.querySelector('button').addEventListener('click', () => { opts.undo(); el.remove(); });
    box.appendChild(el);
    setTimeout(() => el.remove(), 6000);
  };

  /* ---------- overlays: dialog, panel, picker share one root ---------- */
  let lastFocus = null;
  ST.ov = null; // { render: () => html, onClose }
  const overlayRoot = () => document.getElementById('overlay-root');
  ST.showOverlay = (render, { onClose, keepFocus } = {}) => {
    if (!keepFocus) lastFocus = document.activeElement;
    ST.ov = { render, onClose };
    overlayRoot().innerHTML = render();
    const first = overlayRoot().querySelector('[data-autofocus]') || overlayRoot().querySelector('[role="dialog"] button, [role="dialog"] input, [role="dialog"] a');
    if (first) first.focus();
  };
  ST.redrawOverlay = () => {
    if (!ST.ov) return;
    const root = overlayRoot();
    const a = document.activeElement; const fk = a && root.contains(a) && a.dataset ? a.dataset.fk : null;
    const sc = root.querySelector('[data-keep-scroll]'); const top = sc ? sc.scrollTop : 0;
    root.innerHTML = ST.ov.render();
    const sc2 = root.querySelector('[data-keep-scroll]'); if (sc2) sc2.scrollTop = top;
    if (fk) { const el = root.querySelector(`[data-fk="${fk}"]`); if (el) { el.focus(); if (el.setSelectionRange && typeof el.value === 'string' && el.type === 'text') { try { el.setSelectionRange(el.value.length, el.value.length); } catch (e) {} } } }
  };
  ST.hideOverlay = (restore = true) => {
    const cb = ST.ov && ST.ov.onClose;
    ST.ov = null;
    overlayRoot().innerHTML = '';
    if (cb) cb();
    if (restore && lastFocus && document.contains(lastFocus)) lastFocus.focus();
    lastFocus = null;
  };
  document.addEventListener('keydown', (e) => {
    const root = overlayRoot();
    if (!root || !root.children.length) return;
    const box = root.querySelector('[role="dialog"]');
    if (!box) return;
    if (e.key === 'Escape') {
      if (root.querySelector('.ta-list') && e.target.closest('.ta-wrap')) return; // type-ahead closes itself
      e.preventDefault(); if (ST.ov) ST.hideOverlay(); else ST.closeDialog();
    }
    if (e.key === 'Tab') {
      const f = [...box.querySelectorAll('button, [href], input, select, textarea')].filter((x) => !x.disabled && x.offsetParent !== null);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });

  /* Simple confirm/info dialog */
  ST.openDialog = ({ title, body, actions = [], wide = false, onClose }) => {
    const tid = ST.uid('dlg');
    const render = () => `<div class="dialog-scrim" data-scrim>
      <div class="dialog ${wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-labelledby="${tid}">
        <header><h2 id="${tid}">${title}</h2><button class="icon-btn sm" type="button" data-dlg-close aria-label="Close dialog">${ST.ic('x')}</button></header>
        <div class="d-body">${body}</div>
        <footer>${actions.map((a, i) => `<button type="button" class="btn ${a.cls || 'btn-secondary'}" data-dlg-act="${i}" ${a.autofocus ? 'data-autofocus' : ''}>${a.label}</button>`).join('')}</footer>
      </div></div>`;
    ST.dlgActions = actions;
    ST.showOverlay(render, { onClose });
  };
  ST.closeDialog = () => ST.hideOverlay();
  /* Delegated so dialogs survive overlay redraws. */
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-dlg-close]')) { ST.hideOverlay(); return; }
    const b = e.target.closest('[data-dlg-act]');
    if (!b || !ST.dlgActions) return;
    const a = ST.dlgActions[+b.dataset.dlgAct];
    const render = ST.ov && ST.ov.render;
    const dlg = overlayRoot().querySelector('.dialog');
    if (a && a.onClick) a.onClick(dlg);
    if (a && !a.keepOpen && ST.ov && ST.ov.render === render) ST.hideOverlay();
  });
  document.addEventListener('mousedown', (e) => { if (e.target.hasAttribute && e.target.hasAttribute('data-scrim')) ST.hideOverlay(); });

  /* ---------- app shell ---------- */
  ST.NAV = [
    { id: 'library', label: 'Library', icon: 'library', href: '#/library-default' },
    /* reserved: Research map (R2) */
    { id: 'chat', label: 'Chat', icon: 'message', href: '#/chat-new' },
    { id: 'conversations', label: 'Conversations', icon: 'list', href: '#/conversations-active' },
    { id: 'notes', label: 'Notes', icon: 'note', href: '#/notes-active' },
    /* reserved: Quizzes, Reports (R3) */
    { id: 'subjects', label: 'Subjects', icon: 'tag', href: '#/subjects-list' },
    { id: 'usage', label: 'Usage', icon: 'usage', href: '#/usage-overview' }
    /* Settings removed in v0.5 (PRD Q45) */
  ];
  ST.NAV_LATER = { map: { label: 'Research map', icon: 'map', after: 'library', href: '#/r2-map' }, quizzes: { label: 'Quizzes', icon: 'quiz', after: 'notes', href: '#/r3-quizzes-list' }, reports: { label: 'Reports', icon: 'report', after: 'quizzes', href: '#/r3-reports' } };

  /* M3: 208px nav, 32px items in hairline-separated groups, collapsible to a 56px icon rail (names in tooltips). */
  ST.NAV_GROUPS = [['library', 'chat'], ['conversations', 'notes'], ['subjects', 'usage']];
  ST.shell = ({ nav = '', content = '', currentConv = null }) => {
    const S = ST.S;
    const n = ST.needsAction();
    const later = S.release || 0; // 2 shows the map, 3 shows the learning loop (wireframes only)
    const rail = !!S.navCollapsed;
    const byId = (id) => ST.NAV.find((x) => x.id === id) || ST.NAV_LATER[id];
    const item = (id) => {
      const it = byId(id);
      const label = it.label + (id === 'chat' ? ', start a new conversation' : '');
      return `<li><a class="nav-link ${S.tipDemo === id ? 'tip-demo' : ''}" href="${it.href}" ${nav === id ? 'aria-current="page"' : ''} ${rail ? `data-tip="${it.label}" aria-label="${label}${id === 'library' && n ? `, ${n} need your action` : ''}"` : ''} data-od-id="nav-${id}">${ST.ic(it.icon)}<span class="nl-text">${it.label}</span>${
        id === 'library' && n ? `<span class="nav-count" ${rail ? 'aria-hidden="true"' : `aria-label="${ST.plural(n, 'document')} need${n === 1 ? 's' : ''} your action"`}>${n}</span>` : ''}${
        id === 'chat' && !rail ? '<span class="vh">: start a new conversation</span>' : ''}${
        ['map', 'quizzes', 'reports'].includes(id) ? `<span class="nav-tag">R${id === 'map' ? 2 : 3}</span>` : ''}</a>${id === 'conversations' && !rail ? recentList() : ''}</li>`;
    };
    const recentList = () => {
      const recent = S.convs.filter((c) => !c.archived).sort((a, b) => b.last.localeCompare(a.last)).slice(0, 3);
      return recent.length ? `<ul class="nav-sub" aria-label="Recent conversations">${recent.map((c) => `<li><a class="od-truncate" href="#/open/${c.id}" title="${ST.esc(c.title)}" ${currentConv === c.id ? 'aria-current="page"' : ''}>${ST.esc(c.title)}</a></li>`).join('')}</ul>` : '';
    };
    const groups = ST.NAV_GROUPS.map((g) => {
      const ids = [];
      g.forEach((id) => { ids.push(id); if (id === 'library' && later >= 2) ids.push('map'); if (id === 'notes' && later >= 3) ids.push('quizzes', 'reports'); });
      return `<ul class="nav-list">${ids.map(item).join('')}</ul>`;
    }).join('<hr class="nav-hr">');
    return `<div class="app ${rail ? 'nav-collapsed' : ''}">
      <nav class="sidenav" aria-label="Main" data-od-id="side-nav">
        <a class="brand" href="#/library-default" aria-label="Smart Tutor, Library" ${rail ? 'data-tip="Smart Tutor"' : ''}>${ST.logo()}<span class="word">Smart Tutor</span></a>
        ${groups}
        <div class="nav-foot">
          <button class="nav-collapse" type="button" data-action="nav-collapse" aria-expanded="${!rail}" aria-label="${rail ? 'Expand navigation' : 'Collapse navigation'}" data-tip="${rail ? 'Expand navigation' : 'Collapse navigation'}" data-od-id="nav-collapse">${ST.ic(rail ? 'chevronRight' : 'chevronLeft', 'sm')}</button>
          ${S.userMenu ? `<div class="user-menu" id="user-menu">
            <div class="um-head od-stack" style="--od-gap:0"><strong>${ST.esc(ST.USER.name)}</strong><span class="small muted od-truncate">${ST.esc(ST.USER.email)}</span></div>
            <button class="menu-item" type="button" data-action="theme-toggle">${ST.ic(S.theme === 'dark' ? 'sun' : 'moon')}${S.theme === 'dark' ? 'Light theme' : 'Dark theme'}</button>
            <button class="menu-item" type="button" data-action="sign-out">${ST.ic('logout')}Sign out</button>
          </div>` : ''}
          <button class="user-btn" type="button" data-action="user-menu" data-fk="user-btn" aria-expanded="${S.userMenu}" aria-controls="user-menu" ${rail ? `aria-label="${ST.esc(ST.USER.name)}, account menu" data-tip="${ST.esc(ST.USER.name)}"` : ''} data-od-id="user-menu-button">
            <span class="avatar" aria-hidden="true">${ST.USER.initials}</span>
            <span class="ub-name od-truncate">${ST.esc(ST.USER.name)}</span>
            ${ST.ic(S.userMenu ? 'chevronDown' : 'chevronUp', 'sm')}
          </button>
        </div>
      </nav>
      <main class="main" id="main-content" tabindex="-1">${content}</main>
    </div>`;
  };
  ST.actions = ST.actions || {};
  ST.actions['nav-collapse'] = () => { ST.S.navCollapsed = !ST.S.navCollapsed; ST.S.tipDemo = null; ST.ls.set('st9_nav', ST.S.navCollapsed ? 'collapsed' : 'open'); ST.render(); const b = document.querySelector('[data-action="nav-collapse"]'); if (b) b.focus(); };

  /* M4: one 40px page header row: h1, a short count, an info button whose tooltip holds the longer description, the action. */
  ST.pageHead = ({ title, count = '', info = '', action = '', id = '' }) => `<div class="page-head" data-od-id="page-header">
      <h1 ${id ? `id="${id}" tabindex="-1"` : ''}>${title}</h1>${count ? `<span class="ph-count">${count}</span>` : ''}
      ${info ? `<button class="info-btn" type="button" aria-label="About this page: ${ST.esc(info)}" data-tip="${ST.esc(info)}">${ST.ic('info', 'sm')}</button>` : ''}
      <span class="od-fill"></span>${action}</div>`;

  /* ---------- upload tray (global, non-blocking) ---------- */
  ST.renderTray = () => {
    const S = ST.S;
    const root = document.getElementById('tray-root');
    if (!root) return;
    if (!S.tray.length || ST.noTray) { root.innerHTML = ''; return; }
    const busy = S.tray.filter((t) => t.status === 'uploading').length;
    const head = busy ? `Uploading ${ST.plural(busy, 'file')}…` : `Uploads · ${ST.plural(S.tray.length, 'file')}`;
    root.innerHTML = `<section class="tray" aria-labelledby="tray-h">
      <div class="tray-head"><strong id="tray-h">${head}</strong>
        <button class="icon-btn sm" type="button" data-action="tray-toggle" aria-expanded="${!S.trayCollapsed}" aria-label="${S.trayCollapsed ? 'Expand uploads' : 'Collapse uploads'}">${ST.ic(S.trayCollapsed ? 'chevronUp' : 'chevronDown', 'sm')}</button>
        ${busy ? '' : `<button class="icon-btn sm" type="button" data-action="tray-close" aria-label="Close uploads">${ST.ic('x', 'sm')}</button>`}</div>
      ${S.trayCollapsed ? '' : `<ul class="tray-list">${S.tray.map(trayItem).join('')}</ul>`}
    </section>`;
  };
  function trayItem(t) {
    const d = t.docId ? ST.doc(t.docId) : null;
    let cls = '', icon = 'doc', status = '', actions = '', bar = '';
    if (t.status === 'uploading') { status = `Uploading · ${t.size}`; bar = `<div class="bar" role="progressbar" aria-label="Upload progress for ${ST.esc(t.name)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(t.progress)}"><span style="transform:scaleX(${t.progress / 100})"></span></div>`; }
    else if (t.status === 'done') { cls = 'ok'; icon = 'checkCircle'; status = d && d.state === 'ready' ? 'Ready' : d && d.state === 'choose' ? 'Processed · choose subjects' : 'Uploaded · processing'; }
    else if (t.status === 'rejected') { cls = 'bad'; icon = 'alertCircle'; status = `Not uploaded. ${t.reason}`; }
    else if (t.status === 'duplicate') { icon = 'info'; status = 'Already in your library'; actions = `<button class="btn btn-ghost btn-sm" type="button" data-action="open-doc" data-id="${t.docId}">Open document</button>`; }
    else if (t.status === 'duplicate-archived') { icon = 'info'; status = 'Already in your library, archived'; actions = `<button class="btn btn-secondary btn-sm" type="button" data-action="doc-restore" data-id="${t.docId}">${ST.ic('restore', 'sm')}Restore</button>`; }
    return `<li class="tray-item ${cls}"><span class="ti-icon">${ST.ic(icon)}</span><div class="od-stack" style="--od-gap:0">
      <span class="ti-name od-truncate">${ST.esc(t.name)}</span><span class="ti-status">${status}</span>${bar}${actions ? `<div class="ti-actions">${actions}</div>` : ''}</div></li>`;
  }
  ST.actions = ST.actions || {};
  Object.assign(ST.actions, {
    'tray-toggle': () => { ST.S.trayCollapsed = !ST.S.trayCollapsed; ST.renderTray(); const b = document.querySelector('[data-action="tray-toggle"]'); if (b) b.focus(); },
    'tray-close': () => { ST.S.tray = []; ST.renderTray(); const m = document.getElementById('main-content'); if (m) m.focus(); }
  });

  /* ---------- mount with focus preservation ---------- */
  ST.mount = (html, { navigated = false } = {}) => {
    const root = document.getElementById('root');
    const active = document.activeElement;
    const fk = active && root.contains(active) && active.dataset ? active.dataset.fk : null;
    const scrollers = {};
    root.querySelectorAll('[data-keep-scroll]').forEach((el) => { scrollers[el.dataset.keepScroll] = el.scrollTop; });
    root.innerHTML = html;
    if (!navigated) {
      Object.keys(scrollers).forEach((k) => { const el = root.querySelector(`[data-keep-scroll="${k}"]`); if (el) el.scrollTop = scrollers[k]; });
      if (fk) { const el = root.querySelector(`[data-fk="${fk}"]`); if (el) { el.focus({ preventScroll: true }); if (el.setSelectionRange && typeof el.value === 'string' && (el.type === 'text' || el.tagName === 'TEXTAREA')) { try { el.setSelectionRange(el.value.length, el.value.length); } catch (e) {} } } }
    }
  };

  /* ---------- delegated events ---------- */
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    const S = ST.S;
    if (S.rowMenu && !e.target.closest('.row-menu-wrap')) { S.rowMenu = null; if (!el) ST.render(); }
    if (S.chatMenu && !e.target.closest('.th-more')) { S.chatMenu = false; if (!el) ST.render(); }
    if (el && ST.actions[el.dataset.action] && !el.disabled && el.getAttribute('aria-disabled') !== 'true') { ST.actions[el.dataset.action](el, e); return; }
    if (S.userMenu && !e.target.closest('.nav-foot')) { S.userMenu = false; ST.render(); }
  });
  document.addEventListener('toggle', (e) => { const d = e.target; if (d && d.dataset && d.dataset.pop === 'date' && ST.L) ST.L.datePop = d.open; }, true);
  document.addEventListener('change', (e) => { const el = e.target.closest('[data-change]'); if (el && ST.actions[el.dataset.change]) ST.actions[el.dataset.change](el, e); });
  document.addEventListener('input', (e) => { const el = e.target.closest('[data-input]'); if (el && ST.actions[el.dataset.input]) ST.actions[el.dataset.input](el, e); });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (ST.S.userMenu) { ST.S.userMenu = false; ST.render(); const b = document.querySelector('[data-fk="user-btn"]'); if (b) b.focus(); }
    if (ST.S.rowMenu) { const id = ST.S.rowMenu; ST.S.rowMenu = null; ST.render(); const b = document.querySelector(`[data-fk="more-${id}"]`); if (b) b.focus(); }
    if (ST.S.chatMenu) { ST.S.chatMenu = false; ST.render(); const b = document.querySelector('[data-fk="chat-menu"]'); if (b) b.focus(); }
  });
  Object.assign(ST.actions, {
    'user-menu': () => { ST.S.userMenu = !ST.S.userMenu; ST.render(); if (ST.S.userMenu) { const m = document.querySelector('#user-menu .menu-item'); if (m) m.focus(); } },
    'theme-toggle': () => { ST.setTheme(ST.S.theme === 'dark' ? 'light' : 'dark'); ST.S.userMenu = false; ST.render(); },
    'sign-out': () => { ST.S.userMenu = false; location.hash = '#/landing-default'; }, // §6.1: sign-out returns to the landing page
    'rb-theme': () => { ST.setTheme(ST.S.theme === 'dark' ? 'light' : 'dark'); ST.render(); ST.redrawOverlay(); },
    go: (el) => { location.hash = el.dataset.href; }
  });

  /* ---------- timers ---------- */
  ST.timers = [];
  ST.clearTimers = () => { ST.timers.forEach((t) => { clearTimeout(t); clearInterval(t); }); ST.timers = []; };
  ST.later = (fn, ms) => { const t = setTimeout(fn, ms); ST.timers.push(t); return t; };
  ST.every = (fn, ms) => { const t = setInterval(fn, ms); ST.timers.push(t); return t; };

  /* ---------- router ---------- */
  ST.current = null;
  ST.render = () => { if (ST.current) { ST.mount(ST.current.view()); if (ST.current.afterRender) ST.current.afterRender(); } ST.renderTray(); ST.redrawOverlay(); };
  ST.resolve = (hash) => {
    const id = hash.replace(/^#\/?/, '') || 'index';
    const fixed = ST.STATES.find((s) => s.id === id);
    if (fixed) return fixed;
    let m;
    if ((m = id.match(/^open\/(cv\d+)$/))) return ST.dynamicConversation(m[1]);
    if ((m = id.match(/^note\/(n\d+)$/))) return ST.dynamicNote(m[1]);
    return ST.STATES[0];
  };
  ST.goto = (id) => { if (location.hash === '#/' + id) ST.route(); else location.hash = '#/' + id; };
  ST.route = () => {
    ST.clearTimers();
    if (ST.stopStream) ST.stopStream(true);
    ST.ov = null; overlayRoot().innerHTML = '';
    closeDrawer(false);
    const st = ST.resolve(location.hash);
    ST.current = st;
    Object.assign(ST.S, { userMenu: false, rowMenu: null, chatMenu: false, release: 0 });
    ST.emptyDemo = false; ST.noTray = false;
    if (st.setup) st.setup();
    ST.mount(st.view(), { navigated: true });
    if (st.afterRender) st.afterRender();
    ST.renderTray();
    updateReviewBar(st);
    const auto = document.querySelector('#root [data-autofocus]');
    if (st.afterEnter) st.afterEnter();
    if (!overlayRoot().children.length) {
      const main = document.getElementById('main-content');
      if (auto) auto.focus({ preventScroll: true });
      else if (main) main.focus({ preventScroll: true });
    }
    document.title = (st.fixed !== false ? st.id + '@' + ST.BRIEF + ' · ' : '') + 'Smart Tutor';
  };

  /* ---------- review chrome (not product UI) ---------- */
  /* ?shot=1 hides the review bar so tools can render a state at index.html?shot=1#/<state-id> (§11 item 6). */
  ST.shot = /[?&]shot=1(&|$)/.test(location.search);
  ST.flow = null; // { id, steps }
  try { const f = sessionStorage.getItem('st3_flow'); if (f && !ST.shot) ST.flow = f; } catch (e) {}
  function flowInfo(st) {
    if (!ST.flow || !ST.FLOWS) return null;
    const f = ST.FLOWS.find((x) => x.id === ST.flow);
    if (!f) return null;
    const i = f.steps.findIndex((s) => s.state === st.id);
    return { f, i };
  }
  function updateReviewBar(st) {
    const el = document.getElementById('rb-state');
    const label = st.fixed === false ? st.label : `${st.id}@${ST.BRIEF}`;
    const fi = flowInfo(st);
    el.innerHTML = `${fi ? `<span class="rb-flow">${fi.f.id} · ${fi.i >= 0 ? `step ${fi.i + 1}/${fi.f.steps.length}` : 'off the flow'}</span>` : ''}<code>${ST.esc(label)}</code><span class="rb-desc">${ST.esc(fi && fi.i >= 0 ? fi.f.steps[fi.i].text : (st.desc || ''))}</span>`;
    const sim = document.getElementById('rb-sim');
    if (sim) sim.hidden = !(st.id || '').startsWith('library');
    const exit = document.getElementById('rb-exit');
    if (exit) exit.hidden = !fi;
  }
  ST.updateReviewBar = () => ST.current && updateReviewBar(ST.current);
  const idx = () => ST.STATES.findIndex((s) => ST.current && s.id === ST.current.id);
  function step(dir) {
    const fi = ST.current && flowInfo(ST.current);
    if (fi && fi.i >= 0) {
      const n = fi.i + dir;
      if (n >= 0 && n < fi.f.steps.length) { location.hash = '#/' + fi.f.steps[n].state; return; }
      if (n >= fi.f.steps.length) { ST.actions['rb-exit'](); return; }
    }
    const i = idx(); const len = ST.STATES.length;
    location.hash = '#/' + ST.STATES[((i < 0 ? 0 : i) + dir + len) % len].id;
  }
  ST.actions['rb-prev'] = () => step(-1);
  ST.actions['rb-next'] = () => step(1);
  ST.actions['rb-exit'] = () => { ST.flow = null; try { sessionStorage.removeItem('st3_flow'); } catch (e) {} location.hash = '#/index'; };
  ST.actions['start-flow'] = (el) => { ST.flow = el.dataset.flow; try { sessionStorage.setItem('st3_flow', ST.flow); } catch (e) {} const f = ST.FLOWS.find((x) => x.id === ST.flow); ST.goto(f.steps[0].state); };
  ST.actions['rb-sim'] = () => { if (ST.simulateDrop) ST.simulateDrop(); };

  let drawerOpener = null;
  function closeDrawer(restore = true) { const d = document.getElementById('index-drawer-wrap'); if (d) { d.remove(); if (restore && drawerOpener) drawerOpener.focus(); } }
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
      if (e.key === 'Tab') { const f = [...aside.querySelectorAll('button, a')]; if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); } else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); } }
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
