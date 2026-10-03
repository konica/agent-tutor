/* Smart Tutor v0.3 — chat (§6.6): multi-subject conversations that grow to 3, simulated tutor, every state. */
(function () {
  const ST = window.ST;
  const S = ST.S;
  const esc = ST.esc, ic = ST.ic;
  const MAX = 3;

  /* ---------- detection & answer choice (simulated) ---------- */
  const RULES = [
    ['agents', /\breact\b|agent|tool use|\btools?\b|acting|planner/i],
    ['rag', /retriev|\brag\b|hallucinat|grounding|dense|bm25/i],
    ['llm', /attention|transformer|\bllms?\b|language model|chain[- ]of[- ]thought|prompting/i],
    ['rl', /\bppo\b|polic(y|ies)|reinforcement|reward/i]
  ];
  const OFF_TOPIC = /laptop|buy|price|weather|recipe|movie|restaurant/i;
  ST.classify = (q) => {
    const mine = ST.mySubjects();
    return RULES.filter(([id, rx]) => rx.test(q) && mine.includes(id)).map(([id]) => id);
  };
  ST.pickAnswer = (q, subjects) => {
    if (/\breact\b/i.test(q) && !/retriev|hallucinat/i.test(q)) return 'react';
    if (/hallucinat|retriev.*loop/i.test(q)) return 'rag_loop';
    if (/long documents|long input|handle long/i.test(q)) return 'long_docs';
    if (/attention/i.test(q)) return 'attention';
    if (/\bppo\b|clip/i.test(q)) return 'ppo';
    if (/chain/i.test(q)) return 'cot';
    if (/dense|bm25/i.test(q)) return 'rag_dense';
    return 'generic_' + (subjects[0] || 'llm');
  };

  /* ---------- thread model ---------- */
  let mid = 0;
  const M = (o) => Object.assign({ id: 'm' + (++mid) }, o);
  ST.M = M;
  ST.newThread = (o = {}) => Object.assign({
    convId: null, title: 'New conversation', subjects: [], fromNote: null, noteId: null, readOnly: null,
    messages: [], tokens: [0, 0], streaming: null, summarizing: false, summaryHold: false, summaryDone: false,
    rateLimit: 0, draft: '', highlight: null
  }, o);
  const answerMsg = (key, extra = {}) => { const a = ST.ANSWERS[key]; return M(Object.assign({ role: 'tutor', kind: 'answer', key, text: a.text, quote: a.quote || null, cites: ST.clone(a.cites), fb: null }, extra)); };
  ST.answerMsg = answerMsg;

  /* J2/J3 script (§9): returns the cv1 thread after `upTo` learner turns. */
  ST.J2 = [
    { q: 'How does ReAct combine reasoning and acting?', add: ['agents'], a: 'react', tokens: [3920, 412] },
    { q: 'How does retrieval reduce hallucination in that loop?', add: ['rag'], a: 'rag_loop', tokens: [8110, 1530] },
    { q: 'How does self-attention work?', add: ['llm'], a: 'attention', tokens: [12480, 3215] },
    { q: 'How does PPO clip the policy update?', refuse: 'rl' }
  ];
  ST.j2Thread = (upTo, o = {}) => {
    const t = ST.newThread({ convId: 'cv1', title: ST.J2[0].q });
    ST.J2.slice(0, upTo).forEach((s, i) => {
      t.messages.push(M({ role: 'user', text: s.q }));
      if (s.refuse) { t.messages.push(M({ role: 'tutor', kind: 'refused', question: s.q, subject: s.refuse })); return; }
      if (i > 0) s.add.forEach((id) => t.messages.push(M({ role: 'notice', kind: 'added', subject: id })));
      t.subjects.push(...s.add);
      if (i > 0 && t.subjects.length === MAX) t.messages.push(M({ role: 'notice', kind: 'max' }));
      t.messages.push(answerMsg(s.a));
      t.tokens = s.tokens.slice();
    });
    return Object.assign(t, o);
  };
  ST.threadFromConv = (cid, o = {}) => {
    const c = ST.conv(cid);
    if (cid === 'cv1') return ST.j2Thread(3, Object.assign({ noteId: c.noteId, readOnly: c.archived ? 'archived' : null }, o));
    const t = ST.newThread({ convId: c.id, title: c.title, subjects: c.subjects.slice(), noteId: c.noteId, tokens: c.tokens.slice(), readOnly: c.archived ? 'archived' : null });
    t.messages.push(M({ role: 'user', text: c.title }), answerMsg(c.answer));
    return Object.assign(t, o);
  };

  /* ---------- rendering ---------- */
  const T = () => S.thread;
  const noActiveDocs = (t) => t.subjects.length && !S.docs.some((d) => d.state === 'ready' && !d.archived && d.subjects.some((s) => t.subjects.includes(s)));
  const hasNoDocs = () => !S.docs.some((d) => !d.archived);

  function citesHtml(m) {
    if (!S.citations || !m.cites.length) return '';
    return `<div class="cites"><span class="cites-label" id="cl-${m.id}">Sources</span>
      <div class="cite-list" role="list" aria-labelledby="cl-${m.id}">${m.cites.map((c, i) => { const d = ST.doc(c.doc); return `<span role="listitem"><button class="cite" type="button" data-action="cite" data-mid="${m.id}" data-ci="${i}" data-fk="cite-${m.id}-${i}">
        ${ic('doc')}<span><span class="doc-name">${esc(d ? d.title : 'Document')}</span><span class="page">, ${c.page ? 'p. ' + c.page : 'page unavailable'}</span></span>${d && d.archived ? `<span class="badge badge-archived">${ic('archive')}Archived</span>` : ''}</button></span>`; }).join('')}</div></div>`;
  }
  function feedbackHtml(m) {
    let html = `<div class="feedback" role="group" aria-label="Rate this answer"><span class="fb-label">Helpful?</span>
      <button class="icon-btn sm" type="button" data-action="fb-up" data-mid="${m.id}" data-fk="up-${m.id}" aria-pressed="${m.fb === 'up'}" aria-label="Helpful">${ic('thumb', 'sm')}</button>
      <button class="icon-btn sm" type="button" data-action="fb-down" data-mid="${m.id}" data-fk="down-${m.id}" aria-pressed="${m.fb === 'down'}" aria-label="Not helpful">${ic('thumb', 'sm flip-y')}</button>
      ${m.fb === 'up' ? '<span class="fb-thanks">Thanks — glad it helped.</span>' : ''}${m.fb === 'down' && m.reasonSent ? '<span class="fb-thanks">Thanks — your feedback helps improve answers.</span>' : ''}</div>`;
    if (m.fb === 'down' && m.reasonOpen) {
      const reasons = ['Not accurate', "Didn't answer my question", "Citation doesn't match", 'Hard to follow'];
      html += `<form class="reason-form" onsubmit="return false"><fieldset><legend>What could be better? <span class="muted" style="font-weight:400">Optional</span></legend>
        <div class="reason-opts">${reasons.map((r, i) => `<label><input type="radio" name="reason-${m.id}" value="${esc(r)}" ${m.reason === r ? 'checked' : ''} data-change="fb-reason" data-mid="${m.id}" data-fk="r-${m.id}-${i}">${esc(r)}</label>`).join('')}</div></fieldset>
        <div class="field"><label for="rt-${m.id}">Anything else? <span class="muted" style="font-weight:400">Optional</span></label><textarea class="textarea" id="rt-${m.id}" rows="2" data-input="fb-text" data-mid="${m.id}">${esc(m.reasonText || '')}</textarea></div>
        <div class="rf-actions"><button class="btn btn-quiet btn-sm" type="button" data-action="fb-skip" data-mid="${m.id}">Skip</button><button class="btn btn-primary btn-sm" type="button" data-action="fb-send" data-mid="${m.id}">Send feedback</button></div></form>`;
    }
    return html;
  }
  const tutorWrap = (m, inner, busy = false) => `<article class="msg-tutor msg-enter" id="m-${m.id}" aria-label="Smart Tutor">${ST.logo('logo')}
    <div class="msg-body" ${busy ? 'aria-busy="true"' : ''}><span class="msg-name">Smart Tutor</span>${inner}</div></article>`;
  const quoteHtml = (q) => { const d = ST.doc(q.doc); return `<figure class="excerpt"><blockquote>“${esc(q.text)}”</blockquote><figcaption>${ic('quote', 'sm')}Quoted from <span style="text-transform:none;letter-spacing:0"><em>${esc(d ? d.title : '')}</em>, p. ${q.page}</span></figcaption></figure>`; };
  const names = (ids) => { const n = ids.map((i) => ST.sname(i)); return n.length > 1 ? n.slice(0, -1).join(', ') + ' and ' + n[n.length - 1] : n[0]; };

  function msgHtml(m) {
    if (m.role === 'user') return `<div class="msg-user msg-enter"><span class="vh">You asked: </span>${esc(m.text)}</div>`;
    if (m.role === 'notice') {
      if (m.kind === 'added') return `<div class="notice" role="note"><div>${ic('plusCircle')}<span>Added <em>${esc(ST.sname(m.subject))}</em> to this conversation</span></div></div>`;
      return `<div class="notice max" role="note"><div>${ic('info')}<span>This conversation now covers 3 subjects, the maximum. For other topics, start a new conversation.</span></div></div>`;
    }
    if (m.kind === 'answer') {
      if (m.streaming) return tutorWrap(m, `<div class="stream" id="stream-${m.id}">${ST.mdParas(m.partial || '')}<span class="cursor" aria-hidden="true"></span></div>`, true);
      const text = m.stopped ? m.partial : m.text;
      return tutorWrap(m, `${ST.mdParas(text)}${m.quote && !m.stopped ? quoteHtml(m.quote) : ''}
        ${m.stopped ? `<p class="small muted">${ic('stop', 'sm')} You stopped this answer.</p>` : ''}${citesHtml(m)}${feedbackHtml(m)}`);
    }
    if (m.kind === 'unsure') {
      return tutorWrap(m, `<div class="tutor-card"><p>Which subjects is this about?</p>
        <p class="small muted">Pick 1 to 3. I'll answer your question right after.</p>
        <div class="pick-chips" role="group" aria-label="Your subjects">${ST.mySubjects().map((s) => { const on = m.picks.includes(s); return `<button type="button" class="schip" data-s="${ST.hueKey(s)}" aria-pressed="${on}" data-action="unsure-pick" data-mid="${m.id}" data-id="${s}" data-fk="up-${s}" ${m.done || (!on && m.picks.length >= MAX) ? 'disabled' : ''}>${ic('check', 'sm ck')}<span class="dot" aria-hidden="true"></span>${esc(ST.sname(s))}</button>`; }).join('')}</div>
        <div class="tc-actions"><button class="btn btn-primary" type="button" data-action="unsure-go" data-mid="${m.id}" data-fk="unsure-go" ${m.done || !m.picks.length ? 'disabled' : ''}>Continue</button></div></div>`);
    }
    if (m.kind === 'refused') {
      return tutorWrap(m, `<div class="tutor-card decline">
        <p>This conversation already covers 3 subjects: ${esc(names(T().subjects))}. Your question is about <em>${esc(ST.sname(m.subject))}</em>, so I haven't answered it here.</p>
        <p class="small muted">A new conversation can answer it. I'll bring your question with you.</p>
        <div class="tc-actions"><button class="btn btn-primary" type="button" data-action="carry-over" data-mid="${m.id}" data-fk="carry">${ic('plus', 'sm')}New conversation</button></div></div>`);
    }
    if (m.kind === 'decline') {
      return tutorWrap(m, `<div class="tutor-card decline">
        <p>Your documents don't cover this. I can only answer from the documents in your Library, and none of them discuss ${esc(m.topic || 'this question')}.</p>
        <div class="tc-actions">${m.other ? `<button class="btn btn-secondary" type="button" data-action="carry-over" data-mid="${m.id}">${ic('plus', 'sm')}New conversation</button>` : `<a class="btn btn-secondary" href="#/library-default">${ic('upload', 'sm')}Add a document</a>`}</div></div>`);
    }
    if (m.kind === 'error') {
      return tutorWrap(m, `<div class="tutor-card error" role="alert"><p class="tc-head">${ic('alertCircle', 'sm')}This answer didn't come through.</p>
        <p class="small muted">Something went wrong while answering. Your question is saved.</p>
        <div class="tc-actions"><button class="btn btn-secondary" type="button" data-action="retry" data-mid="${m.id}" data-fk="retry">${ic('retry', 'sm')}Retry</button></div></div>`);
    }
    return '';
  }

  function headerHtml() {
    const t = T();
    const note = t.noteId ? ST.note(t.noteId) : null;
    const hasAnswer = t.messages.some((m) => m.kind === 'answer' && !m.streaming);
    const chips = t.subjects.length
      ? `<span class="chips" aria-label="Subjects in this conversation">${t.subjects.map((s) => ST.schip(s, t.highlight === s ? 'flash' : '')).join('')}</span>`
      : `<span>Subjects appear after your first question.</span>`;
    let summarize = '';
    if (hasAnswer && t.readOnly !== 'archived') {
      summarize = t.summarizing
        ? `<button class="btn btn-secondary" type="button" disabled data-fk="summ"><span class="spinner" aria-hidden="true"></span>Summarizing…</button>`
        : `<button class="btn btn-secondary" type="button" data-action="summarize" data-fk="summ" ${t.streaming || t.rateLimit ? 'disabled' : ''}>${ic('note', 'sm')}${note ? 'Update lesson note' : 'Summarize lesson'}</button>`;
    }
    return `<header class="thread-head">
      <div class="th-title"><h1 class="od-truncate">${esc(t.title)}</h1>
        <div class="th-sub">${chips}${note ? `<span class="th-sep" aria-hidden="true"></span><a href="#/note/${note.id}" class="od-row" style="--od-gap:6px;min-width:0">${ic('note', 'sm')}<span class="od-truncate">Lesson note: ${esc(note.title)}</span></a>` : ''}</div></div>
      <div class="th-actions">
        <button class="switch" type="button" role="switch" aria-checked="${S.citations}" data-action="toggle-citations" data-fk="cit-switch"><span class="track" aria-hidden="true"></span>Show citations<span class="state" aria-hidden="true">${S.citations ? 'On' : 'Off'}</span></button>
        ${summarize ? '<span class="th-sep" aria-hidden="true"></span>' + summarize : ''}
        ${t.convId && !t.readOnly ? `<button class="icon-btn" type="button" data-action="archive-thread" aria-label="Archive conversation" title="Archive conversation">${ic('archive')}</button>` : ''}
      </div></header>`;
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
    } else if (noActiveDocs(t)) {
      disabled = true; placeholder = 'No active documents in these subjects';
      banner = `<div class="banner">${ic('archive')}<div class="b-body"><strong>There are no active documents in this conversation's subjects.</strong><span>The history stays readable. Restore a document to keep asking.</span></div><a class="btn btn-secondary btn-sm" href="#/library-archived">Open archived documents</a></div>`;
    } else if (t.rateLimit > 0) {
      disabled = true; placeholder = 'Sending is paused for a moment';
      banner = `<div class="banner banner-warn">${ic('clock')}<div class="b-body"><strong>You've sent 20 messages in the last minute.</strong><span>You can send again in <span id="rl-count" class="mono">${t.rateLimit}</span> seconds.</span></div></div>`;
    }
    const processing = ST.stillProcessing();
    const hint = !disabled && processing ? `<p class="input-hint">${ic('clock', 'sm')}${ST.plural(processing, 'document')} ${processing === 1 ? 'is' : 'are'} still processing and can't be used yet.</p>` : '';
    const btn = t.streaming
      ? `<button class="btn btn-secondary" type="button" data-action="stop" data-fk="stop">${ic('stop', 'sm')}Stop</button>`
      : `<button class="btn btn-primary send" type="button" data-action="send" data-fk="send" aria-label="Send question" ${disabled ? 'disabled' : ''}>${ic('send')}</button>`;
    return `<div class="composer-wrap"><div class="composer-inner">${banner}${hint}
      <div class="composer ${disabled ? 'disabled' : ''}"><label class="vh" for="composer-input">Ask the tutor</label>
        <textarea id="composer-input" rows="1" placeholder="${placeholder}" data-input="draft" data-fk="composer" ${disabled ? 'disabled' : ''} ${!t.messages.length && !disabled ? 'data-autofocus' : ''}>${esc(t.draft)}</textarea>${btn}</div></div></div>`;
  }
  const statusHtml = () => { const t = T(); return `<div class="status-wrap"><div class="status-line"><span class="tokens mono" id="token-line">Tokens: ${ST.num(t.tokens[0])} in · ${ST.num(t.tokens[1])} out</span><span>Enter to send · Shift + Enter for a new line</span></div></div>`; };

  function emptyHtml() {
    const mine = ST.mySubjects();
    return `<div class="chat-empty">
      <div><h2>Ask about your documents</h2>
        <p class="lede">I work out which of your subjects a question is about, answer only from your documents, and show the page each answer came from.</p></div>
      <p class="your-subjects"><span>Your subjects:</span>${mine.map((s) => ST.schip(s, 'sm')).join('')}</p>
      <section class="optional-slot" aria-labelledby="try-h"><h3 id="try-h">Try asking</h3>
        ${['How does ReAct combine reasoning and acting?', 'How does self-attention work?', 'What problem does the PPO clipped objective solve?'].map((q) => `<button class="example" type="button" data-action="example" data-q="${esc(q)}">${esc(q)}</button>`).join('')}</section>
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
          ${!t.messages.length ? `<p class="muted">Ask a question to discuss this note. This conversation starts with ${esc(names(t.subjects))}.</p>` : ''}
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
    const c = t.convId && ST.conv(t.convId); if (c) { c.tokens = t.tokens.slice(); c.last = ST.TODAY + 'T11:24'; }
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
    if (t.highlight) { const h = t.highlight; setTimeout(() => { if (T() === t && t.highlight === h) { t.highlight = null; document.querySelectorAll('.schip.flash').forEach((e) => e.classList.remove('flash')); } }, 2600); }
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

  /* ---------- asking ---------- */
  function ensureConv(q) {
    const t = T(); if (t.convId) return;
    const id = 'cv' + (S.convs.length + 10);
    t.convId = id; if (t.title === 'New conversation') t.title = q;
    S.convs.push({ id, title: q, subjects: t.subjects, last: ST.TODAY + 'T11:24', noteId: null, archived: false, tokens: t.tokens });
  }
  ST.ask = (q) => {
    const t = T(); q = (q || '').trim();
    if (!q || t.streaming || t.readOnly || t.rateLimit > 0 || noActiveDocs(t)) return;
    t.draft = '';
    t.messages.push(M({ role: 'user', text: q }));
    if (t.title === 'New conversation') t.title = q;
    const det = ST.classify(q);
    if (!det.length) {
      if (OFF_TOPIC.test(q)) {
        t.messages.push(M({ role: 'tutor', kind: 'decline', question: q, topic: /laptop/i.test(q) ? 'choosing a laptop' : null }));
        t.tokens[0] += 1240; t.tokens[1] += 46; ensureConv(q);
        ST.render(); scrollBottom(true); ST.announce("Your documents don't cover this.");
        return;
      }
      t.messages.push(M({ role: 'tutor', kind: 'unsure', question: q, picks: [] }));
      ST.render(); scrollBottom(true); ST.announce('Which subjects is this about?');
      return;
    }
    if (!t.subjects.length) { t.subjects = det.slice(0, MAX); ensureConv(q); ST.conv(t.convId).subjects = t.subjects; ST.streamAnswer(ST.pickAnswer(q, t.subjects)); return; }
    ensureConv(q);
    const fresh = det.filter((s) => !t.subjects.includes(s));
    if (t.subjects.length + fresh.length > MAX) {
      t.messages.push(M({ role: 'tutor', kind: 'refused', question: q, subject: fresh[0] }));
      t.tokens[0] += 980; t.tokens[1] += 52;
      ST.render(); scrollBottom(true); ST.announce('This conversation already covers 3 subjects. Start a new conversation for this question.');
      return;
    }
    fresh.forEach((s) => { t.subjects.push(s); t.messages.push(M({ role: 'notice', kind: 'added', subject: s })); t.highlight = s; });
    if (fresh.length) {
      ST.conv(t.convId).subjects = t.subjects;
      ST.announce(`Added ${names(fresh)} to this conversation.` + (t.subjects.length === MAX ? ' This conversation now covers 3 subjects, the maximum.' : ''));
      if (t.subjects.length === MAX) t.messages.push(M({ role: 'notice', kind: 'max' }));
    }
    ST.streamAnswer(ST.pickAnswer(q, t.subjects));
  };

  const findMsg = (el) => T().messages.find((m) => m.id === el.dataset.mid);
  Object.assign(ST.actions, {
    draft: (el) => { T().draft = el.value; autosize(); },
    send: () => ST.ask(T().draft),
    example: (el) => ST.ask(el.dataset.q),
    stop: () => ST.stopStream(false),
    'toggle-citations': () => { S.citations = !S.citations; ST.ls.set('st3_citations', S.citations ? 'on' : 'off'); ST.render(); ST.announce(S.citations ? 'Citations shown.' : 'Citations hidden.'); },
    cite: (el) => { const c = findMsg(el).cites[+el.dataset.ci]; ST.openDetails(c.doc, { cited: { page: c.page } }); },
    'fb-up': (el) => { const m = findMsg(el); m.fb = m.fb === 'up' ? null : 'up'; m.reasonOpen = false; ST.render(); },
    'fb-down': (el) => { const m = findMsg(el); if (m.fb === 'down') { m.fb = null; m.reasonOpen = false; m.reasonSent = false; } else { m.fb = 'down'; m.reasonOpen = true; m.reasonSent = false; } ST.render(); if (m.reasonOpen) { const r = document.querySelector(`[data-fk="r-${m.id}-0"]`); if (r) r.focus(); } },
    'fb-reason': (el) => { findMsg(el).reason = el.value; },
    'fb-text': (el) => { findMsg(el).reasonText = el.value; },
    'fb-skip': (el) => { const m = findMsg(el); m.reasonOpen = false; m.reasonSent = true; ST.render(); const b = document.querySelector(`[data-fk="down-${m.id}"]`); if (b) b.focus(); },
    'fb-send': (el) => { const m = findMsg(el); m.reasonOpen = false; m.reasonSent = true; ST.render(); ST.announce('Feedback sent.'); const b = document.querySelector(`[data-fk="down-${m.id}"]`); if (b) b.focus(); },
    'unsure-pick': (el) => { const m = findMsg(el); const id = el.dataset.id; m.picks = m.picks.includes(id) ? m.picks.filter((x) => x !== id) : m.picks.length < MAX ? [...m.picks, id] : m.picks; ST.render(); },
    'unsure-go': (el) => {
      const t = T(); const m = findMsg(el); if (!m.picks.length) return;
      m.done = true; t.subjects = m.picks.slice(); ensureConv(m.question); ST.conv(t.convId).subjects = t.subjects;
      ST.streamAnswer(ST.pickAnswer(m.question, t.subjects));
    },
    'carry-over': (el) => { ST.pendingAsk = findMsg(el).question; ST.goto('chat-new'); },
    retry: (el) => { const t = T(); t.messages = t.messages.filter((m) => m.id !== el.dataset.mid); const q = [...t.messages].reverse().find((m) => m.role === 'user'); ST.streamAnswer(ST.pickAnswer(q.text, t.subjects)); },
    summarize: () => {
      const t = T(); const n = t.noteId ? ST.note(t.noteId) : null;
      if (n && n.edited) {
        ST.openDialog({ title: 'Replace your edited note?', body: `<p>You've edited this note. Replace it with a new summary?</p><p class="small"><strong>${esc(n.title)}</strong> · edited ${esc(ST.fmtDate(n.editedAt || n.date))}</p>`,
          actions: [{ label: 'Cancel', autofocus: true }, { label: 'Replace', cls: 'btn-primary', onClick: () => startSummary('updated') }] });
      } else startSummary(n ? 'updated' : 'saved');
    },
    'archive-thread': () => { const t = T(); const c = ST.conv(t.convId); c.archived = true; t.readOnly = 'archived'; ST.render(); ST.toast('Conversation archived.', { undo: () => { c.archived = false; t.readOnly = null; ST.render(); } }); },
    'restore-thread': () => { const t = T(); const c = ST.conv(t.convId); if (c) c.archived = false; t.readOnly = null; ST.render(); ST.toast('Conversation restored.'); const i = document.getElementById('composer-input'); if (i) i.focus(); }
  });
  document.addEventListener('keydown', (e) => { if (e.target.id === 'composer-input' && e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ST.ask(T().draft); } });

  /* ---------- lesson notes ---------- */
  ST.makeNote = (t, kind) => {
    const c = t.convId && ST.conv(t.convId);
    if (!t.noteId) {
      if (t.convId === 'cv1') { t.noteId = 'n1'; }
      else {
        const id = 'n' + (S.notes.length + 10);
        const first = t.messages.find((m) => m.role === 'user');
        S.notes.push({ id, title: first ? first.text.replace(/\?$/, '') : 'Lesson note', subjects: t.subjects.slice(), date: ST.TODAY + 'T11:30', convId: t.convId, archived: false, edited: false,
          body: `# ${first ? first.text.replace(/\?$/, '') : 'Lesson note'}\n\n${t.messages.filter((m) => m.kind === 'answer').map((m) => m.text).join('\n\n')}` });
        t.noteId = id;
      }
    }
    const n = ST.note(t.noteId); n.edited = false; n.subjects = t.subjects.slice(); n.date = ST.TODAY + 'T11:30';
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
