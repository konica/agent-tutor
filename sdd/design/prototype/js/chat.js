/* Smart Tutor v0.9 — chat (§6.6): no subjects in conversations (K1); every question is answered from all
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
      return `<span role="listitem"><button class="cite" type="button" data-action="cite" data-mid="${m.id}" data-ci="${i}" data-fk="cite-${m.id}-${i}" aria-label="${esc(d.title)}, ${pg}${d.archived ? ', archived' : ''}. Open in the document viewer" data-tip="${esc(d.title)}, ${pg}">
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

  /* M6: one 40px header row: title, Documents used (N), Summarize lesson, overflow (Archive, Show citations). */
  function headerHtml() {
    const t = T();
    const note = t.noteId ? ST.note(t.noteId) : null;
    const hasAnswer = t.messages.some((m) => m.kind === 'answer' && !m.streaming);
    const used = ST.docsUsed(t).length;
    let summarize = '';
    if (hasAnswer && t.readOnly !== 'archived') {
      summarize = t.summarizing
        ? `<button class="btn btn-secondary btn-sm" type="button" disabled data-fk="summ"><span class="spinner" aria-hidden="true"></span>Summarizing…</button>`
        : `<button class="btn btn-secondary btn-sm" type="button" data-action="summarize" data-fk="summ" ${t.streaming || t.rateLimit ? 'disabled' : ''}>${ic('note', 'sm')}${note ? 'Update lesson note' : 'Summarize lesson'}</button>`;
    }
    const menuOpen = S.chatMenu;
    return `<header class="thread-head" data-od-id="thread-header">
      <h1 class="od-truncate" title="${esc(t.title)}">${esc(t.title)}</h1>
      ${note ? `<a href="#/note/${note.id}" class="th-note" title="Lesson note: ${esc(note.title)}">${ic('note', 'sm')}<span class="od-truncate">Lesson note</span></a>` : ''}
      <span class="od-fill"></span>
      <button class="btn btn-quiet btn-sm" type="button" data-action="docs-used" data-fk="docs-used" aria-haspopup="dialog" data-od-id="documents-used-button">${ic('layers', 'sm')}Documents used (${used})</button>
      ${summarize}
      <span class="row-menu-wrap th-more"><button class="icon-btn sm" type="button" data-action="chat-menu" data-fk="chat-menu" aria-haspopup="menu" aria-expanded="${!!menuOpen}" aria-label="More conversation actions" data-tip="More" data-od-id="thread-overflow">${ic('more')}</button>
        ${menuOpen ? `<div class="row-menu" role="menu" aria-label="Conversation actions">
          <button class="menu-item" role="menuitemcheckbox" aria-checked="${S.citations}" type="button" data-action="toggle-citations" data-fk="cit-switch">${ic(S.citations ? 'check' : 'quote')}Show citations<span class="mi-state">${S.citations ? 'On' : 'Off'}</span></button>
          ${t.convId && !t.readOnly ? `<button class="menu-item" role="menuitem" type="button" data-action="archive-thread">${ic('archive')}Archive conversation</button>` : ''}
        </div>` : ''}</span>
    </header>`;
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
    return `<div class="composer-wrap"><div class="composer-inner">${banner}
      <div class="composer ${disabled ? 'disabled' : ''}"><label class="vh" for="composer-input">Ask the tutor</label>
        <textarea id="composer-input" rows="1" placeholder="${placeholder}" data-input="draft" data-fk="composer" ${disabled ? 'disabled' : ''} ${!t.messages.length && !disabled ? 'data-autofocus' : ''}>${esc(t.draft)}</textarea>${btn}</div></div></div>`;
  }
  const statusHtml = () => { const t = T(); return `<div class="status-wrap"><div class="status-line">${t.hint ? `<span class="input-hint">${ic('clock', 'sm')}${esc(t.hint)}</span>` : '<span class="sl-keys">Enter to send · Shift + Enter for a new line</span>'}<span class="tokens mono" id="token-line">Tokens: ${ST.num(t.tokens[0])} in · ${ST.num(t.tokens[1])} out</span></div></div>`; };

  function emptyHtml() {
    return `<div class="chat-empty">
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
    return ST.shell({ nav: t.convId ? 'conversations' : 'chat', currentConv: t.convId, content: `<div class="chat">${headerHtml()}
      <div class="thread-scroll" data-keep-scroll="thread" id="thread-scroll">${body}</div>${composerHtml()}${statusHtml()}</div>` });
  };
  const scrollBottom = (force = false) => { const el = document.getElementById('thread-scroll'); if (el && (force || el.scrollHeight - el.scrollTop - el.clientHeight < 200)) el.scrollTop = el.scrollHeight; };
  const autosize = () => { const ta = document.getElementById('composer-input'); if (!ta) return; ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'; };
  ST.chatAfter = () => autosize();
  ST.chatEnter = () => scrollBottom(true);

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
    cite: (el) => { const c = findMsg(el).cites[+el.dataset.ci]; ST.openViewer(c.doc, { page: c.page || 1, highlight: c.page ? c : null, from: 'chat' }); },
    'docs-used': () => ST.openDocsUsed(),
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
