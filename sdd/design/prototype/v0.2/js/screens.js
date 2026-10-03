/* Smart Tutor — Release 1 screens: auth theme, subjects, lists, note editor, usage, settings. */
(function () {
  const ST = window.ST;
  const S = ST.S;
  const esc = ST.esc, ic = ST.ic;

  /* =========================================================
     5.2 Sign in / sign up — Keycloak theme
     ========================================================= */
  function kcAside() {
    return `<aside class="kc-aside">
      <a class="brand" href="#/auth-sign-in">${ST.logo()}<span class="word">Smart Tutor</span></a>
      <div>
        <blockquote>Answers you can trace back to the page.</blockquote>
        <ul class="kc-points">
          <li>${ic('book')}Answers come only from your subject's documents</li>
          <li>${ic('doc')}Every answer shows its source and page</li>
          <li>${ic('note')}Turn conversations into lesson notes</li>
        </ul>
      </div>
      <small>© 2026 Smart Tutor</small>
      <svg class="lines" viewBox="0 0 200 200" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1"><path d="M20 180V60c30-10 60-6 80 8v120c-20-14-50-18-80-8zM180 180V60c-30-10-60-6-80 8v120c20-14 50-18 80-8z"/><path d="M30 80c22-6 44-4 62 6M30 100c22-6 44-4 62 6M30 120c22-6 44-4 62 6M108 86c18-10 40-12 62-6M108 106c18-10 40-12 62-6"/></svg>
    </aside>`;
  }
  const kc = (card) => `<div class="kc">${kcAside()}<main class="kc-main" id="main-content" tabindex="-1"><div class="kc-card">${card}</div></main></div>`;

  ST.authSignIn = () => kc(`
    <div><h1>Sign in</h1><p class="kc-sub">Welcome back. Pick up where you left off.</p></div>
    <form class="od-stack" style="--od-gap:16px" novalidate onsubmit="return false">
      <div class="field"><label for="kc-user">Email or username</label>
        <input class="input" id="kc-user" type="email" autocomplete="username" value="mai.nguyen@example.com" data-autofocus></div>
      <div class="field"><label for="kc-pass">Password</label>
        <input class="input" id="kc-pass" type="password" autocomplete="current-password" value="studyhard2026"></div>
      <div class="kc-row"><label class="check"><input type="checkbox" checked> Remember me</label><a href="#/auth-sign-in">Forgot password?</a></div>
      <button class="btn btn-primary btn-lg" type="button" data-action="go" data-href="#/subjects-first-run">Sign in</button>
    </form>
    <p class="kc-alt">New to Smart Tutor? <a href="#/auth-sign-up">Create an account</a></p>`);

  ST.authSignUp = () => kc(`
    <div><h1>Create your account</h1><p class="kc-sub">Start asking questions in a minute.</p></div>
    <form class="od-stack" style="--od-gap:16px" novalidate onsubmit="return false">
      <div class="kc-names">
        <div class="field"><label for="kc-fn">First name</label><input class="input" id="kc-fn" autocomplete="given-name" value="Mai" data-autofocus></div>
        <div class="field"><label for="kc-ln">Last name</label><input class="input" id="kc-ln" autocomplete="family-name" value="Nguyen"></div>
      </div>
      <div class="field"><label for="kc-em">Email</label><input class="input" id="kc-em" type="email" autocomplete="email" value="mai.nguyen@example.com"></div>
      <div class="field"><label for="kc-pw">Password</label><input class="input" id="kc-pw" type="password" autocomplete="new-password" aria-describedby="kc-pw-h" value="studyhard2026"><span class="helper" id="kc-pw-h">At least 8 characters.</span></div>
      <div class="field"><label for="kc-pw2">Confirm password</label><input class="input" id="kc-pw2" type="password" autocomplete="new-password" value="studyhard"
        aria-invalid="true" aria-describedby="kc-pw2-e"><span class="field-error" id="kc-pw2-e">${ic('alertCircle', 'sm')}Passwords don't match. Type the same password in both fields.</span></div>
      <button class="btn btn-primary btn-lg" type="button" data-action="go" data-href="#/auth-verify-email">Create account</button>
    </form>
    <p class="kc-alt">Already have an account? <a href="#/auth-sign-in">Sign in</a></p>`);

  ST.authVerify = () => kc(`
    <span class="mail-art">${ic('mail', 'lg')}</span>
    <div><h1>Check your email</h1>
      <p class="kc-sub">We sent a verification link to <strong>mai.nguyen@example.com</strong>. Open it to finish creating your account.</p></div>
    <div class="od-stack" style="--od-gap:12px">
      <button class="btn btn-secondary btn-lg" type="button" data-action="resend" data-autofocus>${ic('retry', 'sm')}Resend email</button>
      <button class="btn btn-ghost" type="button" data-action="go" data-href="#/subjects-first-run">I've verified my email — continue</button>
    </div>
    <p class="kc-alt">Wrong address? <a href="#/auth-sign-up">Use a different email</a></p>`);
  ST.actions.resend = () => ST.toast('Verification email sent again.');

  /* =========================================================
     5.3 Subject enrollment
     ========================================================= */
  ST.fr = { picked: [] };
  ST.firstRunView = () => {
    const none = ST.fr.picked.length === 0;
    return `<div class="first-run">
      <header class="fr-top"><span class="brand" style="padding:0">${ST.logo()}<span class="word">Smart Tutor</span></span>
        <span class="od-row small muted"><span class="avatar" aria-hidden="true">${ST.USER.initials}</span>${esc(ST.USER.name)}</span></header>
      <main class="fr-main" id="main-content" tabindex="-1">
        <div><p class="steps">Welcome, ${esc(ST.USER.name.split(' ')[0])}</p>
          <h1>Choose the subjects you're studying</h1>
          <p class="lede">The tutor answers from each subject's documents. You can change your subjects at any time.</p></div>
        <fieldset style="border:0;margin:0;padding:0"><legend class="vh">Subjects</legend>
          <div class="subjects">${ST.SUBJECTS.map((s) => {
            const on = ST.fr.picked.includes(s.id);
            return `<label class="subject-card pick ${on ? 'on' : ''}">
              <span class="s-icon">${ST.subjectIcon(s.id, '')}</span>
              <span class="od-stack" style="--od-gap:0">
                <span class="od-row" style="justify-content:space-between"><span style="font-family:var(--font-display);font-size:24px;font-weight:600">${esc(s.name)}</span>
                  <span class="tick" aria-hidden="true">${ic('check', 'sm')}</span></span>
                <span class="s-desc">${esc(s.desc)}</span>
                <span class="s-meta"><span>${s.docs} documents</span></span>
              </span>
              <input type="checkbox" data-change="fr-pick" value="${esc(s.id)}" data-fk="fr-${s.icon}" ${on ? 'checked' : ''}>
            </label>`;
          }).join('')}</div></fieldset>
        <div class="fr-foot">
          <span class="helper" id="fr-help" aria-live="polite">${none ? 'Choose at least one subject to continue.' : `${ST.fr.picked.length} subject${ST.fr.picked.length > 1 ? 's' : ''} chosen.`}</span>
          <button class="btn btn-primary btn-lg" type="button" data-action="fr-continue" aria-describedby="fr-help" ${none ? 'disabled' : ''}>Continue${ic('arrowRight', 'sm')}</button>
        </div>
      </main></div>`;
  };
  ST.actions['fr-pick'] = (el) => {
    const v = el.value;
    ST.fr.picked = el.checked ? [...new Set([...ST.fr.picked, v])] : ST.fr.picked.filter((x) => x !== v);
    ST.render();
  };
  ST.actions['fr-continue'] = () => { S.enrolled = ST.fr.picked.slice(); ST.pendingKeepEnrolled = true; ST.goto('chat-empty'); };

  ST.subjectsView = () => ST.shell({ nav: 'subjects', content: `<div class="page">
    <div class="page-head"><div><h1>Subjects</h1><p>Enroll in the subjects you're studying. The tutor answers from each subject's documents.</p></div></div>
    <div class="subjects">${ST.SUBJECTS.map((s) => {
      const on = S.enrolled.includes(s.id);
      const count = S.convs.filter((c) => c.subject === s.id).length;
      return `<article class="subject-card ${on ? 'on' : ''}" aria-labelledby="sub-${s.icon}">
        <span class="s-icon">${ST.subjectIcon(s.id, '')}</span>
        <div>
          <div class="od-row" style="justify-content:space-between"><h2 id="sub-${s.icon}">${esc(s.name)}</h2>
            ${on ? `<span class="badge badge-note">${ic('check')}Enrolled</span>` : '<span class="badge">Not enrolled</span>'}</div>
          <p class="s-desc">${esc(s.desc)}</p>
          <p class="s-meta"><span>${s.docs} documents</span><span>${count} conversations</span></p>
          <div class="s-foot">
            ${on ? `<span class="small muted">Questions are answered from these documents.</span>
              <button class="btn btn-secondary" type="button" data-action="leave-subject" data-subject="${esc(s.id)}" data-fk="leave-${s.icon}">Leave subject</button>`
              : `<span class="small muted">${count ? 'Your conversations are read-only until you enroll again.' : 'Enroll to ask questions about this subject.'}</span>
              <button class="btn btn-primary" type="button" data-action="enroll-subject" data-subject="${esc(s.id)}" data-fk="leave-${s.icon}">Enroll</button>`}
          </div>
        </div></article>`;
    }).join('')}</div></div>` });

  ST.leaveDialog = (subject) => {
    ST.openDialog({
      title: `Leave ${esc(subject)}?`,
      body: `<p>Your <strong>${esc(subject)}</strong> conversations become read-only until you enroll again. Your lesson notes stay available, and nothing is deleted.</p>`,
      actions: [{ label: 'Stay enrolled', autofocus: true }, { label: `Leave ${esc(subject)}`, cls: 'btn-primary', onClick: () => {
        S.enrolled = S.enrolled.filter((x) => x !== subject);
        ST.render();
        ST.toast(`You left ${subject}.`, { undo: () => { S.enrolled.push(subject); ST.render(); } });
      } }]
    });
  };
  ST.actions['leave-subject'] = (el) => ST.leaveDialog(el.dataset.subject);
  ST.actions['enroll-subject'] = (el) => { S.enrolled.push(el.dataset.subject); ST.render(); ST.toast(`Enrolled in ${el.dataset.subject}.`); };

  /* =========================================================
     Shared list pattern (5.5 Conversations, 5.6 Notes, R2 lists)
     ========================================================= */
  ST.L = { tab: 'active', from: '', to: '', subject: 'all' };
  ST.resetList = (o = {}) => { ST.L = Object.assign({ tab: 'active', from: '', to: '', subject: 'all' }, o); };
  const hasFilters = () => ST.L.from || ST.L.to || ST.L.subject !== 'all';
  ST.applyFilters = (items, dateKey) => items.filter((it) => {
    const d = it[dateKey].slice(0, 10);
    if (ST.L.from && d < ST.L.from) return false;
    if (ST.L.to && d > ST.L.to) return false;
    if (ST.L.subject !== 'all' && it.subject !== ST.L.subject) return false;
    return true;
  });

  ST.filterBar = (count, noun) => `<div class="filter-bar" role="search" aria-label="Filter ${noun}">
    <div class="range">
      <div class="field"><label for="f-from">From</label><input class="input" type="date" id="f-from" value="${ST.L.from}" max="${ST.TODAY}" data-change="f-from" data-fk="f-from"></div>
      <span class="dash" aria-hidden="true">–</span>
      <div class="field"><label for="f-to">To</label><input class="input" type="date" id="f-to" value="${ST.L.to}" max="${ST.TODAY}" data-change="f-to" data-fk="f-to"></div>
    </div>
    <div class="field"><label for="f-subj">Subject</label>
      <select class="select" id="f-subj" data-change="f-subj" data-fk="f-subj">
        <option value="all" ${ST.L.subject === 'all' ? 'selected' : ''}>All subjects</option>
        ${ST.SUBJECTS.map((s) => `<option value="${esc(s.id)}" ${ST.L.subject === s.id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}
      </select></div>
    <div class="active-filters"><span aria-live="polite">${count} ${noun}${count === 1 ? '' : 's'}</span>
      ${hasFilters() ? `<button class="btn btn-ghost btn-sm" type="button" data-action="f-clear" data-fk="f-clear">${ic('x', 'sm')}Clear filters</button>` : ''}</div>
  </div>`;

  ST.tabsHtml = (counts) => `<div class="tabs" role="tablist" aria-label="Status">
    ${[['active', 'Active'], ['archived', 'Archived']].map(([k, l]) => `<button class="tab" role="tab" id="tab-${k}" aria-controls="list-panel" aria-selected="${ST.L.tab === k}" tabindex="${ST.L.tab === k ? 0 : -1}" data-action="tab" data-tab="${k}" data-fk="tab-${k}">${l}<span class="count">${counts[k]}</span></button>`).join('')}
  </div>`;

  Object.assign(ST.actions, {
    'f-from': (el) => { ST.L.from = el.value; ST.render(); },
    'f-to': (el) => { ST.L.to = el.value; ST.render(); },
    'f-subj': (el) => { ST.L.subject = el.value; ST.render(); },
    'f-clear': () => { ST.L.from = ''; ST.L.to = ''; ST.L.subject = 'all'; ST.render(); const f = document.getElementById('f-from'); if (f) f.focus(); },
    tab: (el) => { ST.L.tab = el.dataset.tab; ST.render(); }
  });
  document.addEventListener('keydown', (e) => {
    const tab = e.target.closest && e.target.closest('[role="tab"]');
    if (!tab || (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft')) return;
    const tabs = [...tab.parentElement.querySelectorAll('[role="tab"]')];
    const i = tabs.indexOf(tab);
    const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
    next.click();
    const n = document.getElementById(next.id); if (n) n.focus();
  });

  ST.emptyState = ({ icon, title, text, actions = '' }) => `<div class="empty">
    <span class="empty-icon">${ic(icon, 'lg')}</span><h2>${title}</h2><p>${text}</p>${actions ? `<div class="actions">${actions}</div>` : ''}</div>`;

  /* ---------- 5.5 Conversations ---------- */
  ST.conversationsView = () => {
    const all = ST.emptyDemo ? [] : S.convs;
    const inTab = all.filter((c) => (ST.L.tab === 'archived') === c.archived);
    const rows = ST.applyFilters(inTab, 'last').sort((a, b) => b.last.localeCompare(a.last));
    const counts = { active: ST.applyFilters(all.filter((c) => !c.archived), 'last').length, archived: ST.applyFilters(all.filter((c) => c.archived), 'last').length };
    let list;
    if (all.length === 0) {
      list = ST.emptyState({ icon: 'message', title: 'No conversations yet', text: 'Ask your first question and it will appear here. You can come back to any conversation later.', actions: `<a class="btn btn-primary" href="#/chat-empty">${ic('plus', 'sm')}Start a conversation</a>` });
    } else if (rows.length === 0 && hasFilters()) {
      list = ST.emptyState({ icon: 'filter', title: 'No conversations match these filters', text: 'Try a wider date range or another subject.', actions: `<button class="btn btn-secondary" type="button" data-action="f-clear">Clear filters</button>` });
    } else if (rows.length === 0) {
      list = ST.emptyState({ icon: 'archive', title: ST.L.tab === 'archived' ? 'No archived conversations' : 'No active conversations', text: ST.L.tab === 'archived' ? 'Conversations you archive appear here. You can restore them at any time.' : 'All your conversations are archived. Restore one or start a new conversation.' });
    } else {
      list = `<div class="list" role="table" aria-label="Conversations">
        <div class="list-head" role="row"><span role="columnheader">Conversation</span><span role="columnheader">Subject</span><span role="columnheader">Last activity</span><span role="columnheader"><span class="vh">Actions</span></span></div>
        ${rows.map((c) => `<div class="row" role="row">
          <div class="row-title" role="cell"><a class="od-truncate" href="#/open/${c.id}">${esc(c.title)}</a>
            ${c.noteId ? `<span class="row-meta"><span class="badge badge-note">${ic('note')}Lesson note</span></span>` : ''}</div>
          <div role="cell">${ST.subjectChip(c.subject)}</div>
          <div class="row-meta od-nowrap" role="cell">${ST.fmtDate(c.last)}</div>
          <div class="row-actions" role="cell">
            <a class="btn btn-quiet btn-sm" href="#/open/${c.id}" aria-label="Open ${esc(c.title)}">Open</a>
            ${c.archived
              ? `<button class="btn btn-secondary btn-sm" type="button" data-action="conv-restore" data-id="${c.id}" aria-label="Restore ${esc(c.title)}">${ic('restore', 'sm')}Restore</button>`
              : `<button class="btn btn-secondary btn-sm" type="button" data-action="conv-archive" data-id="${c.id}" aria-label="Archive ${esc(c.title)}">${ic('archive', 'sm')}Archive</button>`}
          </div></div>`).join('')}
      </div>`;
    }
    return ST.shell({ nav: 'conversations', content: `<div class="page">
      <div class="page-head"><div><h1>Conversations</h1><p>Every question you've asked, newest first. Archived conversations can be restored at any time.</p></div>
        <a class="btn btn-primary" href="#/chat-empty">${ic('plus', 'sm')}New conversation</a></div>
      ${ST.tabsHtml(counts)}
      ${all.length ? ST.filterBar(rows.length, 'conversation') : ''}
      <div id="list-panel" role="tabpanel" aria-labelledby="tab-${ST.L.tab}" ${all.length ? '' : 'style="margin-top:16px"'}>${list}</div>
    </div>` });
  };
  ST.actions['conv-archive'] = (el) => { const c = ST.conv(el.dataset.id); c.archived = true; ST.render(); ST.toast('Conversation archived.', { undo: () => { c.archived = false; ST.render(); } }); };
  ST.actions['conv-restore'] = (el) => { const c = ST.conv(el.dataset.id); c.archived = false; ST.render(); ST.toast('Conversation restored.', { undo: () => { c.archived = true; ST.render(); } }); };

  /* ---------- 5.6 Notes list ---------- */
  ST.notesView = () => {
    const all = ST.emptyDemo ? [] : S.notes;
    const inTab = all.filter((n) => (ST.L.tab === 'archived') === n.archived);
    const rows = ST.applyFilters(inTab, 'date').sort((a, b) => b.date.localeCompare(a.date));
    const counts = { active: ST.applyFilters(all.filter((n) => !n.archived), 'date').length, archived: ST.applyFilters(all.filter((n) => n.archived), 'date').length };
    let list;
    if (all.length === 0) {
      list = ST.emptyState({ icon: 'note', title: 'No lesson notes yet', text: 'In any conversation, choose “Summarize lesson” to turn it into a note you can edit and revisit.', actions: `<a class="btn btn-primary" href="#/conversations-active">Go to conversations</a>` });
    } else if (rows.length === 0 && hasFilters()) {
      list = ST.emptyState({ icon: 'filter', title: 'No notes match these filters', text: 'Try a wider date range or another subject.', actions: `<button class="btn btn-secondary" type="button" data-action="f-clear">Clear filters</button>` });
    } else if (rows.length === 0) {
      list = ST.emptyState({ icon: 'archive', title: 'No archived notes', text: 'Notes you archive appear here. You can restore them at any time.' });
    } else {
      list = `<div class="list" role="table" aria-label="Lesson notes">
        <div class="list-head" role="row"><span role="columnheader">Note</span><span role="columnheader">Subject</span><span role="columnheader">Date</span><span role="columnheader"><span class="vh">Actions</span></span></div>
        ${rows.map((n) => { const c = ST.conv(n.convId); return `<div class="row" role="row">
          <div class="row-title" role="cell"><a class="od-truncate" href="#/note/${n.id}">${esc(n.title)}</a>
            <span class="row-meta">${ic('message', 'sm')}<span class="od-truncate">From <a href="#/open/${c.id}">${esc(c.title)}</a></span></span></div>
          <div role="cell">${ST.subjectChip(n.subject)}</div>
          <div class="row-meta od-nowrap" role="cell">${ST.fmtDate(n.date)}</div>
          <div class="row-actions" role="cell">
            <a class="btn btn-quiet btn-sm" href="#/note/${n.id}" aria-label="Open ${esc(n.title)}">Open</a>
            ${n.archived
              ? `<button class="btn btn-secondary btn-sm" type="button" data-action="note-restore" data-id="${n.id}" aria-label="Restore ${esc(n.title)}">${ic('restore', 'sm')}Restore</button>`
              : `<button class="btn btn-secondary btn-sm" type="button" data-action="note-archive" data-id="${n.id}" aria-label="Archive ${esc(n.title)}">${ic('archive', 'sm')}Archive</button>`}
          </div></div>`; }).join('')}
      </div>`;
    }
    return ST.shell({ nav: 'notes', content: `<div class="page">
      <div class="page-head"><div><h1>Notes</h1><p>Lesson notes made from your conversations. Edit them, discuss them, or archive the ones you're done with.</p></div></div>
      ${ST.tabsHtml(counts)}
      ${all.length ? ST.filterBar(rows.length, 'note') : ''}
      <div id="list-panel" role="tabpanel" aria-labelledby="tab-${ST.L.tab}" ${all.length ? '' : 'style="margin-top:16px"'}>${list}</div>
    </div>` });
  };
  ST.actions['note-archive'] = (el) => { const n = ST.note(el.dataset.id); n.archived = true; ST.render(); ST.toast('Note archived.', { undo: () => { n.archived = false; ST.render(); } }); };
  ST.actions['note-restore'] = (el) => { const n = ST.note(el.dataset.id); n.archived = false; ST.render(); ST.toast('Note restored.', { undo: () => { n.archived = true; ST.render(); } }); };

  /* ---------- 5.6 Note view / editor ---------- */
  ST.ed = null;
  ST.openEditor = (id, mode = 'split') => {
    const n = ST.note(id);
    ST.ed = { id, mode, title: n.title, body: n.body, dirty: false, savedAt: ST.fmtDate(n.date) };
  };
  ST.editorView = () => {
    const e = ST.ed, n = ST.note(e.id), c = ST.conv(n.convId);
    const ro = n.archived;
    const modes = [['write', 'Write'], ['preview', 'Preview'], ['split', 'Side by side']];
    const editor = `<section class="pane" aria-label="Markdown">${e.mode === 'split' ? '<div class="pane-label" aria-hidden="true">Markdown</div>' : ''}
      <label class="vh" for="md-ed">Note content (Markdown)</label>
      <textarea class="md-editor" id="md-ed" data-input="ed-body" data-fk="md-ed" spellcheck="true" ${ro ? 'readonly' : ''}>${esc(e.body)}</textarea></section>`;
    const preview = `<section class="pane" aria-label="Preview">${e.mode === 'split' ? '<div class="pane-label" aria-hidden="true">Preview</div>' : ''}<div class="md-preview" id="md-prev">${ST.md(e.body)}</div></section>`;
    return ST.shell({ nav: 'notes', content: `<div class="note-page">
      <header class="note-head">
        <a class="icon-btn" href="#/notes-active" aria-label="Back to notes">${ic('arrowLeft')}</a>
        <div class="nh-title">
          <label class="vh" for="ed-title">Note title</label>
          <input class="title-input" id="ed-title" value="${esc(e.title)}" data-input="ed-title" data-fk="ed-title" ${ro ? 'readonly' : ''}>
          <div class="th-sub">${ST.subjectChip(n.subject)}${ro ? `<span class="badge badge-archived">${ic('archive')}Archived</span>` : ''}
            <span class="th-sep" aria-hidden="true"></span>
            <span class="od-row od-fill" style="--od-gap:6px">${ic('message', 'sm')}<span class="od-truncate">Source conversation: <a href="#/open/${c.id}">${esc(c.title)}</a></span></span></div>
        </div>
        <div class="th-actions">
          ${ro ? `<button class="btn btn-primary" type="button" data-action="ed-restore">${ic('restore', 'sm')}Restore</button>`
            : `<button class="btn btn-secondary" type="button" data-action="ed-archive" data-fk="ed-archive">${ic('archive', 'sm')}Archive</button>
               <button class="btn btn-secondary" type="button" data-action="ed-discuss" data-fk="ed-discuss" ${S.enrolled.includes(n.subject) ? '' : `disabled title="Enroll in ${esc(n.subject)} again to discuss this note"`}>${ic('message', 'sm')}Discuss this note</button>
               <button class="btn btn-primary" type="button" data-action="ed-save" data-fk="ed-save" ${e.dirty ? '' : 'disabled'}>Save</button>`}
        </div>
      </header>
      <div class="note-toolbar">
        ${ro ? `<div class="banner" style="margin:12px 0;flex:1">${ic('archive')}<div class="b-body"><strong>This note is archived.</strong><span>Restore it to edit or discuss it.</span></div></div>` : `
        <div class="seg" role="radiogroup" aria-label="Editor view">${modes.map(([k, l]) => `<button type="button" role="radio" aria-checked="${e.mode === k}" data-action="ed-mode" data-mode="${k}" data-fk="mode-${k}">${l}</button>`).join('')}</div>
        <span class="save-state" aria-live="polite">${e.dirty ? `${ic('pen', 'sm')}Unsaved changes` : `${ic('check', 'sm')}Saved · ${esc(e.savedAt)}`}</span>`}
      </div>
      <div class="note-body ${ro ? 'preview' : e.mode}">
        ${ro ? preview : e.mode === 'write' ? editor : e.mode === 'preview' ? preview : editor + preview}
      </div>
    </div>` });
  };
  /* Update save state in place so typing never re-renders the editor. */
  function markDirty() {
    if (ST.ed.dirty) return;
    ST.ed.dirty = true;
    const s = document.querySelector('.save-state'); if (s) s.innerHTML = `${ic('pen', 'sm')}Unsaved changes`;
    const b = document.querySelector('[data-fk="ed-save"]'); if (b) b.disabled = false;
  }
  Object.assign(ST.actions, {
    'ed-body': (el) => { ST.ed.body = el.value; markDirty(); const p = document.getElementById('md-prev'); if (p) p.innerHTML = ST.md(el.value); },
    'ed-title': (el) => { ST.ed.title = el.value; markDirty(); },
    'ed-mode': (el) => { ST.ed.mode = el.dataset.mode; ST.render(); },
    'ed-save': () => { const n = ST.note(ST.ed.id); n.title = ST.ed.title; n.body = ST.ed.body; ST.ed.dirty = false; ST.ed.savedAt = 'Today, 11:08'; ST.render(); ST.toast('Note saved.'); },
    'ed-archive': () => { const n = ST.note(ST.ed.id); n.archived = true; ST.render(); ST.toast('Note archived.', { undo: () => { n.archived = false; ST.render(); } }); },
    'ed-restore': () => { const n = ST.note(ST.ed.id); n.archived = false; ST.render(); ST.toast('Note restored.'); },
    'ed-discuss': () => { const n = ST.note(ST.ed.id); ST.pendingThread = ST.newThread({ subject: n.subject, fromNote: n.id, title: 'New conversation' }); ST.goto('chat-from-note'); }
  });
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && ST.ed && document.getElementById('md-ed')) { e.preventDefault(); if (ST.ed.dirty) ST.actions['ed-save'](); }
  });
  ST.dynamicNote = (nid) => {
    const n = ST.note(nid) || ST.note('n1');
    return { id: 'note/' + n.id, fixed: false, label: 'note · ' + n.id, desc: 'Lesson note opened from a link.', setup: () => ST.openEditor(n.id), view: ST.editorView };
  };

  /* =========================================================
     5.7 Usage
     ========================================================= */
  ST.U = { key: 'last', dir: 'desc' };
  ST.usageView = () => {
    const rows = S.convs.map((c) => ({ ...c, total: c.tokens[0] + c.tokens[1] }));
    const k = ST.U.key, d = ST.U.dir === 'asc' ? 1 : -1;
    const val = (r) => k === 'in' ? r.tokens[0] : k === 'out' ? r.tokens[1] : k === 'total' ? r.total : r[k];
    rows.sort((a, b) => { const x = val(a), y = val(b); return (typeof x === 'string' ? x.localeCompare(y) : x - y) * d; });
    const tin = rows.reduce((s, r) => s + r.tokens[0], 0), tout = rows.reduce((s, r) => s + r.tokens[1], 0);
    const th = (key, label, num) => {
      const sorted = ST.U.key === key;
      return `<th scope="col" class="${num ? 'num' : ''}" aria-sort="${sorted ? (ST.U.dir === 'asc' ? 'ascending' : 'descending') : 'none'}">
        <button class="sort-btn" type="button" data-action="sort" data-key="${key}" data-fk="sort-${key}">${label}${sorted ? ic(ST.U.dir === 'asc' ? 'chevronUp' : 'chevronDown', 'sm') : ''}</button></th>`;
    };
    return ST.shell({ nav: 'usage', content: `<div class="page">
      <div class="page-head"><div><h1>Usage</h1><p>Tokens used by your conversations. Usage is shown for your information only.</p></div></div>
      <div class="stats">
        <div class="stat od-stat"><span class="s-label">Input tokens</span><span class="s-value">${ST.num(tin)}</span><span class="s-unit">All time</span></div>
        <div class="stat od-stat"><span class="s-label">Output tokens</span><span class="s-value">${ST.num(tout)}</span><span class="s-unit">All time</span></div>
        <div class="stat od-stat"><span class="s-label">Conversations</span><span class="s-value">${rows.length}</span><span class="s-unit">Including archived</span></div>
      </div>
      <div class="banner banner-info" style="margin-bottom:16px">${ic('info')}<div class="b-body">Totals include background work, such as creating lesson notes and updating your learning records.</div></div>
      <div class="table-wrap"><table class="data">
        <caption class="vh">Tokens per conversation, sorted by ${({ title: 'conversation', subject: 'subject', last: 'last activity', in: 'input tokens', out: 'output tokens', total: 'total tokens' })[k]}</caption>
        <thead><tr>${th('title', 'Conversation')}${th('subject', 'Subject')}${th('last', 'Last activity')}${th('in', 'Input', true)}${th('out', 'Output', true)}${th('total', 'Total', true)}</tr></thead>
        <tbody>${rows.map((r) => `<tr>
          <td style="max-width:360px"><span class="od-row"><a class="od-truncate" href="#/open/${r.id}">${esc(r.title)}</a>${r.archived ? `<span class="badge badge-archived">archived</span>` : ''}</span></td>
          <td>${ST.subjectChip(r.subject)}</td>
          <td class="od-nowrap">${ST.fmtDate(r.last)}</td>
          <td class="num">${ST.num(r.tokens[0])}</td><td class="num">${ST.num(r.tokens[1])}</td><td class="num">${ST.num(r.total)}</td></tr>`).join('')}</tbody>
        <tfoot><tr><td colspan="3">Total</td><td class="num">${ST.num(tin)}</td><td class="num">${ST.num(tout)}</td><td class="num">${ST.num(tin + tout)}</td></tr></tfoot>
      </table></div>
    </div>` });
  };
  ST.actions.sort = (el) => {
    const key = el.dataset.key;
    if (ST.U.key === key) ST.U.dir = ST.U.dir === 'asc' ? 'desc' : 'asc';
    else { ST.U.key = key; ST.U.dir = ['title', 'subject'].includes(key) ? 'asc' : 'desc'; }
    ST.render();
  };

  /* =========================================================
     5.8 Settings
     ========================================================= */
  const ZONES = ['Asia/Ho_Chi_Minh', 'Asia/Singapore', 'Asia/Tokyo', 'Australia/Sydney', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Los_Angeles', 'UTC'];
  ST.settingsView = () => {
    let detected = 'UTC';
    try { detected = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch (e) {}
    if (!ST.tz) ST.tz = detected;
    const zones = [...new Set([detected, ...ZONES])];
    return ST.shell({ nav: 'settings', content: `<div class="page">
      <div class="page-head"><div><h1>Settings</h1></div></div>
      <div class="settings-grid">
        <section class="card" aria-labelledby="set-tz">
          <h2 id="set-tz">Time zone</h2>
          <div class="field"><label for="tz">Time zone</label>
            <select class="select" id="tz" data-change="tz" aria-describedby="tz-h" style="max-width:360px">${zones.map((z) => `<option ${z === ST.tz ? 'selected' : ''}>${esc(z)}</option>`).join('')}</select>
            <span class="helper" id="tz-h">${ST.tz === detected ? `Detected from your browser: ${esc(detected)}.` : `Your browser reports ${esc(detected)}.`} Used for dates and for daily and weekly reports.</span></div>
          <div class="card-actions"><button class="btn btn-primary" type="button" data-action="tz-save">Save time zone</button></div>
        </section>
        <section class="card" aria-labelledby="set-sub">
          <h2 id="set-sub">Subjects</h2>
          <p class="muted">You're enrolled in ${S.enrolled.length ? S.enrolled.map((s) => `<strong style="color:var(--text)">${esc(s)}</strong>`).join(' and ') : 'no subjects'}.</p>
          <div class="card-actions"><a class="btn btn-secondary" href="#/subjects-manage">${ic('book', 'sm')}Manage subjects</a></div>
        </section>
        <section class="card" aria-labelledby="set-app">
          <h2 id="set-app">Appearance</h2>
          <div class="seg" role="radiogroup" aria-labelledby="set-app">
            <button type="button" role="radio" aria-checked="${S.theme === 'light'}" data-action="set-theme" data-t="light" data-fk="th-light">${ic('sun', 'sm')}Light</button>
            <button type="button" role="radio" aria-checked="${S.theme === 'dark'}" data-action="set-theme" data-t="dark" data-fk="th-dark">${ic('moon', 'sm')}Dark</button>
          </div>
          <div class="od-row" style="justify-content:space-between;border-top:1px solid var(--border);padding-top:16px">
            <div class="od-field"><span class="label" id="cit-l">Show citations</span><span class="helper">Show sources under every answer. You can also change this in any conversation.</span></div>
            <button class="switch od-fixed" type="button" role="switch" aria-checked="${S.citations}" aria-labelledby="cit-l" data-action="toggle-citations" data-fk="cit-set"><span class="track" aria-hidden="true"></span><span class="state" aria-hidden="true">${S.citations ? 'On' : 'Off'}</span></button>
          </div>
        </section>
      </div>
    </div>` });
  };
  ST.actions.tz = (el) => { ST.tz = el.value; ST.render(); };
  ST.actions['tz-save'] = () => ST.toast(`Time zone saved: ${ST.tz}.`);
  ST.actions['set-theme'] = (el) => { ST.setTheme(el.dataset.t); ST.render(); };
})();
