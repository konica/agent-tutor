/* Smart Tutor v0.10 (P1–P6) — chat (§6.6): no subjects in conversations (K1); every question is answered from all
   ready documents. Documents used (K2) and citations open the document viewer (K3, js/viewer.js). */
(function () {
  const ST = window.ST;
  const S = ST.S;
  const esc = ST.esc, ic = ST.ic;

  /* ---------- answer choice (simulated) ---------- */
  const OFF_TOPIC = /laptop|buy|price|weather|recipe|movie|restaurant/i;
  ST.pickAnswer = (q) => {
    if (/\breact\b/i.test(q) && !/retriev|hallucinat/i.test(q)) return 'react';
    if (/hallucinat|retriev.*loop/i.test(q)) return 'rag_loop';
    if (/long documents|long input|handle long/i.test(q)) return 'long_docs';
    if (/attention/i.test(q)) return 'attention';
    if (/\bppo\b|clip|polic(y|ies)/i.test(q)) return 'ppo';
    if (/chain/i.test(q)) return 'cot';
    if (/dense|bm25/i.test(q)) return 'rag_dense';
    if (/agent|tool/i.test(q)) return 'generic_agents';
    if (/retriev|\brag\b/i.test(q)) return 'generic_rag';
    if (/reward|reinforcement/i.test(q)) return 'generic_rl';
    return 'generic_llm';
  };

  /* ---------- thread model ---------- */
  let mid = 0;
  const M = (o) => Object.assign({ id: 'm' + (++mid) }, o);
  ST.M = M;
  ST.newThread = (o = {}) => Object.assign({
    convId: null, title: 'New conversation', fromNote: null, noteId: null, readOnly: null,
    messages: [], tokens: [0, 0], streaming: null, summarizing: false, summaryHold: false, summaryDone: false,
    rateLimit: 0, draft: ''
  }, o);
  const answerMsg = (key, extra = {}) => { const a = ST.ANSWERS[key]; return M(Object.assign({ role: 'tutor', kind: 'answer', key, text: a.text, quote: a.quote || null, cites: ST.clone(a.cites), fb: null }, extra)); };
  ST.answerMsg = answerMsg;

  /* P5 (US-4c): the conversation's Documents list and the "Only search these documents" switch. */
  ST.convDocList = (t) => { if (!t) return []; const ids = ST.docsUsed(t).filter((id) => !(t.removed || []).includes(id)); (t.added || []).forEach((id) => { if (!ids.includes(id)) ids.push(id); }); return ids; };
  ST.scopeOn = (t) => !!(t && t.scopeOn && ST.convDocList(t).length);
  /* K2: documents used, in order of first use; declines add nothing. */
  ST.docsUsed = (t) => { const ids = []; (t ? t.messages : []).forEach((m) => { if (m.kind === 'answer' && !m.streaming) m.cites.forEach((c) => { if (!ids.includes(c.doc)) ids.push(c.doc); }); }); return ids; };

  /* J2/J3 script (§9): returns the cv1 thread after `upTo` learner turns. */
  ST.J2 = [
    { q: 'How does ReAct combine reasoning and acting?', a: 'react', tokens: [3920, 412] },
    { q: 'How does retrieval reduce hallucination in that loop?', a: 'rag_loop', tokens: [8110, 1530] },
    { q: 'How does PPO clip the policy update?', a: 'ppo', tokens: [12480, 3215] }
  ];
  ST.j2Thread = (upTo, o = {}) => {
    const t = ST.newThread({ convId: 'cv1', title: ST.J2[0].q });
    ST.J2.slice(0, upTo).forEach((s) => { t.messages.push(M({ role: 'user', text: s.q }), answerMsg(s.a)); t.tokens = s.tokens.slice(); });
    return Object.assign(t, o);
  };
  ST.threadFromConv = (cid, o = {}) => {
    const c = ST.conv(cid);
    if (cid === 'cv1') return ST.j2Thread(3, Object.assign({ noteId: c.noteId, readOnly: c.archived ? 'archived' : null }, o));
    const t = ST.newThread({ convId: c.id, title: c.title, noteId: c.noteId, tokens: c.tokens.slice(), readOnly: c.archived ? 'archived' : null });
    t.messages.push(M({ role: 'user', text: c.title }), answerMsg(c.answers[0]));
    return Object.assign(t, o);
  };

  /* ---------- rendering ---------- */
  const T = () => S.thread;
  const noActiveDocs = () => !S.docs.some((d) => d.state === 'ready' && !d.archived && !d.deleted);
  const hasNoDocs = () => !S.docs.some((d) => !d.deleted);

  /* M6: Sources as one line of 22px chips ("ReAct · p. 3"), full title in the tooltip and accessible name;
     Helpful / Not helpful as two 28px icon buttons with tooltips at the end of that line. */
  ST.shortTitle = (t) => { const c = t.split(':')[0]; if (c.length <= 30) return c; const w = c.split(' '); let o = ''; for (const x of w) { if ((o + ' ' + x).trim().length > 28) break; o = (o + ' ' + x).trim(); } return o + '…'; };
  function citeChips(m) {
    if (!S.citations || !m.cites.length) return '';
    return m.cites.map((c, i) => {
      const d = ST.doc(c.doc);
      if (!d || d.deleted) return `<span class="cite cite-deleted" role="listitem" data-od-id="cite-deleted">${ic('doc', 'sm')}Deleted document</span>`;
      const pg = c.page ? 'p. ' + c.page : 'page unavailable';
      const on = ST.VW && ST.VW.mode === 'pane' && ST.VW.chip && ST.VW.chip.mid === m.id && ST.VW.chip.ci === i;
      return `<span role="listitem"><button class="cite ${on ? 'is-open' : ''}" type="button" data-action="cite" data-mid="${m.id}" data-ci="${i}" data-fk="cite-${m.id}-${i}" ${on ? 'aria-current="true"' : ''} aria-label="${esc(d.title)}, ${pg}${d.archived ? ', archived' : ''}. ${on ? 'Shown beside the conversation' : 'Open beside the conversation'}" data-tip="${esc(d.title)}, ${pg}">
        ${ic('doc', 'sm')}<span class="doc-name">${esc(ST.shortTitle(d.title))}</span><span class="cite-page">· ${pg}</span>${d.archived ? `<span class="cite-arch">${ic('archive', 'sm')}Archived</span>` : ''}</button></span>`;
    }).join('');
  }
  function sourcesLine(m) {
    const chips = citeChips(m);
    const fb = `<span class="fb-group" role="group" aria-label="Rate this answer">
      <button class="fb-icon" type="button" data-action="fb-up" data-mid="${m.id}" data-fk="up-${m.id}" aria-pressed="${m.fb === 'up'}" aria-label="Helpful" data-tip="Helpful">${ic('thumb', 'sm')}</button>
      <button class="fb-icon" type="button" data-action="fb-down" data-mid="${m.id}" data-fk="down-${m.id}" aria-pressed="${m.fb === 'down'}" aria-label="Not helpful" data-tip="Not helpful">${ic('thumb', 'sm flip-y')}</button></span>`;
    const thanks = m.fb === 'up' ? '<span class="fb-thanks">Thanks — glad it helped.</span>' : m.fb === 'down' && m.reasonSent ? '<span class="fb-thanks">Thanks — your feedback helps improve answers.</span>' : '';
    return `<div class="sources-line" data-od-id="sources-line">${chips ? `<span class="cites-label" id="cl-${m.id}">Sources</span><span class="cite-list" role="list" aria-labelledby="cl-${m.id}">${chips}</span>` : ''}${fb}</div>${thanks ? `<div class="fb-thanks-row">${thanks}</div>` : ''}`;
  }
  function reasonForm(m) {
    if (!(m.fb === 'down' && m.reasonOpen)) return '';
    const reasons = ['Not accurate', "Didn't answer my question", "Citation doesn't match", 'Hard to follow'];
    return `<form class="reason-form" onsubmit="return false"><fieldset><legend>What could be better? <span class="muted" style="font-weight:400">Optional</span></legend>
        <div class="reason-opts">${reasons.map((r, i) => `<label><input type="radio" name="reason-${m.id}" value="${esc(r)}" ${m.reason === r ? 'checked' : ''} data-change="fb-reason" data-mid="${m.id}" data-fk="r-${m.id}-${i}">${esc(r)}</label>`).join('')}</div></fieldset>
        <div class="field"><label for="rt-${m.id}">Anything else? <span class="muted" style="font-weight:400">Optional</span></label><textarea class="textarea" id="rt-${m.id}" rows="2" data-input="fb-text" data-mid="${m.id}">${esc(m.reasonText || '')}</textarea></div>
        <div class="rf-actions"><button class="btn btn-quiet btn-sm" type="button" data-action="fb-skip" data-mid="${m.id}">Skip</button><button class="btn btn-primary btn-sm" type="button" data-action="fb-send" data-mid="${m.id}">Send feedback</button></div></form>`;
  }
  const tutorWrap = (m, inner, busy = false) => `<article class="msg-tutor msg-enter" id="m-${m.id}" aria-label="Smart Tutor">${ST.logo('logo')}
    <div class="msg-body" ${busy ? 'aria-busy="true"' : ''}><span class="msg-name">Smart Tutor</span>${inner}</div></article>`;
  const quoteHtml = (q) => { const d = ST.doc(q.doc); if (!d || d.deleted) return ''; return `<figure class="excerpt"><blockquote>“${esc(q.text)}”</blockquote><figcaption>${ic('quote', 'sm')}Quoted from <span style="text-transform:none;letter-spacing:0"><em>${esc(d.title)}</em>, p. ${q.page}</span></figcaption></figure>`; };

  function msgHtml(m) {
    if (m.role === 'user') return `<div class="msg-user msg-enter"><span class="vh">You asked: </span>${esc(m.text)}</div>`;
    if (m.kind === 'answer') {
      if (m.streaming) return tutorWrap(m, `<div class="stream" id="stream-${m.id}">${ST.mdParas(m.partial || '')}<span class="cursor" aria-hidden="true"></span></div>`, true);
      const text = m.stopped ? m.partial : m.text;
      return tutorWrap(m, `${ST.mdParas(text)}${m.quote && !m.stopped ? quoteHtml(m.quote) : ''}
        ${m.stopped ? `<p class="small muted">${ic('stop', 'sm')} You stopped this answer.</p>` : ''}${sourcesLine(m)}${reasonForm(m)}`);
    }
    if (m.kind === 'decline' && m.limited) {
      return tutorWrap(m, `<div class="tutor-card decline" data-od-id="decline-limited">
        <p>These documents don't cover this.</p>
        <p class="small muted">This conversation only searches ${ST.plural(m.count || ST.convDocList(T()).length, 'document')}.</p>
        <div class="tc-actions"><button class="btn btn-secondary" type="button" data-action="docs-add" data-fk="decline-add">${ic('plus', 'sm')}Add documents</button>
          <button class="btn btn-secondary" type="button" data-action="search-all" data-mid="${m.id}" data-fk="decline-all">${ic('search', 'sm')}Search all my documents</button></div></div>`);
    }
    if (m.kind === 'decline') {
      return tutorWrap(m, `<div class="tutor-card decline">
        <p>Your documents don't cover this. I answer only from your Library, and none of your documents is about ${esc(m.topic || 'this topic')}.</p>
        <p class="small muted">To continue, upload a document on this topic.</p>
        <div class="tc-actions"><button class="btn btn-secondary" type="button" data-action="decline-upload" data-fk="decline-upload">${ic('upload', 'sm')}Upload a document</button></div></div>`);
    }
    if (m.kind === 'nodocs') {
      return tutorWrap(m, `<div class="tutor-card decline">
        <p>None of your documents can be used right now: they are all archived or deleted.</p>
        <p class="small muted">Upload a document to get an answer. Your earlier answers stay readable.</p>
        <div class="tc-actions"><button class="btn btn-secondary" type="button" data-action="decline-upload" data-fk="nodocs-upload">${ic('upload', 'sm')}Upload</button></div></div>`);
    }
    if (m.kind === 'error') {
      return tutorWrap(m, `<div class="tutor-card error" role="alert"><p class="tc-head">${ic('alertCircle', 'sm')}This answer didn't come through.</p>
        <p class="small muted">Something went wrong while answering. Your question is saved.</p>
        <div class="tc-actions"><button class="btn btn-secondary" type="button" data-action="retry" data-mid="${m.id}" data-fk="retry">${ic('retry', 'sm')}Retry</button></div></div>`);
    }
    return '';
  }

  /* P1: one 40px header row: panel toggle, title, overflow. Documents used and Summarize lesson live in the panel. */
  /* P6: header = panel toggle (panel-left icon), editable title. No overflow menu: Show citations and Archive live in the panel. */
  function headerHtml() {
    const t = T();
    const label = S.chatPanel ? 'Hide panel' : 'Show panel';
    const editable = t.readOnly !== 'archived';
    let title;
    if (t.titleEdit) {
      const empty = !(t.titleDraft || '').trim();
      title = `<div class="th-title-edit" data-od-id="thread-title-edit"><label class="vh" for="th-title-input">Conversation title</label>
        <input class="th-title-input" id="th-title-input" type="text" maxlength="120" value="${esc(t.titleDraft)}" data-input="title-draft" data-fk="title-input" aria-keyshortcuts="Enter Escape" title="Enter to save · Esc to cancel" ${empty ? 'aria-invalid="true" aria-describedby="th-title-err"' : ''}>
        ${empty ? `<p class="th-title-err" id="th-title-err" role="alert">${ic('alertCircle', 'sm')}Enter a title</p>` : ''}</div>
        <span class="th-title-hint" aria-hidden="true">Enter to save · Esc to cancel</span>`;
    } else if (editable) {
      title = `<h1 class="th-h1"><button class="th-title-btn" type="button" data-action="title-edit" data-fk="title-btn" title="${esc(t.title)}" aria-label="${esc(t.title)}. Edit title" data-od-id="thread-title"><span class="th-title-text">${esc(t.title)}</span>${ic('pen', 'sm th-pen')}</button></h1>`;
    } else {
      title = `<h1 class="th-h1 od-truncate" title="${esc(t.title)}">${esc(t.title)}</h1>`;
    }
    return `<header class="thread-head" data-od-id="thread-header">
      <button class="icon-btn sm" type="button" data-action="chat-panel" data-fk="chat-panel" aria-expanded="${!!S.chatPanel}" aria-controls="conv-panel" aria-label="${label}" data-tip="${label}" data-od-id="chat-panel-toggle">${ic('panelLeft')}</button>
      ${title}
    </header>`;
  }

  /* P6: inline title editing: Enter or clicking away saves, Esc cancels, 1–120 characters. */
  const saveTitle = (keepFocus) => {
    const t = T(); if (!t || !t.titleEdit) return;
    const v = (t.titleDraft || '').trim().slice(0, 120);
    t.titleEdit = false;
    if (v) { t.title = v; const c = t.convId && ST.conv(t.convId); if (c) c.title = v; ST.announce('Title saved.'); }
    ST.render();
    if (keepFocus) { const b = document.querySelector('[data-fk="title-btn"]'); if (b) b.focus(); }
  };
  const cancelTitle = () => { const t = T(); t.titleEdit = false; ST.render(); const b = document.querySelector('[data-fk="title-btn"]'); if (b) b.focus(); };
  ST.startTitleEdit = () => {
    const t = T(); if (!t || t.readOnly === 'archived') return;
    t.titleEdit = true; t.titleDraft = t.title; ST.render();
    const i = document.getElementById('th-title-input'); if (i) { i.focus(); if (i.select) i.select(); }
  };
  document.addEventListener('keydown', (e) => {
    if (e.target.id !== 'th-title-input') return;
    if (e.key === 'Enter') { e.preventDefault(); if ((T().titleDraft || '').trim()) saveTitle(true); }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cancelTitle(); }
  }, true);
  document.addEventListener('focusout', (e) => {
    if (e.target.id !== 'th-title-input') return;
    setTimeout(() => { const t = T(); const a = document.activeElement; if (!t || !t.titleEdit || (a && (a.id === 'th-title-input' || a.id === 'main-content'))) return; if ((t.titleDraft || '').trim()) saveTitle(false); else cancelTitle(); }, 0);
  });

  /* P1: conversation panel (260px): Documents used, Lesson Note, Actions. */
  function panelHtml() {
    const t = T();
    const docs = ST.convDocList(t).map((id) => ST.doc(id)).filter(Boolean);
    const anyDeleted = docs.some((d) => d.deleted);
    const shown = ST.VW && ST.VW.mode === 'pane' ? ST.VW.id : null;
    const used = ST.docsUsed(t);
    const row = (d) => {
      const inner = `<span class="cp-icon">${ic(d.book ? 'book' : 'doc', 'sm')}</span><span class="cp-title">${esc(d.title)}</span><span class="cp-pages">${d.pages} p.</span>${d.deleted ? `<span class="badge badge-deleted">${ic('x')}Deleted</span>` : d.archived ? `<span class="badge badge-archived">${ic('archive')}Archived</span>` : (t.added || []).includes(d.id) && !used.includes(d.id) ? '<span class="badge badge-note">Added</span>' : ''}`;
      const rm = `<button class="cp-x" type="button" data-action="cp-remove" data-id="${d.id}" data-fk="cpx-${d.id}" aria-label="Remove ${esc(d.title)} from this conversation" data-tip="Remove from this conversation">${ic('x', 'sm')}</button>`;
      return d.deleted
        ? `<li class="cp-li"><span class="cp-row is-deleted" title="${esc(d.title)}" data-od-id="documents-used-${d.id}"><span class="vh">Deleted: </span>${inner}</span>${rm}</li>`
        : `<li class="cp-li">${rm}<button class="cp-row ${shown === d.id ? 'is-open' : ''}" type="button" data-action="cp-open" data-id="${d.id}" data-fk="cp-${d.id}" ${shown === d.id ? 'aria-current="true"' : ''} title="${esc(d.title)}" aria-label="${esc(d.title)}, ${d.pages} pages${d.archived ? ', archived' : ''}. Open beside the conversation at page 1" data-od-id="documents-used-${d.id}">${inner}</button></li>`;
    };
    const note = t.noteId ? ST.note(t.noteId) : null;
    const hasAnswer = t.messages.some((m) => m.kind === 'answer' && !m.streaming);
    const canSumm = hasAnswer && t.readOnly !== 'archived';
    const summBtn = t.summarizing
      ? `<button class="btn btn-secondary btn-sm" type="button" disabled data-fk="summ"><span class="spinner" aria-hidden="true"></span>Summarizing…</button>`
      : `<button class="btn btn-secondary btn-sm" type="button" data-action="summarize" data-fk="summ" ${t.streaming || t.rateLimit ? 'disabled' : ''}>${ic('note', 'sm')}${note ? 'Update lesson note' : 'Summarize lesson'}</button>`;
    return `<aside class="conv-panel" id="conv-panel" aria-label="Conversation panel" data-od-id="conversation-panel">
      <section class="cp-sec" aria-labelledby="cp-docs-h" data-od-id="documents-used-panel">
        <h2 class="cp-h" id="cp-docs-h">Documents <span class="cp-count">${docs.length}</span></h2>
        ${docs.length ? `<ol class="cp-list">${docs.map(row).join('')}</ol>${anyDeleted ? `<p class="cp-note">${ic('info', 'sm')}Deleted documents can't be opened.</p>` : ''}`
          : `<p class="cp-empty">Documents used to answer will appear here.</p>`}
        <div class="cp-btns"><button class="btn btn-quiet btn-sm cp-add" type="button" data-action="docs-add" data-fk="docs-add" aria-haspopup="dialog" data-od-id="panel-add-documents">${ic('plus', 'sm')}Add documents</button></div>
        <button class="switch cp-switch" type="button" role="switch" aria-checked="${ST.scopeOn(t)}" data-action="scope-toggle" data-fk="scope-switch" ${docs.length ? '' : 'disabled aria-describedby="scope-h"'} data-od-id="panel-scope-switch"><span class="track" aria-hidden="true"></span>Only search these documents</button>
        ${docs.length ? '' : '<p class="cp-empty" id="scope-h">Add documents to limit the search.</p>'}
      </section>
      <section class="cp-sec" aria-labelledby="cp-note-h" data-od-id="panel-lesson-note">
        <h2 class="cp-h" id="cp-note-h">Lesson Note</h2>
        ${note ? `<a class="cp-note-link" href="#/note/${note.id}" title="${esc(note.title)}">${ic('note', 'sm')}<span class="od-truncate">${esc(note.title)}</span></a>
          <div class="cp-btns"><a class="btn btn-secondary btn-sm" href="#/note/${note.id}">Open note</a>${canSumm ? summBtn : ''}</div>`
          : canSumm ? `<p class="cp-empty">Turn this conversation into a note you can edit.</p><div class="cp-btns">${summBtn}</div>` : `<p class="cp-empty">After the first answer you can summarize this conversation into a note.</p>`}
      </section>
      <section class="cp-sec" aria-labelledby="cp-act-h" data-od-id="panel-actions">
        <h2 class="cp-h" id="cp-act-h">Actions</h2>
        <button class="switch cp-switch" type="button" role="switch" aria-checked="${S.citations}" data-action="toggle-citations" data-fk="cit-switch"><span class="track" aria-hidden="true"></span>Show citations</button>
        ${t.convId ? (t.readOnly === 'archived' ? `<button class="btn btn-quiet btn-sm cp-act" type="button" data-action="restore-thread">${ic('restore', 'sm')}Restore conversation</button>` : `<button class="btn btn-quiet btn-sm cp-act" type="button" data-action="archive-thread">${ic('archive', 'sm')}Archive conversation</button>`) : ''}
      </section>
    </aside>`;
  }
  function summaryCard() {
    const t = T();
    if (t.summarizing) return `<div class="tutor-card" role="status"><p class="tc-head"><span class="spinner" aria-hidden="true"></span>Summarizing this lesson into a note…</p>
      <div class="progress" aria-hidden="true"><span></span></div><p class="small muted">This usually takes a few seconds. You can keep reading.</p></div>`;
    if (t.summaryDone && t.noteId) { const n = ST.note(t.noteId); return `<div class="banner banner-success" role="status">${ic('checkCircle')}<div class="b-body"><strong>${t.summaryDone === 'updated' ? 'Lesson note updated' : 'Lesson note saved'}</strong><span>${esc(n.title)}</span></div><a class="btn btn-secondary btn-sm" href="#/note/${n.id}">Open note</a></div>`; }
    return '';
  }

  function composerHtml() {
    const t = T();
    let banner = '', disabled = false, placeholder = 'Ask about your documents…';
    if (t.readOnly === 'archived') {
      disabled = true; placeholder = 'Archived conversation';
      banner = `<div class="banner">${ic('archive')}<div class="b-body"><strong>This conversation is archived.</strong><span>Restore it to keep asking.</span></div><button class="btn btn-primary btn-sm" type="button" data-action="restore-thread">${ic('restore', 'sm')}Restore</button></div>`;
    } else if (t.rateLimit > 0) {
      disabled = true; placeholder = 'Sending is paused for a moment';
      banner = `<div class="banner banner-warn">${ic('clock')}<div class="b-body"><strong>You've sent 20 messages in the last minute.</strong><span>You can send again at 11:25 (${ST.TZ.short}), in <span id="rl-count" class="mono">${t.rateLimit}</span> seconds.</span><span class="b-variant">If it's the daily limit (500 per day): You can send again at 00:00 (${ST.TZ.short}).</span></div></div>`;
    }
    const processing = ST.stillProcessing();
    T().hint = !disabled && processing ? `${ST.plural(processing, 'document')} ${processing === 1 ? 'is' : 'are'} still processing and can't be used yet.` : '';
    const btn = t.streaming
      ? `<button class="btn btn-secondary" type="button" data-action="stop" data-fk="stop">${ic('stop', 'sm')}Stop</button>`
      : `<button class="btn btn-primary send" type="button" data-action="send" data-fk="send" aria-label="Send question" ${disabled ? 'disabled' : ''}>${ic('send')}</button>`;
    const scope = ST.scopeOn(t) && !disabled ? `<p class="scope-line" data-od-id="composer-scope-line">${ic('filter', 'sm')}Searching ${ST.plural(ST.convDocList(t).length, 'document')} <button class="link-btn" type="button" data-action="scope-change" data-fk="scope-change">Change</button></p>` : '';
    return `<div class="composer-wrap"><div class="composer-inner">${banner}${scope}
      <div class="composer ${disabled ? 'disabled' : ''}"><label class="vh" for="composer-input">Ask the tutor</label>
        <textarea id="composer-input" rows="1" placeholder="${placeholder}" data-input="draft" data-fk="composer" ${disabled ? 'disabled' : ''} ${!t.messages.length && !disabled ? 'data-autofocus' : ''}>${esc(t.draft)}</textarea>${btn}</div></div></div>`;
  }
  const statusHtml = () => { const t = T(); return `<div class="status-wrap"><div class="status-line">${t.hint ? `<span class="input-hint" title="${esc(t.hint)}">${ic('clock', 'sm')}<span class="sl-text">${esc(t.hint)}</span></span>` : '<span class="sl-keys" title="Enter to send · Shift + Enter for a new line"><span class="sl-text">Enter to send · Shift + Enter for a new line</span></span>'}<span class="tokens mono" id="token-line" aria-label="Tokens: ${ST.num(t.tokens[0])} in, ${ST.num(t.tokens[1])} out"><span class="tk-label" aria-hidden="true">Tokens: </span><span aria-hidden="true">${ST.num(t.tokens[0])} in · ${ST.num(t.tokens[1])} out</span></span></div></div>`; };

  function emptyHtml() {
    const from = T().fromDoc ? ST.doc(T().fromDoc) : null;
    return `<div class="chat-empty">${from ? `<p class="notice-row nr-info from-doc" data-od-id="started-from-document">${ic('doc', 'sm')}<span class="nr-text">Started from <em>${esc(from.title)}</em>. It's listed in Documents; answers still use all your documents unless you turn on “Only search these documents”.</span></p>` : ''}
      <div><h2>Ask about your documents</h2>
        <p class="lede">I answer only from the documents in your Library and show the page each answer came from. There's nothing to choose first: just ask.</p></div>
      <section class="optional-slot" aria-labelledby="try-h"><h3 id="try-h">Try asking</h3>
        ${['How does ReAct combine reasoning and acting?', 'How does retrieval reduce hallucination in that loop?', 'How does PPO clip the policy update?'].map((q) => `<button class="example" type="button" data-action="example" data-q="${esc(q)}">${esc(q)}</button>`).join('')}</section>
    </div>`;
  }

  ST.chatView = () => {
    const t = T();
    if (hasNoDocs()) {
      return ST.shell({ nav: 'chat', content: `<div class="page"><div style="margin-top:48px">${ST.emptyState({ icon: 'upload', title: 'Upload a document first', text: 'The tutor answers only from your documents. Add a PDF to your Library and you can start asking in a few minutes.', actions: `<a class="btn btn-primary" href="#/library-empty" data-autofocus>${ic('upload', 'sm')}Upload</a>` })}</div></div>` });
    }
    const fromNote = t.fromNote ? ST.note(t.fromNote) : null;
    const body = !t.messages.length && !fromNote ? emptyHtml()
      : `<div class="thread" id="thread">${fromNote ? `<div class="banner banner-info">${ic('note')}<div class="b-body">Started from note: <a href="#/note/${fromNote.id}"><em>${esc(fromNote.title)}</em></a></div></div>` : ''}
          ${!t.messages.length ? `<p class="muted">Ask a question to discuss this note. The tutor answers from all of your documents.</p>` : ''}
          ${t.messages.map(msgHtml).join('')}${summaryCard()}</div>`;
    const split = ST.VW && ST.VW.mode === 'pane';
    return ST.shell({ nav: t.convId ? 'conversations' : 'chat', currentConv: t.convId, content: `<div class="chat chat-v10 ${S.chatPanel ? 'with-panel' : ''} ${split ? 'with-doc' : ''}">${headerHtml()}
      <div class="chat-body">${S.chatPanel ? panelHtml() : ''}
        <div class="conv-col" data-od-id="conversation"><div class="thread-scroll" data-keep-scroll="thread" id="thread-scroll">${body}</div>${composerHtml()}${statusHtml()}</div>
        ${split ? ST.paneHtml() : ''}</div></div>` });
  };
  const scrollBottom = (force = false) => { const el = document.getElementById('thread-scroll'); if (el && (force || el.scrollHeight - el.scrollTop - el.clientHeight < 200)) el.scrollTop = el.scrollHeight; };
  const autosize = () => { const ta = document.getElementById('composer-input'); if (!ta) return; ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'; };
  ST.chatAfter = () => autosize();
  ST.chatEnter = () => { scrollBottom(true); if (ST.VW && ST.VW.mode === 'pane') { ST.afterPaneDraw(); const h = document.getElementById('vw-title'); if (h) h.focus({ preventScroll: true }); } };

  /* ---------- streaming ---------- */
  let streamTimer = null;
  ST.stopStream = (silent) => {
    if (streamTimer) { clearInterval(streamTimer); streamTimer = null; }
    const t = T(); if (!t || !t.streaming) return;
    const m = t.messages.find((x) => x.id === t.streaming);
    if (m) { m.streaming = false; m.stopped = true; }
    t.streaming = null;
    if (!silent) { addTokens(m, true); ST.announce('Answer stopped.'); ST.render(); }
  };
  function addTokens(m, partial) {
    const t = T();
    t.tokens[0] += 2860 + t.messages.length * 140;
    t.tokens[1] += Math.round(((partial ? m.partial : m.text) || '').length / 4);
    const c = t.convId && ST.conv(t.convId);
    if (c) { c.tokens = t.tokens.slice(); c.last = ST.TODAY + 'T11:24'; if (!partial && !c.answers.includes(m.key)) c.answers.push(m.key); ST.syncConvSubjects(c); }
  }
  ST.streamAnswer = (key, { startAt = 0, speed = 45 } = {}) => {
    const t = T();
    const m = answerMsg(key, { streaming: true, partial: '' });
    t.messages.push(m); t.streaming = m.id;
    const words = m.text.split(/(\s+)/);
    let i = Math.floor(words.length * startAt);
    m.partial = words.slice(0, i).join('');
    ST.render(); scrollBottom(true);
    ST.announce('Smart Tutor is answering.');
    streamTimer = setInterval(() => {
      i += 2; m.partial = words.slice(0, i).join('');
      const node = document.getElementById('stream-' + m.id);
      if (node) { node.innerHTML = ST.mdParas(m.partial) + '<span class="cursor" aria-hidden="true"></span>'; scrollBottom(); }
      if (i >= words.length) {
        clearInterval(streamTimer); streamTimer = null;
        m.streaming = false; m.partial = null; t.streaming = null;
        addTokens(m, false); ST.render(); scrollBottom();
        ST.announce('Answer ready' + (S.citations ? `, with ${ST.plural(m.cites.length, 'source')}.` : '.'));
      }
    }, speed);
  };

  /* ---------- asking: no subject detection (K1) ---------- */
  function ensureConv(q) {
    const t = T(); if (t.convId) return;
    const id = 'cv' + (S.convs.length + 10);
    t.convId = id; if (t.title === 'New conversation') t.title = q;
    S.convs.push({ id, title: q, answers: [], subjects: [], last: ST.TODAY + 'T11:24', noteId: null, archived: false, tokens: t.tokens });
  }
  ST.ask = (q) => {
    const t = T(); q = (q || '').trim();
    if (!q || t.streaming || t.readOnly || t.rateLimit > 0) return;
    t.draft = '';
    t.messages.push(M({ role: 'user', text: q }));
    if (t.title === 'New conversation') t.title = q;
    ensureConv(q);
    if (noActiveDocs()) {
      t.messages.push(M({ role: 'tutor', kind: 'nodocs', question: q }));
      ST.render(); scrollBottom(true); ST.announce('None of your documents can be used right now. Upload a document to get an answer.');
      return;
    }
    if (ST.scopeOn(t)) {
      const key = ST.pickAnswer(q); const list = ST.convDocList(t);
      if (OFF_TOPIC.test(q) || !ST.ANSWERS[key].cites.some((c) => list.includes(c.doc))) {
        t.messages.push(M({ role: 'tutor', kind: 'decline', limited: true, question: q, count: list.length }));
        ST.render(); scrollBottom(true); ST.announce("These documents don't cover this.");
        return;
      }
    }
    if (OFF_TOPIC.test(q)) {
      t.messages.push(M({ role: 'tutor', kind: 'decline', question: q, topic: /laptop/i.test(q) ? 'choosing a laptop' : null }));
      t.tokens[0] += 1240; t.tokens[1] += 46;
      ST.render(); scrollBottom(true); ST.announce("Your documents don't cover this.");
      return;
    }
    ST.streamAnswer(ST.pickAnswer(q));
  };

  const findMsg = (el) => T().messages.find((m) => m.id === el.dataset.mid);
  Object.assign(ST.actions, {
    draft: (el) => { T().draft = el.value; autosize(); },
    send: () => ST.ask(T().draft),
    example: (el) => ST.ask(el.dataset.q),
    stop: () => ST.stopStream(false),
    'chat-menu': () => { S.chatMenu = !S.chatMenu; ST.render(); if (S.chatMenu) { const m = document.querySelector('.th-more .menu-item'); if (m) m.focus(); } },
    'toggle-citations': () => { S.chatMenu = false; S.citations = !S.citations; ST.ls.set('st3_citations', S.citations ? 'on' : 'off'); ST.render(); ST.announce(S.citations ? 'Citations shown.' : 'Citations hidden.'); },
    cite: (el) => { const c = findMsg(el).cites[+el.dataset.ci]; ST.openPane(c.doc, { page: c.page || 1, highlight: c.page ? c : null, chip: { mid: el.dataset.mid, ci: +el.dataset.ci } }); return; ST.openViewer(c.doc, { page: c.page || 1, highlight: c.page ? c : null, from: 'chat' }); },
    'docs-used': () => ST.openDocsUsed(),
    'title-edit': () => ST.startTitleEdit(),
    'title-draft': (el) => { const t = T(); t.titleDraft = el.value; const empty = !el.value.trim(); const box = el.closest('.th-title-edit'); if (!box) return; el.toggleAttribute('aria-invalid', empty); if (empty) el.setAttribute('aria-describedby', 'th-title-err'); else el.removeAttribute('aria-describedby'); let err = box.querySelector('.th-title-err'); if (empty && !err) box.insertAdjacentHTML('beforeend', `<p class="th-title-err" id="th-title-err" role="alert">${ic('alertCircle', 'sm')}Enter a title</p>`); if (!empty && err) err.remove(); },
    'chat-panel': () => { S.chatPanel = !S.chatPanel; if (!ST.VW || ST.VW.mode !== 'pane') ST.ls.set('st10_panel', S.chatPanel ? 'open' : 'closed'); ST.render(); const b = document.querySelector('[data-fk="chat-panel"]'); if (b) b.focus(); },
    'cp-open': (el) => ST.openPane(el.dataset.id, { page: 1, row: el.dataset.id }),
    'cp-remove': (el) => { const t = T(); const id = el.dataset.id; t.added = (t.added || []).filter((x) => x !== id); if (ST.docsUsed(t).includes(id)) t.removed = [...(t.removed || []), id]; if (!ST.convDocList(t).length) t.scopeOn = false; ST.render(); ST.announce(`${ST.docTitle(id)} removed from this conversation.`); const a = document.querySelector('[data-fk="docs-add"]'); if (a) a.focus(); },
    'scope-toggle': () => { const t = T(); t.scopeOn = !t.scopeOn; ST.render(); ST.announce(t.scopeOn ? `Only searching ${ST.plural(ST.convDocList(t).length, 'document')}.` : 'Searching all your documents.'); },
    'scope-change': () => { S.chatPanel = true; ST.render(); const sw = document.querySelector('[data-fk="scope-switch"]'); if (sw) sw.focus(); },
    'search-all': (el) => { const t = T(); const m = findMsg(el); t.scopeOn = false; m.resolved = true; ST.streamAnswer(ST.pickAnswer(m.question)); },
    'docs-add': () => ST.openDocPicker(),
    'fb-up': (el) => { const m = findMsg(el); m.fb = m.fb === 'up' ? null : 'up'; m.reasonOpen = false; ST.render(); },
    'fb-down': (el) => { const m = findMsg(el); if (m.fb === 'down') { m.fb = null; m.reasonOpen = false; m.reasonSent = false; } else { m.fb = 'down'; m.reasonOpen = true; m.reasonSent = false; } ST.render(); if (m.reasonOpen) { const r = document.querySelector(`[data-fk="r-${m.id}-0"]`); if (r) r.focus(); } },
    'fb-reason': (el) => { findMsg(el).reason = el.value; },
    'fb-text': (el) => { findMsg(el).reasonText = el.value; },
    'fb-skip': (el) => { const m = findMsg(el); m.reasonOpen = false; m.reasonSent = true; ST.render(); const b = document.querySelector(`[data-fk="down-${m.id}"]`); if (b) b.focus(); },
    'fb-send': (el) => { const m = findMsg(el); m.reasonOpen = false; m.reasonSent = true; ST.render(); ST.announce('Feedback sent.'); const b = document.querySelector(`[data-fk="down-${m.id}"]`); if (b) b.focus(); },
    'decline-upload': () => { ST.goto('library-default'); if (!S.uploadLimit) document.getElementById('file-input').click(); },
    retry: (el) => { const t = T(); t.messages = t.messages.filter((m) => m.id !== el.dataset.mid); const q = [...t.messages].reverse().find((m) => m.role === 'user'); ST.streamAnswer(ST.pickAnswer(q.text)); },
    summarize: () => {
      const t = T(); const n = t.noteId ? ST.note(t.noteId) : null;
      if (n && n.edited) {
        ST.openDialog({ title: 'Replace your edited note?', body: `<p>You've edited this note. Replace it with a new summary?</p><p class="small"><strong>${esc(n.title)}</strong> · edited ${esc(ST.fmtDate(n.editedAt || n.date))}</p>`,
          actions: [{ label: 'Cancel', autofocus: true }, { label: 'Replace', cls: 'btn-primary', onClick: () => startSummary('updated') }] });
      } else startSummary(n ? 'updated' : 'saved');
    },
    'archive-thread': () => { S.chatMenu = false; const t = T(); const c = ST.conv(t.convId); c.archived = true; t.readOnly = 'archived'; ST.render(); ST.toast('Conversation archived.', { undo: () => { c.archived = false; t.readOnly = null; ST.render(); } }); },
    'restore-thread': () => { const t = T(); const c = ST.conv(t.convId); if (c) c.archived = false; t.readOnly = null; ST.render(); ST.toast('Conversation restored.'); const i = document.getElementById('composer-input'); if (i) i.focus(); }
  });
  document.addEventListener('keydown', (e) => { if (e.target.id === 'composer-input' && e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ST.ask(T().draft); } });

  /* ---------- P5 · Add documents: searchable picker of the learner's ready documents ---------- */
  ST.openDocPicker = ({ q = '', sel = [] } = {}) => {
    ST.DPK = { q, sel: sel.slice() };
    ST.showOverlay(docPickerView, { onClose: () => { ST.DPK = null; } });
  };
  function docPickerView() {
    const t = T(); const P = ST.DPK; const listed = ST.convDocList(t);
    const docs = S.docs.filter((d) => d.state === 'ready' && !d.archived && !d.deleted && (!P.q || d.title.toLowerCase().includes(P.q.toLowerCase())));
    const n = P.sel.length;
    return `<div class="dialog-scrim" data-scrim><div class="dialog doc-picker" role="dialog" aria-modal="true" aria-labelledby="dpk-h" data-od-id="add-documents-dialog">
      <header><h2 id="dpk-h">Add documents</h2><button class="icon-btn sm" type="button" data-dlg-close aria-label="Close dialog">${ic('x')}</button></header>
      <div class="d-body">
        <input class="input" type="search" placeholder="Search your documents" aria-label="Search your documents" value="${esc(P.q)}" data-input="dpk-q" data-fk="dpk-q" data-autofocus>
        <ul class="dpk-list" role="group" aria-label="Your ready documents">${docs.length ? docs.map((d) => { const on = listed.includes(d.id); const chk = on || P.sel.includes(d.id); return `<li><label class="dpk-row ${on ? 'is-listed' : ''}"><input type="checkbox" ${chk ? 'checked' : ''} ${on ? 'disabled' : ''} data-change="dpk-toggle" data-id="${d.id}" data-fk="dpk-${d.id}">
          <span class="dpk-title" title="${esc(d.title)}">${esc(d.title)}</span><span class="dpk-meta">${on ? 'In this conversation' : `${esc(d.authors || '')}${d.year ? ' · ' + d.year : ''}`}</span></label></li>`; }).join('') : '<li class="cp-empty">No ready documents match.</li>'}</ul>
      </div>
      <footer><button class="btn btn-secondary" type="button" data-dlg-close>Cancel</button><button class="btn btn-primary" type="button" data-action="dpk-add" ${n ? '' : 'disabled'}>${n ? `Add ${ST.plural(n, 'document')}` : 'Add'}</button></footer>
    </div></div>`;
  }
  Object.assign(ST.actions, {
    'dpk-q': (el) => { ST.DPK.q = el.value; ST.redrawOverlay(); },
    'dpk-toggle': (el) => { const id = el.dataset.id; const P = ST.DPK; P.sel = el.checked ? [...P.sel, id] : P.sel.filter((x) => x !== id); ST.redrawOverlay(); },
    'dpk-add': () => { const t = T(); const ids = ST.DPK.sel; t.added = [...(t.added || []), ...ids]; t.removed = (t.removed || []).filter((x) => !ids.includes(x)); ST.hideOverlay(false); ST.render(); ST.announce(`${ST.plural(ids.length, 'document')} added to this conversation.`); const a = document.querySelector('[data-fk="docs-add"]'); if (a) a.focus(); }
  });

  /* ---------- lesson notes (a note's subjects come from the documents used) ---------- */
  ST.makeNote = (t, kind) => {
    const c = t.convId && ST.conv(t.convId);
    const subjects = ST.subjectsOfDocs(ST.docsUsed(t));
    if (!t.noteId) {
      if (t.convId === 'cv1') { t.noteId = 'n1'; }
      else {
        const id = 'n' + (S.notes.length + 10);
        const first = t.messages.find((m) => m.role === 'user');
        S.notes.push({ id, title: first ? first.text.replace(/\?$/, '') : 'Lesson note', subjects, date: ST.TODAY + 'T11:30', convId: t.convId, archived: false, edited: false,
          body: `# ${first ? first.text.replace(/\?$/, '') : 'Lesson note'}\n\n${t.messages.filter((m) => m.kind === 'answer').map((m) => m.text).join('\n\n')}` });
        t.noteId = id;
      }
    }
    const n = ST.note(t.noteId); n.edited = false; n.subjects = subjects; n.date = ST.TODAY + 'T11:30';
    if (c) c.noteId = t.noteId;
    t.summaryDone = kind;
  };
  function startSummary(kind) {
    const t = T(); t.summarizing = true; t.summaryDone = false;
    ST.render(); scrollBottom(true); ST.announce('Summarizing this lesson.');
    if (t.summaryHold) return;
    ST.later(() => { t.summarizing = false; ST.makeNote(t, kind); t.tokens[0] += 3120; t.tokens[1] += 486; ST.render(); scrollBottom(true); ST.announce(kind === 'updated' ? 'Lesson note updated.' : 'Lesson note saved.'); }, 3000);
  }

  ST.startRateLimit = (secs) => {
    const t = T(); t.rateLimit = secs;
    ST.every(() => {
      if (t.rateLimit <= 0) return;
      t.rateLimit -= 1;
      const el = document.getElementById('rl-count');
      if (t.rateLimit <= 0) { ST.render(); ST.announce('You can send messages again.'); } else if (el) el.textContent = t.rateLimit;
    }, 1000);
  };

  ST.dynamicConversation = (cid) => {
    const c = ST.conv(cid) || ST.conv('cv1');
    return { id: 'open/' + c.id, fixed: false, label: 'conversation · ' + c.id, desc: 'Opened from Conversations: full history with its lesson note in the header.',
      setup: () => { S.thread = ST.threadFromConv(c.id); }, view: ST.chatView, afterRender: ST.chatAfter, afterEnter: ST.chatEnter };
  };
})();
