/* Smart Tutor v0.9 — documents: sign-in theme, shared list pattern, Library, uploads,
   subject picker (§6.4), document details (§6.5), Subjects (§6.9). */
(function () {
  const ST = window.ST;
  const S = ST.S;
  const esc = ST.esc, ic = ST.ic;

  /* =========================================================
     §6.2 Keycloak pages: stock keycloak.v2 layout, fields and messages.
     The theme changes only the logo, accent and background colours, font and display name.
     Low-detail references, not designed layouts.
     ========================================================= */
  const kc = (title, body) => `<div class="kc2">
    <main class="kc2-main" id="main-content" tabindex="-1">
      <header class="kc2-header" data-od-id="kc-header">${ST.logo()}<span class="kc2-name">Smart Tutor</span></header>
      <div class="kc2-card" data-od-id="kc-card"><h1>${title}</h1>${body}</div>
      <p class="kc2-ref review-note">${ic('info', 'sm')}<span>Reference only: Keycloak's stock <code class="mono">keycloak.v2</code> layout, fields and messages. Our theme sets the logo, accent and background colours, font and the display name “Smart Tutor”.</span></p>
    </main></div>`;
  const kf = (id, label, type = 'text', value = '', extra = '') => `<div class="field"><label for="${id}">${label} <span class="kc2-req" aria-hidden="true">*</span></label><input class="input" id="${id}" type="${type}" value="${esc(value)}" required ${extra}></div>`;

  ST.authSignIn = () => kc('Sign in to your account', `
    <form class="kc2-form" novalidate onsubmit="return false">
      ${kf('kc-user', 'Username or email', 'text', 'mai.nguyen@example.com', 'autocomplete="username" data-autofocus')}
      ${kf('kc-pass', 'Password', 'password', 'attention2017', 'autocomplete="current-password"')}
      <div class="kc2-row"><label class="check"><input type="checkbox"> Remember me</label><a href="#/auth-sign-in">Forgot Password?</a></div>
      <button class="btn btn-primary kc2-submit" type="button" data-action="go" data-href="#/library-default" data-od-id="kc-sign-in">Sign In</button>
    </form>
    <p class="kc2-alt">New user? <a href="#/auth-sign-up">Register</a></p>`);

  ST.authSignUp = () => kc('Register', `
    <form class="kc2-form" novalidate onsubmit="return false">
      ${kf('kc-em', 'Email', 'email', 'mai.nguyen@example.com', 'autocomplete="email" data-autofocus')}
      ${kf('kc-fn', 'First name', 'text', 'Mai', 'autocomplete="given-name"')}
      ${kf('kc-ln', 'Last name', 'text', 'Nguyen', 'autocomplete="family-name"')}
      ${kf('kc-pw', 'Password', 'password', 'attention2017', 'autocomplete="new-password"')}
      ${kf('kc-pw2', 'Confirm password', 'password', 'attention2017', 'autocomplete="new-password"')}
      <p class="kc2-small"><span aria-hidden="true">*</span> Required fields</p>
      <div class="kc2-row"><a href="#/auth-sign-in">« Back to Login</a>
        <button class="btn btn-primary" type="button" data-action="go" data-href="#/auth-verify-email" data-od-id="kc-register">Register</button></div>
    </form>`);

  ST.authVerify = () => kc('Email verification', `
    <div class="kc2-alert" role="status">${ic('info', 'sm')}<span>You need to verify your email address to activate your account.</span></div>
    <p>An email with instructions to verify your email address has been sent to your address mai.nguyen@example.com.</p>
    <p class="kc2-small">Haven't received a verification code in your email? <a href="#/auth-verify-email" data-action="resend">Click here</a> to re-send the email.</p>
    <p class="review-note kc2-small"><a href="#/library-empty">Prototype: continue as if the link in the email was opened →</a></p>`);
  ST.actions.resend = () => ST.toast('Verification email sent again.');

  /* =========================================================
     Shared list pattern (Library, Conversations, Notes)
     ========================================================= */
  ST.L = {};
  ST.resetList = (o = {}) => { ST.L = Object.assign({ tab: 'active', from: '', to: '', subject: 'all', state: 'all', q: '', sort: 'new', datePop: false }, o); };
  ST.resetList();
  ST.hasFilters = () => !!(ST.L.from || ST.L.to || ST.L.subject !== 'all' || ST.L.state !== 'all' || ST.L.q);
  ST.applyFilters = (items, dateKey) => items.filter((it) => {
    const d = it[dateKey].slice(0, 10);
    if (ST.L.from && d < ST.L.from) return false;
    if (ST.L.to && d > ST.L.to) return false;
    if (ST.L.subject !== 'all' && !it.subjects.includes(ST.L.subject)) return false;
    if (ST.L.state !== 'all' && it.state !== undefined && it.state !== ST.L.state) return false;
    if (ST.L.q && !it.title.toLowerCase().includes(ST.L.q.toLowerCase())) return false;
    return true;
  }).sort((a, b) => (ST.L.sort === 'old' ? 1 : -1) * a[dateKey].localeCompare(b[dateKey]));

  /* M4: one 36px toolbar row: tabs with inline counts, unlabelled filters (dates in one popover), a status chip, the count. */
  const fmtShort = (iso) => ST.fmtLong(iso).replace(/ 2026$/, '');
  ST.toolbar = ({ counts, count, noun, subjects, states = false, chip = null, search = false, sort = false, dateLabel = 'Date' }) => {
    const dateOn = ST.L.from || ST.L.to;
    const dateText = dateOn ? `${dateLabel}: ${ST.L.from ? fmtShort(ST.L.from) : '…'} – ${ST.L.to ? fmtShort(ST.L.to) : '…'}` : dateLabel;
    return `<div class="toolbar" data-od-id="toolbar">
      ${ST.tabsHtml(counts)}
      <div class="tb-filters" role="search" aria-label="Filter ${noun}s">
        ${search ? `<input class="input tb-search" type="search" placeholder="Search ${noun}s" aria-label="Search ${noun}s" value="${esc(ST.L.q)}" data-input="f-q" data-fk="f-q">` : ''}
        <select class="select tb-sel" id="f-subj" aria-label="Subject" data-change="f-subj" data-fk="f-subj">
          <option value="all" ${ST.L.subject === 'all' ? 'selected' : ''}>All subjects</option>
          ${subjects.map((x) => `<option value="${esc(x)}" ${ST.L.subject === x ? 'selected' : ''}>${esc(ST.sname(x))}</option>`).join('')}
        </select>
        <details class="tb-pop" ${ST.L.datePop ? 'open' : ''} data-pop="date"><summary class="tb-btn ${dateOn ? 'on' : ''}" data-fk="f-date">${ic('clock', 'sm')}${esc(dateText)}${ic('chevronDown', 'sm')}</summary>
          <div class="pop" role="group" aria-label="${dateLabel} between">
            <label class="pop-field">From<input class="input" type="date" id="f-from" value="${ST.L.from}" max="${ST.TODAY}" data-change="f-from" data-fk="f-from"></label>
            <label class="pop-field">To<input class="input" type="date" id="f-to" value="${ST.L.to}" max="${ST.TODAY}" data-change="f-to" data-fk="f-to"></label>
          </div></details>
        ${states ? `<select class="select tb-sel" id="f-state" aria-label="State" data-change="f-state" data-fk="f-state">
          ${[['all', 'All states'], ['processing', 'Processing'], ['choose', 'Needs subjects'], ['ready', 'Ready'], ['failed', 'Failed']].map(([v, l]) => `<option value="${v}" ${ST.L.state === v ? 'selected' : ''}>${l}</option>`).join('')}</select>` : ''}
        ${sort ? `<select class="select tb-sel" aria-label="Sort" data-change="f-sort" data-fk="f-sort"><option value="new" ${ST.L.sort === 'new' ? 'selected' : ''}>Newest first</option><option value="old" ${ST.L.sort === 'old' ? 'selected' : ''}>Oldest first</option></select>` : ''}
        ${chip ? `<button class="status-chip" type="button" aria-pressed="${ST.L.state === chip.state}" data-action="f-chip" data-state="${chip.state}" data-fk="f-chip" data-od-id="toolbar-status-chip">${ic('tag', 'sm')}${esc(chip.label)}</button>` : ''}
        ${ST.hasFilters() ? `<button class="btn btn-ghost btn-sm" type="button" data-action="f-clear" data-fk="f-clear">${ic('x', 'sm')}Clear filters</button>` : ''}
      </div>
      <span class="tb-count" aria-live="polite">${ST.plural(count, noun)}</span>
    </div>`;
  };
  /* M4: an inline notice is one 32px row; only errors and blocking states use a full banner. */
  ST.notice = ({ tone = 'info', icon = 'info', html, action = '', id = '' }) => `<div class="notice-row nr-${tone}" role="status" ${id ? `data-od-id="${id}"` : ''}>${ic(icon, 'sm')}<span class="nr-text">${html}</span>${action}</div>`;
  ST.filterBar = ({ count, noun, subjects, states }) => `<div class="filter-bar" role="search" aria-label="Filter ${noun}s">
    <div class="field"><label for="f-subj">Subject</label>
      <select class="select" id="f-subj" data-change="f-subj" data-fk="f-subj">
        <option value="all" ${ST.L.subject === 'all' ? 'selected' : ''}>All subjects</option>
        ${subjects.map((s) => `<option value="${esc(s)}" ${ST.L.subject === s ? 'selected' : ''}>${esc(ST.sname(s))}</option>`).join('')}
      </select></div>
    <div class="range">
      <div class="field"><label for="f-from">From</label><input class="input" type="date" id="f-from" value="${ST.L.from}" max="${ST.TODAY}" data-change="f-from" data-fk="f-from"></div>
      <span class="dash" aria-hidden="true">–</span>
      <div class="field"><label for="f-to">To</label><input class="input" type="date" id="f-to" value="${ST.L.to}" max="${ST.TODAY}" data-change="f-to" data-fk="f-to"></div>
    </div>
    ${states ? `<div class="field"><label for="f-state">State</label><select class="select" id="f-state" data-change="f-state" data-fk="f-state">
      ${[['all', 'All states'], ['processing', 'Processing'], ['choose', 'Needs subjects'], ['ready', 'Ready'], ['failed', 'Failed']].map(([v, l]) => `<option value="${v}" ${ST.L.state === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div>` : ''}
    <div class="active-filters"><span aria-live="polite">${ST.plural(count, noun)}</span>
      ${ST.hasFilters() ? `<button class="btn btn-ghost btn-sm" type="button" data-action="f-clear" data-fk="f-clear">${ic('x', 'sm')}Clear filters</button>` : ''}</div>
  </div>`;
  ST.tabsHtml = (counts) => `<div class="tabs" role="tablist" aria-label="Status">
    ${[['active', 'Active'], ['archived', 'Archived']].map(([k, l]) => `<button class="tab" role="tab" id="tab-${k}" aria-controls="list-panel" aria-selected="${ST.L.tab === k}" tabindex="${ST.L.tab === k ? 0 : -1}" data-action="tab" data-tab="${k}" data-fk="tab-${k}">${l}<span class="count">${counts[k]}</span></button>`).join('')}
  </div>`;
  ST.emptyState = ({ icon, title, text, actions = '' }) => `<div class="empty"><span class="empty-icon">${ic(icon, 'lg')}</span><h2>${title}</h2><p>${text}</p>${actions ? `<div class="actions">${actions}</div>` : ''}</div>`;
  Object.assign(ST.actions, {
    'f-from': (el) => { ST.L.from = el.value; ST.render(); },
    'f-to': (el) => { ST.L.to = el.value; ST.render(); },
    'f-subj': (el) => { ST.L.subject = el.value; ST.render(); },
    'f-state': (el) => { ST.L.state = el.value; ST.render(); },
    'f-clear': () => { Object.assign(ST.L, { from: '', to: '', subject: 'all', state: 'all', q: '' }); ST.render(); const f = document.getElementById('f-subj'); if (f) f.focus(); },
    'f-q': (el) => { ST.L.q = el.value; ST.render(); },
    'f-sort': (el) => { ST.L.sort = el.value; ST.render(); },
    'f-chip': (el) => { ST.L.state = ST.L.state === el.dataset.state ? 'all' : el.dataset.state; ST.L.tab = 'active'; ST.render(); },
    tab: (el) => { ST.L.tab = el.dataset.tab; if (el.dataset.tab === 'archived') ST.L.state = 'all'; ST.render(); }
  });
  document.addEventListener('keydown', (e) => {
    const tab = e.target.closest && e.target.closest('[role="tab"]');
    if (!tab || (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft')) return;
    const tabs = [...tab.parentElement.querySelectorAll('[role="tab"]')];
    const next = tabs[(tabs.indexOf(tab) + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
    next.click(); const n = document.getElementById(next.id); if (n) n.focus();
  });

  /* =========================================================
     Document state badge (one visual language)
     ========================================================= */
  ST.stateBadge = (d, withHint = true) => {
    if (d.archived) return `<span class="state state-archived">${ic('archive')}Archived</span>`;
    const m = {
      uploading: ['state-uploading', ic('upload'), 'Uploading', ''],
      processing: ['state-processing', '<span class="spinner" aria-hidden="true"></span>', 'Processing', 'You can choose subjects when processing finishes.'],
      choose: ['state-choose', ic('tag'), 'Needs subjects', 'Processing finished · suggestions ready'],
      ready: ['state-ready', ic('check'), 'Ready', ''],
      failed: ['state-failed', ic('alert'), 'Failed', d.attempts >= 3 ? 'This file could not be processed' : d.failReason]
    }[d.state];
    return `<span class="state ${m[0]}">${m[1]}${m[2]}</span>${withHint && m[3] ? `<span class="state-hint ${d.state === 'failed' ? 'err' : ''}" title="${esc(m[3])}">${esc(m[3])}</span>` : ''}`;
  };
  const docMeta = (d) => d.titlePending ? `${esc(d.file)} · Reading the first pages…` : d.book ? `${esc(d.authors)} · Book` : d.authors ? `${esc(d.authors)}${d.year ? ' · ' + d.year : ''}` : `${esc(d.file)} · ${d.size}`;

  /* =========================================================
     §6.3 Library
     ========================================================= */
  ST.libraryView = () => {
    const all = ST.emptyDemo ? [] : S.docs.filter((d) => !d.deleted); // K4: a deleted document leaves the Library
    const counts = { active: all.filter((d) => !d.archived).length, archived: all.filter((d) => d.archived).length };
    const inTab = all.filter((d) => (ST.L.tab === 'archived') === d.archived);
    const rows = ST.applyFilters(inTab, 'uploaded');
    const choose = all.filter((d) => !d.archived && d.state === 'choose');
    const processingFirst = S.convs.length ? [] : all.filter((d) => !d.archived && ['uploading', 'processing'].includes(d.state));
    const subjOpts = [];
    all.forEach((d) => d.subjects.forEach((s) => { if (!subjOpts.includes(s)) subjOpts.push(s); }));
    const uploadBtn = `<button class="btn btn-primary" type="button" data-action="upload" data-fk="upload-btn" ${S.uploadLimit ? 'disabled aria-describedby="limit-msg upload-rights"' : 'aria-describedby="upload-rights"'}>${ic('upload', 'sm')}Upload</button>`;
    const limit = S.uploadLimit ? `<div class="banner banner-warn" id="limit-msg">${ic('clock')}<div class="b-body"><strong>Upload limit reached.</strong><span>You can upload up to 20 files per hour and 100 per day. You can upload again at 11:40 (${ST.TZ.short}).</span><span class="b-variant">If it's the daily limit (100 per day): You can upload again at 00:00 (${ST.TZ.short}).</span></div></div>` : '';

    let body;
    if (all.length === 0) {
      body = `<div class="dropzone">
        <span class="dz-icon">${ic('upload', 'lg')}</span>
        <h2>Upload your first document</h2>
        <p>PDFs up to 50 MB and 500 pages. Your documents stay private to you.</p>
        <p class="dz-rights" id="dz-rights" data-od-id="upload-rights">${esc(ST.RIGHTS)}</p>
        <button class="btn btn-primary btn-lg" type="button" data-action="upload" data-autofocus data-fk="upload-big" aria-describedby="dz-rights">${ic('upload', 'sm')}Choose PDFs</button>
        <p class="small">Or drop files anywhere on this page. You can add several at once.</p>
      </div>`;
    } else {
      let list;
      if (rows.length === 0 && ST.hasFilters()) list = ST.emptyState({ icon: 'filter', title: 'No documents match these filters', text: 'Try another subject, state or a wider date range.', actions: `<button class="btn btn-secondary" type="button" data-action="f-clear">Clear filters</button>` });
      else if (rows.length === 0) list = ST.emptyState({ icon: 'archive', title: ST.L.tab === 'archived' ? 'No archived documents' : 'No active documents', text: ST.L.tab === 'archived' ? 'Documents you archive appear here. You can restore them at any time.' : 'Upload a PDF to start asking questions about it.', actions: ST.L.tab === 'archived' ? '' : uploadBtn });
      else list = `<div class="list lib-list" role="table" aria-label="Documents">
        <div class="lib-head" role="row"><span role="columnheader">Document</span><span role="columnheader">Subjects</span><span role="columnheader">State</span><span role="columnheader">Uploaded</span><span role="columnheader"><span class="vh">Actions</span></span></div>
        ${rows.map(libRow).join('')}</div>`;
      body = `${ST.toolbar({ counts, count: rows.length, noun: 'document', subjects: subjOpts, states: ST.L.tab === 'active', dateLabel: 'Uploaded', chip: choose.length && ST.L.tab === 'active' ? { state: 'choose', label: `${choose.length} need${choose.length === 1 ? 's' : ''} subjects` } : null })}
        ${ST.L.tab === 'archived' ? ST.notice({ html: "Archived documents aren't used for answers, but citations to them in past conversations still work. Restore a document to change its subjects." }) : ''}
        <div id="list-panel" role="tabpanel" aria-labelledby="tab-${ST.L.tab}">${list}</div>`;
    }
    const notices = [
      limit,
      S.deletedNotice ? ST.notice({ tone: 'success', icon: 'checkCircle', id: 'library-deleted-confirmation', html: `<em>${esc(S.deletedNotice)}</em> deleted.`, action: `<button class="icon-btn sm" type="button" data-action="deleted-dismiss" aria-label="Dismiss" data-tip="Dismiss">${ic('x', 'sm')}</button>` }) : '',
      !S.convs.length && all.some((d) => d.state === 'ready' && !d.archived) && ST.L.tab === 'active' ? ST.notice({ tone: 'success', icon: 'checkCircle', html: '<strong>Your documents are ready.</strong> Ask anything about them; answers cite the document and page.', action: `<a class="btn btn-primary btn-sm" href="#/chat-new" data-fk="ask-first">${ic('message', 'sm')}Ask a question</a>` }) : '',
      processingFirst.length && !choose.length && ST.L.tab === 'active' ? ST.notice({ icon: 'clock', html: `<strong>Processing ${ST.plural(processingFirst.length, 'document')}.</strong> Titles appear within about 30 seconds; processing takes up to 5 minutes (15 for very long documents).` }) : ''
    ].filter(Boolean).join('');
    const action = all.length ? `<div class="upload-area" data-od-id="library-upload-area"><p class="upload-rights" id="upload-rights">${esc(ST.RIGHTS)}</p>${uploadBtn}</div>` : '';
    return ST.shell({ nav: 'library', content: `<div class="page wide">
      ${ST.pageHead({ title: 'Library', id: 'lib-h', count: all.length ? ST.plural(counts.active, 'active document') : '', info: "Your documents. They're private to you, and the tutor answers only from them.", action })}
      ${notices ? `<div class="notices">${notices}</div>` : ''}
      ${body}
    </div>` });
  };

  /* Subjects sized to content: at most 2 chips, then "+N" with every name in the tooltip and accessible name. */
  const subjChips = (ids) => ids.length <= 2 ? ST.chips(ids, 'sm')
    : `<span class="chips">${ids.slice(0, 2).map((i) => ST.schip(i, 'sm')).join('')}<span class="chip-more" title="${esc(ids.map(ST.sname).join(', '))}" aria-label="${ids.length - 2} more: ${esc(ids.slice(2).map(ST.sname).join(', '))}">+${ids.length - 2}</span></span>`;
  function libRow(d) {
    const needs = !d.archived && d.state === 'choose';
    let primary;
    if (d.archived) primary = `<button class="btn btn-secondary btn-sm" type="button" data-action="doc-restore" data-id="${d.id}" aria-label="Restore ${esc(d.title)}">${ic('restore', 'sm')}Restore</button>`;
    else if (needs) primary = `<button class="btn btn-primary btn-sm" type="button" data-action="choose-one" data-id="${d.id}" data-fk="choose-${d.id}" aria-label="Choose subjects for ${esc(d.title)}">Choose subjects</button>`;
    else if (d.state === 'failed' && (d.attempts || 0) < 3) primary = `<button class="btn btn-secondary btn-sm" type="button" data-action="doc-retry" data-id="${d.id}" data-fk="retry-${d.id}" aria-label="Retry ${esc(d.title)}">${ic('retry', 'sm')}Retry</button>`;
    else primary = `<button class="btn btn-quiet btn-sm" type="button" data-action="open-doc" data-id="${d.id}" aria-label="Open ${esc(d.title)}">Open</button>`;
    const open = S.rowMenu === d.id;
    const canChange = d.subjects.length && !d.archived && d.state === 'ready'; // E7: archived → Restore first
    const menu = open ? `<div class="row-menu" role="menu" aria-label="Actions for ${esc(d.title)}">
      <button class="menu-item" role="menuitem" type="button" data-action="open-doc" data-id="${d.id}">${ic('doc')}Open details</button>
      ${canChange ? `<button class="menu-item" role="menuitem" type="button" data-action="change-subjects" data-id="${d.id}">${ic('tag')}Change subjects</button>` : ''}
      ${!d.archived && d.state !== 'failed' ? `<button class="menu-item" role="menuitem" type="button" data-action="edit-title" data-id="${d.id}">${ic('pen')}Edit title</button>` : ''}
      ${d.state === 'failed' && (d.attempts || 0) < 3 && !d.archived ? `<button class="menu-item" role="menuitem" type="button" data-action="doc-retry" data-id="${d.id}">${ic('retry')}Retry</button>` : ''}
      ${d.archived ? `<button class="menu-item" role="menuitem" type="button" data-action="doc-restore" data-id="${d.id}">${ic('restore')}Restore</button>` : `<button class="menu-item" role="menuitem" type="button" data-action="doc-archive" data-id="${d.id}">${ic('archive')}Archive</button>`}
      ${ST.canDelete(d) ? `<span class="menu-sep" role="separator"></span><button class="menu-item danger" role="menuitem" type="button" data-action="doc-delete" data-id="${d.id}" data-od-id="row-menu-delete">${ic('trash')}Delete…</button>` : ''}
    </div>` : '';
    return `<div class="lib-row ${needs ? 'needs' : ''} ${d.archived ? 'is-archived' : ''} ${d.state === 'failed' ? 'is-failed' : ''} ${open ? 'menu-open' : ''}" role="row" data-od-id="library-row-${d.id}">
      <div class="doc-cell" role="cell"><span class="doc-icon">${ic(d.book ? 'book' : 'doc')}</span>
        <div class="od-stack" style="--od-gap:2px"><button class="doc-title" type="button" data-action="open-doc" data-id="${d.id}" data-fk="title-${d.id}" title="${esc(d.title)}">${esc(d.title)}</button><span class="doc-meta">${docMeta(d)}</span></div></div>
      <div role="cell" class="subj-cell">${d.subjects.length ? subjChips(d.subjects) : `<span class="nc">${d.state === 'failed' ? '—' : 'Not chosen yet'}</span>`}</div>
      <div role="cell" class="state-cell">${ST.stateBadge(d)}</div>
      <div class="row-meta row-date" role="cell">${ST.fmtDate(d.uploaded, false)}</div>
      <div class="row-actions" role="cell">${primary}
        <span class="row-menu-wrap"><button class="icon-btn sm row-more" type="button" data-action="row-more" data-id="${d.id}" data-fk="more-${d.id}" aria-haspopup="menu" aria-expanded="${open}" aria-label="More actions for ${esc(d.title)}" data-tip="More">${ic('more')}</button>${menu}</span></div>
    </div>`;
  }

  Object.assign(ST.actions, {
    'row-more': (el) => { const id = el.dataset.id; S.rowMenu = S.rowMenu === id ? null : id; ST.render(); const m = document.querySelector('.row-menu .menu-item'); if (m) m.focus(); },
    upload: () => { if (S.uploadLimit) return; document.getElementById('file-input').click(); },
    'open-doc': (el) => { S.rowMenu = null; ST.openDetails(el.dataset.id); },
    'edit-title': (el) => { S.rowMenu = null; ST.openDetails(el.dataset.id, { editing: true }); },
    'choose-one': (el) => { const id = el.dataset.id; ST.openPicker([id, ...S.docs.filter((d) => !d.archived && !d.deleted && d.state === 'choose' && d.id !== id).map((d) => d.id)]); },
    'choose-all': () => ST.openPicker(S.docs.filter((d) => !d.archived && d.state === 'choose').map((d) => d.id)),
    'change-subjects': (el) => { S.rowMenu = null; ST.openPicker([el.dataset.id], { mode: 'change' }); },
    'doc-archive': (el) => {
      S.rowMenu = null; const d = ST.doc(el.dataset.id); d.archived = true; ST.render();
      ST.toast(`Archived “${d.title}”. It won't be used for answers.`, { undo: () => { d.archived = false; ST.render(); } });
    },
    'doc-restore': (el) => {
      S.rowMenu = null; const d = ST.doc(el.dataset.id); d.archived = false;
      S.tray.forEach((t) => { if (t.docId === d.id && t.status === 'duplicate-archived') t.status = 'duplicate'; });
      ST.render(); ST.toast(`Restored “${d.title}”.`);
    },
    'doc-retry': (el) => { S.rowMenu = null; ST.retryDoc(ST.doc(el.dataset.id)); },
    'doc-delete': (el) => { S.rowMenu = null; ST.render(); ST.confirmDelete(el.dataset.id); },
    'deleted-dismiss': () => { S.deletedNotice = null; ST.render(); const h = document.getElementById('lib-h'); if (h) h.focus(); }
  });

  /* ---------- simulated upload pipeline (background, survives navigation) ---------- */
  let seq = 0;
  const bg = (fn, ms) => setTimeout(fn, ms);
  const alive = (d) => S.docs.includes(d);
  const prettify = (name) => name.replace(/\.pdf$/i, '').replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  ST.addFiles = (files) => {
    if (S.uploadLimit) { ST.toast(`Upload limit reached. You can upload again at 11:40 (${ST.TZ.short}).`); return; }
    S.trayCollapsed = false;
    const added = [];
    files.forEach((f) => {
      const t = { id: 't' + (++seq), name: f.name, size: f.sizeLabel || (f.size / 1048576).toFixed(1) + ' MB', status: 'uploading', progress: 0 };
      const isPdf = /\.pdf$/i.test(f.name) || f.type === 'application/pdf';
      const mb = f.size ? f.size / 1048576 : parseFloat(f.sizeLabel) || 1;
      const dup = S.docs.find((d) => d.file === f.name);
      if (!isPdf) { t.status = 'rejected'; t.reason = 'Only PDF files can be uploaded.'; }
      else if (mb > 50) { t.status = 'rejected'; t.reason = `This file is ${mb.toFixed(0)} MB; the limit is 50 MB.`; }
      else if (dup) { t.status = dup.archived ? 'duplicate-archived' : 'duplicate'; t.docId = dup.id; }
      S.tray.unshift(t);
      if (t.status !== 'uploading') { ST.announce(`${f.name}: ${t.status === 'rejected' ? 'not uploaded. ' + t.reason : 'already in your library.'}`); return; }
      const src = f.from ? ST.DOCS.find((x) => x.id === f.from) : null;
      const d = {
        id: 'u' + seq, title: src ? src.title : prettify(f.name), extracted: src ? src.title : prettify(f.name), authors: src ? src.authors : null, year: src ? src.year : null, doi: src ? src.doi : null,
        file: f.name, pages: src ? src.pages : 18, size: t.size, uploaded: ST.TODAY + 'T11:20', state: 'uploading', subjects: [], archived: false, tokens: [0, 0],
        suggestions: f.suggestions || [{ id: 'llm', origin: 'yours' }, { id: 'agents', origin: 'yours' }, { id: 'c-ml', origin: 'shared' }],
        summary: src ? src.summary : 'Smart Tutor will add a two-sentence summary once it has read the first pages.'
      };
      t.docId = d.id;
      S.docs.unshift(d);
      added.push([t, d]);
    });
    ST.render();
    added.forEach(([t, d], k) => runUpload(t, d, k));
  };
  function runUpload(t, d, k) {
    const tick = () => {
      if (!alive(d)) return;
      t.progress = Math.min(100, t.progress + 18 + k * 3);
      if (t.progress < 100) { ST.renderTray(); bg(tick, 320); return; }
      t.status = 'done'; d.state = 'processing'; d.titlePending = true; d.realTitle = d.title; d.title = d.file;
      ST.announce(`${t.name} uploaded. Processing.`);
      ST.render();
      bg(() => { if (!alive(d) || !d.titlePending) return; d.titlePending = false; d.title = d.realTitle; ST.render(); }, 1100 + k * 500);
      bg(() => { if (!alive(d) || d.state !== 'processing') return; if (d.titlePending) { d.titlePending = false; d.title = d.realTitle; } d.state = 'choose'; d.tokens = [5800, 410]; ST.announce(`${d.title} has finished processing. Choose its subjects.`); ST.render(); }, 4200 + k * 900);
    };
    bg(tick, 300 + k * 150);
  }
  ST.finishProcessing = (d, ms = 5000) => bg(() => { if (!alive(d) || d.state !== 'processing') return; d.state = 'ready'; d.tokens = [36000, 1600]; ST.announce(`${d.title} is ready.`); ST.render(); }, ms);
  ST.retryDoc = (d) => {
    d.attempts = (d.attempts || 0) + 1; d.state = 'processing';
    ST.render(); ST.announce(`Retrying ${d.title}.`);
    bg(() => {
      if (!alive(d)) return;
      d.state = 'failed';
      ST.announce(d.attempts >= 3 ? `${d.title}: this file could not be processed.` : `${d.title} failed again: ${d.failReason}.`);
      ST.render();
    }, 3500);
  };
  ST.simulateDrop = () => {
    if (!(ST.current && ST.current.id.startsWith('library'))) ST.goto('library-default');
    ST.addFiles(ST.J1_FILES.map((f) => ({ name: f.file, sizeLabel: f.size, from: f.from, suggestions: f.suggestions })));
  };
  document.getElementById('file-input').addEventListener('change', (e) => { const files = [...e.target.files]; e.target.value = ''; if (files.length) ST.addFiles(files); });

  /* Page-wide drop zone on Library screens */
  let dragDepth = 0;
  const onLibrary = () => ST.current && ST.current.id.startsWith('library');
  const showDrop = (on) => {
    let ov = document.getElementById('drop-ov');
    if (on && !ov) { ov = document.createElement('div'); ov.id = 'drop-ov'; ov.className = 'drop-overlay'; ov.setAttribute('aria-hidden', 'true'); ov.innerHTML = `<div>${ic('upload', 'lg')}Drop PDFs to upload<span class="ov-rights">${esc(ST.RIGHTS)}</span></div>`; document.body.appendChild(ov); }
    if (!on && ov) ov.remove();
  };
  ST.showDrop = showDrop;
  document.addEventListener('dragenter', (e) => { if (!onLibrary()) return; e.preventDefault(); dragDepth++; showDrop(true); });
  document.addEventListener('dragover', (e) => { if (onLibrary()) e.preventDefault(); });
  document.addEventListener('dragleave', () => { if (!onLibrary()) return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) showDrop(false); });
  document.addEventListener('drop', (e) => { if (!onLibrary()) return; e.preventDefault(); dragDepth = 0; showDrop(false); const files = [...(e.dataTransfer.files || [])]; if (files.length) ST.addFiles(files); });

  /* =========================================================
     §6.4 Choose subjects (picker)
     ========================================================= */
  ST.PK = null;
  const norm = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().replace(/s$/, '');
  const ALIASES = { llm: 'llm', 'large language model': 'llm', 'large language modell': 'llm', 'language model': 'llm', rag: 'rag', 'retrieval augmented generation': 'rag', 'ai agent': 'agents', agent: 'agents', 'llm agent': 'agents', rl: 'rl', 'reinforcement learning': 'rl', 'tool': 'tool', 'tool use': 'tool' };
  ST.analyzeName = (raw, { personal = false, exclude = null } = {}) => {
    const v = raw.trim();
    if (!v) return { kind: 'empty' };
    if (v.length > 60) return { kind: 'long', msg: 'Subject names can be up to 60 characters.' };
    if (/@|\b\d{6,}\b|\bmai\b|\bnguyen\b|\bmy (thesis|supervisor|phone)\b/i.test(v)) return { kind: 'reject', msg: "Subject names can't include names, contact details or other personal information." };
    if (/\b(stupid|idiot|damn|crap)\b/i.test(v)) return { kind: 'reject', msg: 'This name could offend other learners.' };
    if (personal) {
      const clash = ST.mySubjects().find((id) => id !== exclude && ST.sname(id).toLowerCase() === v.toLowerCase());
      if (clash) return { kind: 'reject', msg: `You already call another of your subjects “${ST.sname(clash)}”. Your own subject names must differ from each other.` };
      return { kind: 'ok' };
    }
    const n = norm(v);
    const exact = S.catalog.find((s) => s.shared.toLowerCase() === v.toLowerCase() || (s.mine && s.mine.toLowerCase() === v.toLowerCase()));
    if (exact) return { kind: 'exact', id: exact.id };
    const near = ALIASES[n] || (S.catalog.find((s) => norm(s.shared) === n) || {}).id;
    if (near) return { kind: 'near', id: near, msg: `We'll use the existing subject ${ST.subj(near).shared}.` };
    return { kind: 'new' };
  };

  ST.openPicker = (ids, { mode = 'choose', fromPanel = null, typed = '', step = 0, saved = false } = {}) => {
    ST.PK = { queue: ids, i: step, mode, fromPanel, typed, taOpen: !!typed, taIdx: 0, saved, done: 0 };
    initPickerDoc();
    ST.showOverlay(pickerView, { onClose: () => { const back = ST.PK && ST.PK.fromPanel; ST.PK = null; if (back) setTimeout(() => ST.openDetails(back), 0); } });
  };
  function initPickerDoc() {
    const P = ST.PK; const d = ST.doc(P.queue[P.i]);
    P.sel = P.mode === 'change' ? d.subjects.slice() : (d.suggestions && d.suggestions.length ? [d.suggestions[0].id] : []);
    P.options = (d.suggestions || []).map((s) => ({ id: s.id, origin: s.origin }));
    d.subjects.forEach((s) => { if (!P.options.find((o) => o.id === s)) P.options.push({ id: s, origin: 'yours' }); });
  }
  const ORIGIN = { yours: 'Your subject', shared: 'Shared subject', new: 'New' };
  function pickerView() {
    const P = ST.PK; const d = ST.doc(P.queue[P.i]);
    const multi = P.queue.length > 1;
    const head = `<header><div><p class="sp-kicker" style="font-size:12px;font-weight:650;text-transform:uppercase;letter-spacing:.06em;color:var(--text-2)">${multi ? `Document ${P.i + 1} of ${P.queue.length}` : P.mode === 'change' ? 'Ready document' : 'Processing finished'}</p>
      <h2 id="pk-title">${P.mode === 'change' ? 'Change subjects' : 'Choose subjects'}</h2></div>
      <button class="icon-btn sm" type="button" data-action="pk-close" aria-label="Close">${ic('x')}</button></header>`;
    if (P.saved) {
      const msg = P.mode === 'change'
        ? `<em>${esc(d.title)}</em> now uses ${d.subjects.map((s) => esc(ST.sname(s))).join(', ')}.`
        : `<em>${esc(d.title)}</em> is ready to use.`;
      return `<div class="dialog-scrim" data-scrim><div class="dialog picker" role="dialog" aria-modal="true" aria-labelledby="pk-title">${head}
        <div class="d-body" role="status"><div class="banner banner-success">${ic('checkCircle')}<div class="b-body"><strong>Subjects saved.</strong><span>${msg}</span></div></div>
          <p>${ST.chips(d.subjects)}</p></div>
        <footer><button class="btn btn-primary" type="button" data-action="pk-close" data-autofocus>Done</button></footer></div></div>`;
    }
    const n = P.sel.length;
    const typedA = ST.analyzeName(P.typed);
    const q = P.typed.trim().toLowerCase();
    const matches = q ? S.catalog.filter((s) => s.shared.toLowerCase().includes(q) || (s.mine && s.mine.toLowerCase().includes(q))).slice(0, 5) : [];
    const exactish = typedA.kind === 'exact' || typedA.kind === 'near';
    const showCreate = q && !exactish && typedA.kind === 'new';
    const opts = matches.map((s) => ({ id: s.id, label: s.mine || s.shared, meta: s.mine ? `Your subject · shared name ${s.shared}` : ST.mySubjects().includes(s.id) ? 'Your subject' : 'Shared subject' }));
    if (showCreate) opts.push({ id: '__new', label: `Create “${P.typed.trim()}”`, meta: 'New subject, visible to everyone' });
    const taOpen = P.taOpen && opts.length && typedA.kind !== 'long' && typedA.kind !== 'reject';
    let note = '';
    if (typedA.kind === 'near') note = `<p class="field-note info" id="pk-note">${ic('info')}<span>We'll use the existing subject <em>${esc(ST.subj(typedA.id).shared)}</em>.</span></p>`;
    if (typedA.kind === 'reject') note = `<p class="field-note err" id="pk-note">${ic('alertCircle')}<span><strong>Please choose a different name.</strong><br>${esc(typedA.msg)}</span></p>`;
    if (typedA.kind === 'long') note = `<p class="field-note err" id="pk-note">${ic('alertCircle')}<span>${esc(typedA.msg)}</span></p>`;
    const canAdd = q && ['exact', 'near', 'new'].includes(typedA.kind) && n < 3;
    return `<div class="dialog-scrim" data-scrim><div class="dialog picker" role="dialog" aria-modal="true" aria-labelledby="pk-title">${head}
      <div class="d-body" style="gap:20px;color:var(--text)" data-keep-scroll="pk">
        <div class="picker-doc"><span class="pd-title">${esc(d.title)}</span><span class="small muted">${docMeta(d)}</span>
          ${d.summary ? `<p class="pd-sum">${esc(d.summary)}</p>` : ''}</div>
        <fieldset style="border:0;margin:0;padding:0;display:grid;gap:12px">
          <legend class="od-row" style="width:100%;justify-content:space-between;margin-bottom:12px"><span class="label">Suggested subjects</span>
            <span class="counter ${n === 3 ? 'max' : ''}" aria-live="polite">${n === 3 ? '3 of 3 selected · the maximum' : `${n} of 3 selected`}</span></legend>
          <div class="sugg">${P.options.map((o) => { const on = P.sel.includes(o.id); return `<button type="button" class="schip" data-s="${ST.hueKey(o.id)}" aria-pressed="${on}" data-action="pk-toggle" data-id="${o.id}" data-fk="pk-${o.id}" ${!on && n >= 3 ? 'disabled' : ''}>
            ${ic('check', 'sm ck')}<span class="dot" aria-hidden="true"></span>${esc(ST.sname(o.id))}<span class="origin">· ${ORIGIN[o.origin] || 'Shared subject'}</span></button>`; }).join('')}</div>
        </fieldset>
        <div class="field">
          <label for="pk-input">Add your own</label>
          <div class="ta-row"><div class="ta-wrap" style="flex:1">
            <input class="input" id="pk-input" type="text" role="combobox" aria-autocomplete="list" aria-expanded="${!!taOpen}" aria-controls="pk-list" ${taOpen ? `aria-activedescendant="pk-opt-${P.taIdx}"` : ''}
              aria-describedby="pk-help${note ? ' pk-note' : ''}" ${typedA.kind === 'reject' || typedA.kind === 'long' ? 'aria-invalid="true"' : ''} value="${esc(P.typed)}" placeholder="Search subjects" data-input="pk-type" data-fk="pk-input" autocomplete="off" ${n >= 3 ? 'disabled' : ''}>
            ${taOpen ? `<ul class="ta-list" id="pk-list" role="listbox" aria-label="Matching subjects">${opts.map((o, i) => `<li id="pk-opt-${i}" role="option" aria-selected="${i === P.taIdx}" data-action="pk-pick" data-id="${o.id}"><span>${esc(o.label)}</span><span class="meta">${esc(o.meta)}</span></li>`).join('')}</ul>` : ''}
          </div><button class="btn btn-secondary" type="button" data-action="pk-add" data-fk="pk-add" ${canAdd ? '' : 'disabled'}>Add</button></div>
          <span class="helper od-row" id="pk-help" style="justify-content:space-between"><span>Subject names are visible to everyone. Don't include personal information.</span>
            ${P.typed ? `<span class="counter od-nowrap" style="${P.typed.trim().length > 60 ? 'color:var(--danger);font-weight:650' : ''}">${P.typed.trim().length}/60</span>` : ''}</span>
          ${note}
          ${n >= 3 ? `<span class="helper">You've chosen 3 subjects, the maximum. Remove one to add another.</span>` : ''}
        </div>
      </div>
      <footer>
        ${multi ? `<span class="step-nav">${P.i + 1} of ${P.queue.length}</span><button class="btn btn-quiet" type="button" data-action="pk-skip">Skip</button>` : `<button class="btn btn-secondary" type="button" data-action="pk-close">Cancel</button>`}
        <button class="btn btn-primary" type="button" data-action="pk-save" data-fk="pk-save" ${n ? '' : 'disabled aria-describedby="pk-save-h"'}>${multi && P.i < P.queue.length - 1 ? 'Save and next' : 'Save'}</button>
        ${n ? '' : '<span class="vh" id="pk-save-h">Choose at least one subject to save.</span>'}
      </footer></div></div>`;
  }
  function pickId(id) {
    const P = ST.PK;
    if (id === '__new') {
      const name = P.typed.trim();
      const nid = 'x' + (++seq);
      S.catalog.push({ id: nid, shared: name, mine: null, isNew: true });
      id = nid;
      ST.announce(`New subject ${name} added. Subject names are visible to everyone.`);
    }
    if (!P.options.find((o) => o.id === id)) P.options.push({ id, origin: ST.subj(id).isNew ? 'new' : ST.mySubjects().includes(id) ? 'yours' : 'shared' });
    if (!P.sel.includes(id) && P.sel.length < 3) P.sel.push(id);
    P.typed = ''; P.taOpen = false; P.taIdx = 0;
    ST.redrawOverlay();
    const inp = document.getElementById('pk-input'); if (inp && !inp.disabled) inp.focus(); else { const s = document.querySelector('[data-fk="pk-save"]'); if (s) s.focus(); }
  }
  function savePicker() {
    const P = ST.PK; const d = ST.doc(P.queue[P.i]);
    d.subjects = P.sel.slice();
    if (d.state === 'choose') { d.state = 'ready'; ST.announce(`Subjects saved. ${d.title} is ready to use.`); }
    P.done++;
    ST.render();
    if (P.queue.length > 1) {
      if (P.i < P.queue.length - 1) { P.i++; initPickerDoc(); ST.redrawOverlay(); ST.announce(`Saved. Document ${P.i + 1} of ${P.queue.length}.`); const f = document.querySelector('.sugg button'); if (f) f.focus(); return; }
      ST.hideOverlay();
      ST.toast(`Subjects saved for ${ST.plural(P.done, 'document')}. They're ready to use.`);
      return;
    }
    P.saved = true; ST.redrawOverlay();
    const b = document.querySelector('#overlay-root [data-autofocus]'); if (b) b.focus();
  }
  Object.assign(ST.actions, {
    'pk-close': () => ST.hideOverlay(),
    'pk-toggle': (el) => { const P = ST.PK; const id = el.dataset.id; P.sel = P.sel.includes(id) ? P.sel.filter((x) => x !== id) : P.sel.length < 3 ? [...P.sel, id] : P.sel; ST.redrawOverlay(); },
    'pk-type': (el) => { ST.PK.typed = el.value; ST.PK.taOpen = true; ST.PK.taIdx = 0; ST.redrawOverlay(); },
    'pk-pick': (el) => pickId(el.dataset.id),
    'pk-add': () => { const a = ST.analyzeName(ST.PK.typed); if (a.kind === 'exact' || a.kind === 'near') pickId(a.id); else if (a.kind === 'new') pickId('__new'); },
    'pk-save': () => savePicker(),
    'pk-skip': () => { const P = ST.PK; if (P.i < P.queue.length - 1) { P.i++; initPickerDoc(); ST.redrawOverlay(); } else { ST.hideOverlay(); if (P.done) ST.toast(`Subjects saved for ${ST.plural(P.done, 'document')}.`); } }
  });
  document.addEventListener('keydown', (e) => {
    if (e.target.id !== 'pk-input' || !ST.PK) return;
    const opts = document.querySelectorAll('#pk-list [role="option"]');
    if (e.key === 'ArrowDown' && opts.length) { e.preventDefault(); ST.PK.taIdx = (ST.PK.taIdx + 1) % opts.length; ST.redrawOverlay(); }
    else if (e.key === 'ArrowUp' && opts.length) { e.preventDefault(); ST.PK.taIdx = (ST.PK.taIdx - 1 + opts.length) % opts.length; ST.redrawOverlay(); }
    else if (e.key === 'Enter') { e.preventDefault(); if (opts.length && ST.PK.taOpen) pickId(opts[ST.PK.taIdx].dataset.id); else ST.actions['pk-add'](); }
    else if (e.key === 'Escape' && ST.PK.taOpen) { e.preventDefault(); e.stopPropagation(); ST.PK.taOpen = false; ST.redrawOverlay(); }
  }, true);

  /* =========================================================
     §6.5 Document details (side panel)
     ========================================================= */
  ST.DP = null;
  ST.openDetails = (id, { editing = false, cited = null, draft = null } = {}) => {
    const d = ST.doc(id);
    ST.DP = { id, editing, draft: draft != null ? draft : d.title, cited };
    ST.showOverlay(detailsView, { onClose: () => { ST.DP = null; } });
  };
  const canOpen = (d) => ['ready', 'choose'].includes(d.state); // §6.12: ready, choose subjects, and archived (archived keeps its state)
  function detailsView() {
    const P = ST.DP; const d = ST.doc(P.id);
    const titleBlock = P.editing
      ? `<div class="field"><label for="dp-title">Display title</label>
          <input class="input" id="dp-title" type="text" value="${esc(P.draft)}" data-input="dp-draft" data-fk="dp-title" data-autofocus aria-describedby="dp-title-h">
          <span class="helper" id="dp-title-h">Only changes how the title appears to you. Citations use this title.</span>
          <div class="od-cluster" style="margin-top:8px">
            <button class="btn btn-primary btn-sm" type="button" data-action="dp-save-title" ${P.draft.trim() ? '' : 'disabled'}>Save title</button>
            <button class="btn btn-quiet btn-sm" type="button" data-action="dp-cancel-title">Cancel</button>
            ${d.extracted && P.draft !== d.extracted ? `<button class="btn btn-ghost btn-sm" type="button" data-action="dp-reset-title">${ic('restore', 'sm')}Reset to extracted title</button>` : ''}
          </div></div>`
      : `<div class="od-row-top"><h2 class="sp-title od-fill" id="dp-h">${esc(d.title)}</h2>
          ${!d.archived && d.state !== 'failed' ? `<button class="btn btn-ghost btn-sm od-fixed" type="button" data-action="dp-edit-title" data-fk="dp-edit">${ic('pen', 'sm')}Edit title</button>` : ''}</div>
          ${d.extracted && d.title !== d.extracted ? `<p class="small muted">Extracted title: ${esc(d.extracted)} · <button class="btn btn-ghost btn-sm" type="button" data-action="dp-reset-title" style="padding:0 4px;min-height:24px">Reset to extracted title</button></p>` : ''}`;
    const failed = d.state === 'failed' && !d.archived
      ? `<div class="banner banner-danger">${ic('alert')}<div class="b-body"><strong>${d.attempts >= 3 ? 'This file could not be processed' : 'Processing failed'}</strong><span>${d.attempts >= 3 ? 'We tried 3 times. Try exporting the PDF again, or uploading a text-based copy.' : `${esc(d.failReason)}. Attempt ${d.attempts} of 3.${d.scanned ? ' A copy with selectable text will work.' : ''}`}</span></div>
          ${d.attempts < 3 ? `<button class="btn btn-secondary btn-sm" type="button" data-action="doc-retry" data-id="${d.id}">${ic('retry', 'sm')}Retry</button>` : ''}</div>` : '';
    const archived = d.archived ? `<div class="banner">${ic('archive')}<div class="b-body"><strong>Archived</strong><span>Not used for answers. Citations to it in past conversations still open here. Restore it to change its subjects.</span></div></div>` : '';
    const processing = d.state === 'processing' && !d.archived ? `<div class="banner banner-info" role="status"><span class="spinner" aria-hidden="true" style="margin-top:3px"></span><div class="b-body"><strong>Processing all ${d.pages} pages</strong><span>${d.pages > 300 ? 'Very long documents can take up to 15 minutes.' : 'This can take up to 5 minutes.'} You can choose subjects when processing finishes.</span></div></div>` : '';
    const cited = P.cited ? `<div class="banner banner-info">${ic('quote')}<div class="b-body"><strong>Cited ${P.cited.page ? `on page ${P.cited.page}` : '· page unavailable'}</strong><span>From an answer in your conversation.</span></div></div>` : '';
    const facts = [['Authors', d.authors || '—'], ['Year', d.year || (d.book ? 'Not shown' : '—')], ['DOI', d.doi || '—'], ['File name', d.file], ['Pages', d.pages], ['Uploaded', ST.fmtLong(d.uploaded)]];
    return `<div class="panel-scrim" data-scrim></div>
      <aside class="side-panel" role="dialog" aria-modal="true" aria-labelledby="${P.editing ? 'dp-title' : 'dp-h'}">
        <header><div class="od-fill od-stack" style="--od-gap:6px"><span class="sp-kicker">Document details</span><span>${ST.stateBadge(d)}</span></div>
          <button class="icon-btn sm" type="button" data-action="dp-close" aria-label="Close document details" ${P.editing ? '' : 'data-autofocus'}>${ic('x')}</button></header>
        <div class="sp-body" data-keep-scroll="dp">
          ${cited}${processing}${failed}${archived}
          <div class="sp-section">${titleBlock}</div>
          <dl class="facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
          <section class="sp-section" aria-labelledby="dp-sum"><h3 id="dp-sum">Summary</h3>${d.summary ? `<p class="summary-text">${esc(d.summary)}</p>` : '<p class="small muted">A summary appears once Smart Tutor can read this PDF.</p>'}</section>
          <section class="sp-section" aria-labelledby="dp-sub"><h3 id="dp-sub">Subjects</h3>
            ${d.subjects.length ? ST.chips(d.subjects) : `<p class="small muted">${d.state === 'choose' ? 'Processing has finished and suggestions are ready.' : d.state === 'processing' ? 'You can choose subjects when processing finishes.' : 'No subjects yet.'}</p>`}
            ${!d.archived && d.state === 'choose' ? `<button class="btn btn-primary btn-sm" type="button" data-action="dp-change" style="justify-self:start">Choose subjects</button>` : ''}
            ${d.subjects.length && !d.archived && d.state === 'ready' ? `<button class="btn btn-secondary btn-sm" type="button" data-action="dp-change" data-fk="dp-change" style="justify-self:start">${ic('tag', 'sm')}Change subjects</button>` : ''}
          </section>
        </div>
        <footer class="dp-foot">
          ${ST.canDelete(d) ? `<button class="btn btn-danger-quiet" type="button" data-action="dp-delete" data-fk="dp-delete" data-od-id="details-delete">${ic('trash', 'sm')}Delete…</button>` : ''}
          <span class="od-fill"></span>
          ${d.archived ? `<button class="btn btn-${canOpen(d) ? 'secondary' : 'primary'}" type="button" data-action="dp-restore" data-od-id="details-restore">${ic('restore', 'sm')}Restore</button>`
            : `<button class="btn btn-secondary" type="button" data-action="dp-archive" data-fk="dp-archive" data-od-id="details-archive">${ic('archive', 'sm')}Archive</button>`}
          ${canOpen(d) ? `<button class="btn btn-primary" type="button" data-action="dp-open" data-fk="dp-open" data-od-id="details-open">${ic('doc', 'sm')}Open</button>` : ''}</footer>
      </aside>`;
  }
  Object.assign(ST.actions, {
    'dp-close': () => ST.hideOverlay(),
    'dp-open': () => { const id = ST.DP.id; ST.hideOverlay(false); ST.openViewer(id, { page: 1, from: 'details' }); },
    'dp-delete': () => { const id = ST.DP.id; ST.hideOverlay(false); ST.confirmDelete(id, { fromDetails: true }); },
    'dp-edit-title': () => { ST.DP.editing = true; ST.DP.draft = ST.doc(ST.DP.id).title; ST.redrawOverlay(); const i = document.getElementById('dp-title'); if (i) i.focus(); },
    'dp-draft': (el) => { ST.DP.draft = el.value; const b = document.querySelector('[data-action="dp-save-title"]'); if (b) b.disabled = !el.value.trim(); },
    'dp-cancel-title': () => { ST.DP.editing = false; ST.redrawOverlay(); const b = document.querySelector('[data-fk="dp-edit"]'); if (b) b.focus(); },
    'dp-save-title': () => { const d = ST.doc(ST.DP.id); d.title = ST.DP.draft.trim(); ST.DP.editing = false; ST.render(); ST.toast('Title updated.'); const b = document.querySelector('[data-fk="dp-edit"]'); if (b) b.focus(); },
    'dp-reset-title': () => { const d = ST.doc(ST.DP.id); d.title = d.extracted; ST.DP.draft = d.extracted; ST.DP.editing = false; ST.render(); ST.toast('Title reset to the extracted title.'); },
    'dp-change': () => { const id = ST.DP.id; const d = ST.doc(id); ST.hideOverlay(false); ST.openPicker([id], { mode: d.state === 'choose' ? 'choose' : 'change', fromPanel: id }); },
    'dp-archive': () => { const d = ST.doc(ST.DP.id); d.archived = true; ST.render(); ST.announce('Document archived.'); ST.toast(`Archived “${d.title}”. It won't be used for answers.`, { undo: () => { d.archived = false; ST.render(); } }); },
    'dp-restore': () => { const d = ST.doc(ST.DP.id); d.archived = false; ST.render(); ST.announce('Document restored.'); ST.toast(`Restored “${d.title}”.`); }
  });

  /* =========================================================
     K4 · Delete a document (§6.3): confirmed, permanent, not while processing
     ========================================================= */
  ST.canDelete = (d) => !['uploading', 'processing'].includes(d.state);
  ST.deleteDoc = (d) => {
    d.deleted = true; d.archived = false;
    S.deletedNotice = d.title;
    S.tray = S.tray.filter((t) => t.docId !== d.id);
  };
  ST.confirmDelete = (id, { fromDetails = false } = {}) => {
    const d = ST.doc(id);
    let done = false;
    ST.openDialog({
      title: `Delete <em>${esc(d.title)}</em>?`,
      body: `<p>This can't be undone. Conversations and notes keep their text.</p>
        ${d.archived ? '' : `<div class="del-alt"><p>Archive hides it and can be undone.</p><button class="btn btn-secondary btn-sm" type="button" data-action="del-archive-instead" data-id="${d.id}" data-od-id="delete-archive-instead">${ic('archive', 'sm')}Archive instead</button></div>`}`,
      actions: [
        { label: 'Cancel', autofocus: true },
        { label: `${ic('trash', 'sm')}Delete`, cls: 'btn-danger', onClick: () => { done = true; ST.deleteDoc(d); } }
      ],
      onClose: () => {
        if (done || d.deleted) {
          if (ST.current && ST.current.id.startsWith('library')) ST.render(); else ST.goto('library-default');
          setTimeout(() => { const h = document.getElementById('lib-h'); if (h) h.focus(); }, 0);
          ST.announce(`${d.title} deleted.`);
        } else if (fromDetails && !d.archived) setTimeout(() => ST.openDetails(d.id), 0);
      }
    });
  };
  ST.actions['del-archive-instead'] = (el) => {
    const d = ST.doc(el.dataset.id); d.archived = true; ST.hideOverlay(false); ST.render();
    ST.toast(`Archived “${d.title}”. It won't be used for answers.`, { undo: () => { d.archived = false; ST.render(); } });
    const h = document.getElementById('lib-h'); if (h) h.focus();
  };

  /* =========================================================
     §6.9 Subjects (personal rename)
     ========================================================= */
  ST.SB = { editing: null, draft: '' };
  ST.subjectsView = () => {
    const mine = ST.mySubjects();
    const docCount = (id) => S.docs.filter((d) => d.state === 'ready' && !d.archived && d.subjects.includes(id)).length;
    const convCount = (id) => S.convs.filter((c) => c.subjects.includes(id)).length;
    return ST.shell({ nav: 'subjects', content: `<div class="page">
      ${ST.pageHead({ title: 'Subjects', count: ST.plural(mine.length, 'subject'), info: 'Subjects come from your documents. Rename one to match how you think about it. Only you see your names.' })}
      <div class="subj-list" role="table" aria-label="My subjects">
        <div class="subj-head" role="row"><span role="columnheader">Subject</span><span role="columnheader">Documents</span><span role="columnheader">Conversations</span><span role="columnheader"><span class="vh">Actions</span></span></div>
        ${mine.map((id) => {
          const s = ST.subj(id);
          const editing = ST.SB.editing === id;
          const a = editing ? ST.analyzeName(ST.SB.draft, { personal: true, exclude: id }) : null;
          const bad = a && (a.kind === 'reject' || a.kind === 'long');
          return `<div class="subj-row" role="row">
            <div class="subj-name" role="cell"><a href="#/library-default" data-action="subj-filter" data-id="${id}" style="text-decoration:none" aria-label="Show documents in ${esc(ST.sname(id))}">${ST.schip(id)}</a>
              ${s.mine ? `<span class="shared">Shared name: ${esc(s.shared)}</span>` : ''}</div>
            <div class="row-meta" role="cell">${ST.plural(docCount(id), 'document')}</div>
            <div class="row-meta" role="cell">${ST.plural(convCount(id), 'conversation')}</div>
            <div class="row-actions" role="cell">
              ${s.mine ? `<button class="btn btn-ghost btn-sm" type="button" data-action="subj-reset" data-id="${id}">${ic('restore', 'sm')}Reset name</button>` : ''}
              <button class="btn btn-secondary btn-sm" type="button" data-action="subj-rename" data-id="${id}" data-fk="ren-${id}" ${editing ? 'disabled' : ''}>${ic('pen', 'sm')}Rename</button></div>
            ${editing ? `<form class="rename-form" onsubmit="return false" aria-label="Rename ${esc(ST.sname(id))}">
              <label class="label" for="ren-input">Your name for this subject</label>
              <div class="ta-row"><input class="input" id="ren-input" type="text" value="${esc(ST.SB.draft)}" data-input="subj-draft" data-fk="ren-input" aria-describedby="ren-help${bad ? ' ren-err' : ''}" ${bad ? 'aria-invalid="true"' : ''} data-autofocus>
                <button class="btn btn-primary" type="button" data-action="subj-save" data-id="${id}" ${bad || !ST.SB.draft.trim() ? 'disabled' : ''}>Save</button>
                <button class="btn btn-quiet" type="button" data-action="subj-cancel">Cancel</button></div>
              <span class="helper od-row" id="ren-help" style="justify-content:space-between;max-width:560px"><span>Only you see this name. Don't include personal information.</span><span class="counter od-nowrap" style="${ST.SB.draft.trim().length > 60 ? 'color:var(--danger);font-weight:650' : ''}">${ST.SB.draft.trim().length}/60</span></span>
              ${bad ? `<p class="field-note err" id="ren-err">${ic('alertCircle')}<span>${a.kind === 'reject' ? '<strong>Please choose a different name.</strong><br>' : ''}${esc(a.msg)}</span></p>` : ''}
            </form>` : ''}
          </div>`;
        }).join('')}
      </div>
      <p class="legend-line">${ic('info', 'sm')}There's no need to create or delete subjects here. They come from the documents in your Library.</p>
    </div>` });
  };
  Object.assign(ST.actions, {
    'subj-filter': (el, e) => { e.preventDefault(); ST.resetList({ subject: el.dataset.id }); ST.keepListFilters = true; ST.goto('library-default'); },
    'subj-rename': (el) => { ST.SB = { editing: el.dataset.id, draft: ST.sname(el.dataset.id) }; ST.render(); const i = document.getElementById('ren-input'); if (i) { i.focus(); i.select(); } },
    'subj-draft': (el) => { ST.SB.draft = el.value; ST.render(); },
    'subj-cancel': () => { const id = ST.SB.editing; ST.SB = { editing: null, draft: '' }; ST.render(); const b = document.querySelector(`[data-fk="ren-${id}"]`); if (b) b.focus(); },
    'subj-save': (el) => {
      const s = ST.subj(el.dataset.id); const v = ST.SB.draft.trim();
      s.mine = v === s.shared ? null : v; ST.SB = { editing: null, draft: '' }; ST.render();
      ST.toast(`Renamed to “${v}”. Only you see this name.`);
      const b = document.querySelector(`[data-fk="ren-${s.id}"]`); if (b) b.focus();
    },
    'subj-reset': (el) => { const s = ST.subj(el.dataset.id); const old = s.mine; s.mine = null; ST.render(); ST.toast(`Using the shared name “${s.shared}” again.`, { undo: () => { s.mine = old; ST.render(); } }); }
  });
})();
