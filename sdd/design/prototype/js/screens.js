/* Smart Tutor v0.4 — Conversations (§6.7), Notes (§6.8), Usage (§6.10), Settings (§6.11). */
(function () {
  const ST = window.ST;
  const S = ST.S;
  const esc = ST.esc, ic = ST.ic;
  const subjOptions = (items) => { const o = []; items.forEach((i) => i.subjects.forEach((s) => { if (!o.includes(s)) o.push(s); })); return o; };

  /* ---------- §6.7 Conversations ---------- */
  ST.conversationsView = () => {
    const all = ST.emptyDemo ? [] : S.convs;
    const inTab = all.filter((c) => (ST.L.tab === 'archived') === c.archived);
    const rows = ST.applyFilters(inTab, 'last').sort((a, b) => b.last.localeCompare(a.last));
    const counts = { active: all.filter((c) => !c.archived).length, archived: all.filter((c) => c.archived).length };
    let list;
    if (!all.length) list = ST.emptyState({ icon: 'message', title: 'No conversations yet', text: 'Ask a question about your documents. Every conversation is saved here so you can come back to it.', actions: `<a class="btn btn-primary" href="#/chat-new">${ic('plus', 'sm')}Start a conversation</a>` });
    else if (!rows.length && ST.hasFilters()) list = ST.emptyState({ icon: 'filter', title: 'No conversations match these filters', text: 'Try another subject or a wider date range.', actions: `<button class="btn btn-secondary" type="button" data-action="f-clear">Clear filters</button>` });
    else if (!rows.length) list = ST.emptyState({ icon: 'archive', title: 'No archived conversations', text: 'Conversations you archive appear here. You can restore them at any time.' });
    else list = `<div class="list" role="table" aria-label="Conversations">
      <div class="list-head" role="row" style="grid-template-columns:minmax(0,1fr) 300px 140px 200px"><span role="columnheader">Conversation</span><span role="columnheader">Subjects</span><span role="columnheader">Last activity</span><span role="columnheader"><span class="vh">Actions</span></span></div>
      ${rows.map((c) => `<div class="row" role="row" style="grid-template-columns:minmax(0,1fr) 300px 140px 200px">
        <div class="row-title" role="cell"><a class="od-truncate" href="#/open/${c.id}">${esc(c.title)}</a>${c.noteId ? `<span class="row-meta"><span class="badge badge-note">${ic('note')}Lesson note</span></span>` : ''}</div>
        <div role="cell">${ST.chips(c.subjects, 'sm')}</div>
        <div class="row-meta od-nowrap" role="cell">${ST.fmtDate(c.last)}</div>
        <div class="row-actions" role="cell"><a class="btn btn-quiet btn-sm" href="#/open/${c.id}" aria-label="Open ${esc(c.title)}">Open</a>
          ${c.archived ? `<button class="btn btn-secondary btn-sm" type="button" data-action="conv-restore" data-id="${c.id}" aria-label="Restore ${esc(c.title)}">${ic('restore', 'sm')}Restore</button>`
            : `<button class="btn btn-secondary btn-sm" type="button" data-action="conv-archive" data-id="${c.id}" aria-label="Archive ${esc(c.title)}">${ic('archive', 'sm')}Archive</button>`}</div></div>`).join('')}</div>`;
    return ST.shell({ nav: 'conversations', content: `<div class="page">
      <div class="page-head"><div><h1>Conversations</h1><p>Every question you've asked, newest first.</p></div><a class="btn btn-primary" href="#/chat-new">${ic('plus', 'sm')}New conversation</a></div>
      ${ST.tabsHtml(counts)}${all.length ? ST.filterBar({ count: rows.length, noun: 'conversation', subjects: subjOptions(all) }) : ''}
      <div id="list-panel" role="tabpanel" aria-labelledby="tab-${ST.L.tab}" ${all.length ? '' : 'style="margin-top:16px"'}>${list}</div></div>` });
  };
  ST.actions['conv-archive'] = (el) => { const c = ST.conv(el.dataset.id); c.archived = true; ST.render(); ST.toast('Conversation archived.', { undo: () => { c.archived = false; ST.render(); } }); };
  ST.actions['conv-restore'] = (el) => { const c = ST.conv(el.dataset.id); c.archived = false; ST.render(); ST.toast('Conversation restored.', { undo: () => { c.archived = true; ST.render(); } }); };

  /* ---------- §6.8 Notes ---------- */
  ST.notesView = () => {
    const all = ST.emptyDemo ? [] : S.notes;
    const inTab = all.filter((n) => (ST.L.tab === 'archived') === n.archived);
    const rows = ST.applyFilters(inTab, 'date').sort((a, b) => b.date.localeCompare(a.date));
    const counts = { active: all.filter((n) => !n.archived).length, archived: all.filter((n) => n.archived).length };
    let list;
    if (!all.length) list = ST.emptyState({ icon: 'note', title: 'No lesson notes yet', text: 'In any conversation, choose “Summarize lesson” to turn it into a note you can edit and revisit.', actions: `<a class="btn btn-primary" href="#/conversations-active">Go to conversations</a>` });
    else if (!rows.length && ST.hasFilters()) list = ST.emptyState({ icon: 'filter', title: 'No notes match these filters', text: 'Try another subject or a wider date range.', actions: `<button class="btn btn-secondary" type="button" data-action="f-clear">Clear filters</button>` });
    else if (!rows.length) list = ST.emptyState({ icon: 'archive', title: 'No archived notes', text: 'Notes you archive appear here. You can restore them at any time.' });
    else list = `<div class="list" role="table" aria-label="Lesson notes">
      <div class="list-head" role="row" style="grid-template-columns:minmax(0,1fr) 300px 140px 200px"><span role="columnheader">Note</span><span role="columnheader">Subjects</span><span role="columnheader">Date</span><span role="columnheader"><span class="vh">Actions</span></span></div>
      ${rows.map((n) => { const c = ST.conv(n.convId); return `<div class="row" role="row" style="grid-template-columns:minmax(0,1fr) 300px 140px 200px">
        <div class="row-title" role="cell"><span class="od-row"><a class="od-truncate" href="#/note/${n.id}">${esc(n.title)}</a>${n.edited ? `<span class="badge">${ic('pen')}Edited</span>` : ''}</span>
          ${c ? `<span class="row-meta">${ic('message', 'sm')}<span class="od-truncate">From <a href="#/open/${c.id}">${esc(c.title)}</a></span></span>` : ''}</div>
        <div role="cell">${ST.chips(n.subjects, 'sm')}</div>
        <div class="row-meta od-nowrap" role="cell">${ST.fmtDate(n.date)}</div>
        <div class="row-actions" role="cell"><a class="btn btn-quiet btn-sm" href="#/note/${n.id}" aria-label="Open ${esc(n.title)}">Open</a>
          ${n.archived ? `<button class="btn btn-secondary btn-sm" type="button" data-action="note-restore" data-id="${n.id}" aria-label="Restore ${esc(n.title)}">${ic('restore', 'sm')}Restore</button>`
            : `<button class="btn btn-secondary btn-sm" type="button" data-action="note-archive" data-id="${n.id}" aria-label="Archive ${esc(n.title)}">${ic('archive', 'sm')}Archive</button>`}</div></div>`; }).join('')}</div>`;
    return ST.shell({ nav: 'notes', content: `<div class="page">
      <div class="page-head"><div><h1>Notes</h1><p>Lesson notes made from your conversations. Edit them, discuss them, or archive the ones you're done with.</p></div></div>
      ${ST.tabsHtml(counts)}${all.length ? ST.filterBar({ count: rows.length, noun: 'note', subjects: subjOptions(all) }) : ''}
      <div id="list-panel" role="tabpanel" aria-labelledby="tab-${ST.L.tab}" ${all.length ? '' : 'style="margin-top:16px"'}>${list}</div></div>` });
  };
  ST.actions['note-archive'] = (el) => { const n = ST.note(el.dataset.id); n.archived = true; ST.render(); ST.toast('Note archived.', { undo: () => { n.archived = false; ST.render(); } }); };
  ST.actions['note-restore'] = (el) => { const n = ST.note(el.dataset.id); n.archived = false; ST.render(); ST.toast('Note restored.', { undo: () => { n.archived = true; ST.render(); } }); };

  /* Note editor */
  ST.ed = null;
  ST.openEditor = (id, mode = 'split') => { const n = ST.note(id); ST.ed = { id, mode, title: n.title, body: n.body, dirty: false }; };
  ST.editorView = () => {
    const e = ST.ed, n = ST.note(e.id), c = ST.conv(n.convId), ro = n.archived;
    const modes = [['write', 'Write'], ['preview', 'Preview'], ['split', 'Side by side']];
    const editor = `<section class="pane" aria-label="Markdown">${e.mode === 'split' ? '<div class="pane-label" aria-hidden="true">Markdown</div>' : ''}<label class="vh" for="md-ed">Note content (Markdown)</label>
      <textarea class="md-editor" id="md-ed" data-input="ed-body" data-fk="md-ed" ${ro ? 'readonly' : ''}>${esc(e.body)}</textarea></section>`;
    const preview = `<section class="pane" aria-label="Preview">${e.mode === 'split' ? '<div class="pane-label" aria-hidden="true">Preview</div>' : ''}<div class="md-preview" id="md-prev">${ST.md(e.body)}</div></section>`;
    const status = n.edited ? `${ic('pen', 'sm')}Edited ${esc(ST.fmtDate(n.editedAt || n.date))} · a new summary will ask before replacing it` : `${ic('check', 'sm')}Generated ${esc(ST.fmtDate(n.date))} · not edited`;
    return ST.shell({ nav: 'notes', content: `<div class="note-page">
      <header class="note-head"><a class="icon-btn" href="#/notes-active" aria-label="Back to notes">${ic('arrowLeft')}</a>
        <div class="nh-title"><label class="vh" for="ed-title">Note title</label><input class="title-input" id="ed-title" value="${esc(e.title)}" data-input="ed-title" data-fk="ed-title" ${ro ? 'readonly' : ''}>
          <div class="th-sub">${ST.chips(n.subjects, 'sm')}${n.edited ? `<span class="badge">${ic('pen')}Edited</span>` : ''}${ro ? `<span class="badge badge-archived">${ic('archive')}Archived</span>` : ''}
            ${c ? `<span class="th-sep" aria-hidden="true"></span><span class="od-row od-fill" style="--od-gap:6px">${ic('message', 'sm')}<span class="od-truncate">Source conversation: <a href="#/open/${c.id}">${esc(c.title)}</a></span></span>` : ''}</div></div>
        <div class="th-actions">${ro ? `<button class="btn btn-primary" type="button" data-action="ed-restore">${ic('restore', 'sm')}Restore</button>`
          : `<button class="btn btn-secondary" type="button" data-action="ed-archive">${ic('archive', 'sm')}Archive</button>
             <button class="btn btn-secondary" type="button" data-action="ed-discuss">${ic('message', 'sm')}Discuss this note</button>
             <button class="btn btn-primary" type="button" data-action="ed-save" data-fk="ed-save" ${e.dirty ? '' : 'disabled'}>Save</button>`}</div></header>
      <div class="note-toolbar">${ro ? `<div class="banner" style="margin:12px 0;flex:1">${ic('archive')}<div class="b-body"><strong>This note is archived.</strong><span>Restore it to edit or discuss it.</span></div></div>`
        : `<div class="seg" role="radiogroup" aria-label="Editor view">${modes.map(([k, l]) => `<button type="button" role="radio" aria-checked="${e.mode === k}" data-action="ed-mode" data-mode="${k}" data-fk="mode-${k}">${l}</button>`).join('')}</div>
           <span class="save-state" aria-live="polite">${e.dirty ? `${ic('pen', 'sm')}Unsaved changes` : status}</span>`}</div>
      <div class="note-body ${ro ? 'preview' : e.mode}">${ro ? preview : e.mode === 'write' ? editor : e.mode === 'preview' ? preview : editor + preview}</div></div>` });
  };
  function markDirty() {
    if (ST.ed.dirty) return; ST.ed.dirty = true;
    const s = document.querySelector('.save-state'); if (s) s.innerHTML = `${ic('pen', 'sm')}Unsaved changes`;
    const b = document.querySelector('[data-fk="ed-save"]'); if (b) b.disabled = false;
  }
  Object.assign(ST.actions, {
    'ed-body': (el) => { ST.ed.body = el.value; markDirty(); const p = document.getElementById('md-prev'); if (p) p.innerHTML = ST.md(el.value); },
    'ed-title': (el) => { ST.ed.title = el.value; markDirty(); },
    'ed-mode': (el) => { ST.ed.mode = el.dataset.mode; ST.render(); },
    'ed-save': () => { const n = ST.note(ST.ed.id); n.title = ST.ed.title; n.body = ST.ed.body; n.edited = true; n.editedAt = ST.TODAY + 'T11:40'; ST.ed.dirty = false; ST.render(); ST.toast('Note saved. It now shows as Edited.'); },
    'ed-archive': () => { const n = ST.note(ST.ed.id); n.archived = true; ST.render(); ST.toast('Note archived.', { undo: () => { n.archived = false; ST.render(); } }); },
    'ed-restore': () => { const n = ST.note(ST.ed.id); n.archived = false; ST.render(); ST.toast('Note restored.'); },
    'ed-discuss': () => { const n = ST.note(ST.ed.id); ST.pendingThread = ST.newThread({ subjects: n.subjects.slice(), fromNote: n.id }); ST.goto('chat-from-note'); }
  });
  document.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && ST.ed && document.getElementById('md-ed')) { e.preventDefault(); if (ST.ed.dirty) ST.actions['ed-save'](); } });
  ST.dynamicNote = (nid) => { const n = ST.note(nid) || ST.note('n1'); return { id: 'note/' + n.id, fixed: false, label: 'note · ' + n.id, desc: 'Lesson note opened from a link.', setup: () => ST.openEditor(n.id), view: ST.editorView }; };

  /* ---------- §6.10 Usage ---------- */
  ST.U = { key: 'last', dir: 'desc' };
  ST.usageView = () => {
    const convs = S.convs.map((c) => ({ ...c, total: c.tokens[0] + c.tokens[1] }));
    const k = ST.U.key, dir = ST.U.dir === 'asc' ? 1 : -1;
    const val = (r) => k === 'in' ? r.tokens[0] : k === 'out' ? r.tokens[1] : k === 'total' ? r.total : r[k];
    convs.sort((a, b) => { const x = val(a), y = val(b); return (typeof x === 'string' ? x.localeCompare(y) : x - y) * dir; });
    const docs = S.docs.filter((d) => d.tokens && (d.tokens[0] || d.dedup));
    const sum = (arr, i) => arr.reduce((s, r) => s + r.tokens[i], 0);
    const allIn = sum(convs, 0) + sum(docs, 0) + sum(ST.BACKGROUND, 0);
    const allOut = sum(convs, 1) + sum(docs, 1) + sum(ST.BACKGROUND, 1);
    const todayConvs = convs.filter((c) => c.last.startsWith(ST.TODAY)); const todayDocs = docs.filter((d) => d.uploaded.startsWith(ST.TODAY));
    const tIn = sum(todayConvs, 0) + sum(todayDocs, 0) + 3120, tOut = sum(todayConvs, 1) + sum(todayDocs, 1) + 486;
    const th = (key, label, num) => { const on = ST.U.key === key; return `<th scope="col" class="${num ? 'num' : ''}" aria-sort="${on ? (ST.U.dir === 'asc' ? 'ascending' : 'descending') : 'none'}"><button class="sort-btn" type="button" data-action="sort" data-key="${key}" data-fk="sort-${key}">${label}${on ? ic(ST.U.dir === 'asc' ? 'chevronUp' : 'chevronDown', 'sm') : ''}</button></th>`; };
    const stat = (label, v, unit) => `<div class="stat od-stat"><span class="s-label">${label}</span><span class="s-value">${ST.num(v)}</span><span class="s-unit">${unit}</span></div>`;
    return ST.shell({ nav: 'usage', content: `<div class="page">
      <div class="page-head"><div><h1>Usage</h1><p>Tokens used for your conversations, your documents and background work. Shown for your information only.</p></div></div>
      <div class="stats four">${stat('Input tokens', tIn, `Today · ${ST.TZ.short}`)}${stat('Output tokens', tOut, `Today · ${ST.TZ.short}`)}${stat('Input tokens', allIn, 'All time')}${stat('Output tokens', allOut, 'All time')}</div>
      <p class="legend-line" style="margin-top:12px">${ic('clock', 'sm')}“Today” runs from midnight to midnight in ${esc(ST.TZ.long)}, the time zone Smart Tutor uses for everyone.</p>

      <section class="usage-section" aria-labelledby="u-conv"><h2 id="u-conv">Conversations</h2>
        <div class="table-wrap"><table class="data"><caption class="vh">Tokens per conversation</caption>
          <thead><tr>${th('title', 'Conversation')}${th('last', 'Last activity')}${th('in', 'Input', true)}${th('out', 'Output', true)}${th('total', 'Total', true)}</tr></thead>
          <tbody>${convs.map((r) => `<tr><td style="max-width:420px"><span class="od-row"><a class="od-truncate" href="#/open/${r.id}">${esc(r.title)}</a>${r.archived ? '<span class="badge badge-archived">Archived</span>' : ''}</span></td>
            <td class="od-nowrap">${ST.fmtDate(r.last)}</td><td class="num">${ST.num(r.tokens[0])}</td><td class="num">${ST.num(r.tokens[1])}</td><td class="num">${ST.num(r.total)}</td></tr>`).join('')}</tbody>
          <tfoot><tr><td colspan="2">Total</td><td class="num">${ST.num(sum(convs, 0))}</td><td class="num">${ST.num(sum(convs, 1))}</td><td class="num">${ST.num(sum(convs, 0) + sum(convs, 1))}</td></tr></tfoot></table></div></section>

      <section class="usage-section" aria-labelledby="u-docs"><h2 id="u-docs">Document processing</h2>
        <p>Reading, summarizing and indexing the documents you uploaded. A document Smart Tutor had already processed costs nothing.</p>
        <div class="table-wrap"><table class="data"><caption class="vh">Tokens per document</caption>
          <thead><tr><th scope="col">Document</th><th scope="col">Uploaded</th><th scope="col" class="num">Input</th><th scope="col" class="num">Output</th></tr></thead>
          <tbody>${docs.map((d) => `<tr><td style="max-width:460px"><span class="od-row"><button class="doc-title od-truncate" style="font-size:14px" type="button" data-action="open-doc" data-id="${d.id}">${esc(d.title)}</button>${d.state !== 'ready' && !d.archived ? `<span class="badge">In progress</span>` : ''}</span></td>
            <td class="od-nowrap">${ST.fmtDate(d.uploaded, false)}</td>${d.dedup ? '<td class="num" colspan="2">Already processed · 0</td>' : `<td class="num">${ST.num(d.tokens[0])}</td><td class="num">${ST.num(d.tokens[1])}</td>`}</tr>`).join('')}</tbody>
          <tfoot><tr><td colspan="2">Total</td><td class="num">${ST.num(sum(docs, 0))}</td><td class="num">${ST.num(sum(docs, 1))}</td></tr></tfoot></table></div></section>

      <section class="usage-section" aria-labelledby="u-bg"><h2 id="u-bg">Background</h2><p>Work Smart Tutor does for you between conversations.</p>
        <div class="table-wrap"><table class="data"><caption class="vh">Background tokens</caption>
          <thead><tr><th scope="col">Work</th><th scope="col">What it covers</th><th scope="col" class="num">Input</th><th scope="col" class="num">Output</th></tr></thead>
          <tbody>${ST.BACKGROUND.map((b) => `<tr><td><strong>${b.label}</strong></td><td class="muted">${b.detail}</td><td class="num">${ST.num(b.tokens[0])}</td><td class="num">${ST.num(b.tokens[1])}</td></tr>`).join('')}</tbody></table></div></section>
    </div>` });
  };
  ST.actions.sort = (el) => { const key = el.dataset.key; if (ST.U.key === key) ST.U.dir = ST.U.dir === 'asc' ? 'desc' : 'asc'; else { ST.U.key = key; ST.U.dir = key === 'title' ? 'asc' : 'desc'; } ST.render(); };

  /* ---------- §6.11 Settings ---------- */
  ST.settingsView = () => {
    return ST.shell({ nav: 'settings', content: `<div class="page"><div class="page-head"><div><h1>Settings</h1></div></div>
      <div class="settings-grid">
        <section class="card" aria-labelledby="set-tz"><h2 id="set-tz">Time zone</h2>
          <dl class="facts"><dt>Time zone</dt><dd><span class="od-row" style="--od-gap:6px">${ic('lock', 'sm')}${esc(ST.TZ.long)}</span></dd></dl>
          <p class="helper">Smart Tutor uses one time zone for everyone. It sets “today” in Usage and the times shown when an upload or message limit ends. It can't be changed.</p></section>
        <section class="card" aria-labelledby="set-terms"><h2 id="set-terms">Terms of use</h2>
          <dl class="facts"><dt>Version</dt><dd>1.0 · effective 1 Oct 2026</dd><dt>Accepted</dt><dd>3 Oct 2026, 08:12</dd></dl>
          <div class="card-actions"><button class="btn btn-secondary" type="button" data-action="full-terms">${ic('doc', 'sm')}View the terms you accepted</button></div></section>
        <section class="card" aria-labelledby="set-app"><h2 id="set-app">Appearance</h2>
          <div class="seg" role="radiogroup" aria-labelledby="set-app">
            <button type="button" role="radio" aria-checked="${S.theme === 'light'}" data-action="set-theme" data-t="light" data-fk="th-light">${ic('sun', 'sm')}Light</button>
            <button type="button" role="radio" aria-checked="${S.theme === 'dark'}" data-action="set-theme" data-t="dark" data-fk="th-dark">${ic('moon', 'sm')}Dark</button></div>
          <div class="od-row" style="justify-content:space-between;border-top:1px solid var(--border);padding-top:16px">
            <div class="od-field"><span class="label" id="cit-l">Show citations</span><span class="helper">Show sources under every answer. You can also change this in any conversation.</span></div>
            <button class="switch od-fixed" type="button" role="switch" aria-checked="${S.citations}" aria-labelledby="cit-l" data-action="toggle-citations" data-fk="cit-set"><span class="track" aria-hidden="true"></span><span class="state" aria-hidden="true">${S.citations ? 'On' : 'Off'}</span></button></div></section>
      </div></div>` });
  };
  ST.actions['set-theme'] = (el) => { ST.setTheme(el.dataset.t); ST.render(); };
})();
