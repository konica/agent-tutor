/* Smart Tutor — chat screen (§5.4): thread model, simulated tutor, every state. */
(function () {
  const ST = window.ST;
  const S = ST.S;
  const esc = ST.esc, ic = ST.ic;

  ST.ANSWERS.agents_planning = {
    subject: 'AI Agents',
    text: 'In agent design, planning means breaking a goal into steps before acting.\n\nA common approach is *plan-and-execute*: a planner writes the steps, an executor carries them out one by one, and the plan is revised when an observation shows that a step failed.',
    cites: [{ doc: 'Agentic Design Patterns', page: 88 }]
  };

  /* ---------- subject detection & answer choice (simulated) ---------- */
  const RX_IELTS = /\bielts\b|essay|task ?[12]\b|band score|speaking part|part [23]\b|paraphras|cohesion|body paragraph|introduction|examiner/i;
  const RX_AGENTS = /agent|\breact\b|\btools?\b|\bskills?\b|\bllm|planner|router|human in the loop|\brag\b|prompt/i;
  ST.classify = (q) => {
    const a = RX_IELTS.test(q), b = RX_AGENTS.test(q);
    if (a && !b) return 'IELTS';
    if (b && !a) return 'AI Agents';
    return null;
  };
  ST.pickAnswer = (q, subject) => {
    if (subject === 'IELTS') {
      if (/structure|task 2 essay/i.test(q)) return 'ielts_task2';
      if (/paraphras|introduction/i.test(q)) return 'ielts_paraphrase';
      if (/paragraph|how long/i.test(q)) return 'ielts_para';
      return 'ielts_generic';
    }
    if (/\breact\b/i.test(q)) return 'react';
    if (/tool/i.test(q) && /skill/i.test(q)) return 'tool_skill';
    if (/plan/i.test(q)) return 'agents_planning';
    return 'agents_generic';
  };

  /* ---------- thread construction ---------- */
  let mid = 0;
  const M = (o) => Object.assign({ id: 'm' + (++mid) }, o);
  ST.newThread = (o = {}) => Object.assign({
    convId: null, title: 'New conversation', subject: null, fromNote: null, noteId: null,
    readOnly: null, messages: [], tokens: [0, 0], streaming: null, summarizing: false, summaryHold: false,
    summaryDone: false, rateLimit: 0, draft: ''
  }, o);
  const answerMsg = (key, extra = {}) => {
    const a = ST.ANSWERS[key];
    return M(Object.assign({ role: 'tutor', kind: 'answer', key, text: a.text, cites: ST.clone(a.cites), fb: null }, extra));
  };
  ST.threadFromConv = (cid, o = {}) => {
    const c = ST.conv(cid);
    const t = ST.newThread({ convId: c.id, title: c.title, subject: c.subject, noteId: c.noteId, tokens: c.tokens.slice(), readOnly: c.archived ? 'archived' : null });
    t.messages.push(M({ role: 'user', text: c.title }));
    t.messages.push(M({ role: 'sys', text: `Subject set to ${c.subject} from your question.` }));
    t.messages.push(answerMsg(c.answer));
    return Object.assign(t, o);
  };
  ST.addFollowUp = (t, q, key) => { t.messages.push(M({ role: 'user', text: q })); t.messages.push(answerMsg(key)); };
  ST.M = M;
  ST.answerMsg = answerMsg;

  /* ---------- rendering ---------- */
  const T = () => S.thread;

  function citesHtml(m) {
    if (!S.citations || !m.cites || !m.cites.length) return '';
    return `<div class="cites"><span class="cites-label" id="cl-${m.id}">Sources</span>
      <div class="cite-list" role="list" aria-labelledby="cl-${m.id}">${m.cites.map((c, i) => `<span role="listitem"><button class="cite" type="button" data-action="cite" data-mid="${m.id}" data-ci="${i}" data-fk="cite-${m.id}-${i}">
        ${ic('doc')}<span>${esc(c.doc)}<span class="page">, p. ${c.page}</span></span>${c.archived ? `<span class="badge badge-archived">${ic('archive')}archived</span>` : ''}</button></span>`).join('')}</div></div>`;
  }

  function feedbackHtml(m) {
    if (m.streaming) return '';
    let html = `<div class="feedback" role="group" aria-label="Rate this answer">
      <span class="fb-label">Helpful?</span>
      <button class="icon-btn sm" type="button" data-action="fb-up" data-mid="${m.id}" data-fk="up-${m.id}" aria-pressed="${m.fb === 'up'}" aria-label="Helpful">${ic('thumb', 'sm')}</button>
      <button class="icon-btn sm" type="button" data-action="fb-down" data-mid="${m.id}" data-fk="down-${m.id}" aria-pressed="${m.fb === 'down'}" aria-label="Not helpful">${ic('thumb', 'sm flip-y')}</button>
      ${m.fb === 'up' ? '<span class="fb-thanks">Thanks — glad it helped.</span>' : ''}
      ${m.fb === 'down' && m.reasonSent ? '<span class="fb-thanks">Thanks — your feedback helps improve answers.</span>' : ''}
    </div>`;
    if (m.fb === 'down' && m.reasonOpen) {
      const reasons = ['Not accurate', "Didn't answer my question", "Source doesn't match", 'Hard to follow'];
      html += `<form class="reason-form" data-mid="${m.id}" onsubmit="return false">
        <fieldset><legend>What could be better? <span class="muted" style="font-weight:400">Optional</span></legend>
          <div class="reason-opts">${reasons.map((r, i) => `<label><input type="radio" name="reason-${m.id}" value="${esc(r)}" ${m.reason === r ? 'checked' : ''} data-change="fb-reason" data-mid="${m.id}" data-fk="r-${m.id}-${i}">${esc(r)}</label>`).join('')}</div>
        </fieldset>
        <div class="field"><label for="rt-${m.id}">Anything else? <span class="muted" style="font-weight:400">Optional</span></label>
          <textarea class="textarea" id="rt-${m.id}" rows="2" data-input="fb-text" data-mid="${m.id}" data-fk="rt-${m.id}">${esc(m.reasonText || '')}</textarea></div>
        <div class="rf-actions"><button class="btn btn-quiet btn-sm" type="button" data-action="fb-skip" data-mid="${m.id}">Skip</button>
          <button class="btn btn-primary btn-sm" type="button" data-action="fb-send" data-mid="${m.id}">Send feedback</button></div>
      </form>`;
    }
    return html;
  }

  function tutorWrap(m, inner, busy = false) {
    return `<article class="msg-tutor msg-enter" id="m-${m.id}" aria-label="Smart Tutor answer">
      ${ST.logo('logo')}
      <div class="msg-body" ${busy ? 'aria-busy="true"' : ''}><span class="msg-name">Smart Tutor</span>${inner}</div></article>`;
  }

  function msgHtml(m) {
    const t = T();
    if (m.role === 'user') return `<div class="msg-user msg-enter"><span class="vh">You asked: </span>${esc(m.text)}</div>`;
    if (m.role === 'sys') return `<p class="sys-line">${esc(m.text)}</p>`;
    if (m.kind === 'answer') {
      if (m.streaming) {
        return tutorWrap(m, `<div class="stream" id="stream-${m.id}">${ST.mdParas(m.partial || '')}<span class="cursor" aria-hidden="true"></span></div>`, true);
      }
      return tutorWrap(m, `${ST.mdParas(m.partial != null && m.stopped ? m.partial : m.text)}
        ${m.stopped ? `<p class="small muted">${ic('stop', 'sm')} You stopped this answer.</p>` : ''}
        ${citesHtml(m)}${feedbackHtml(m)}`);
    }
    if (m.kind === 'unsure') {
      return tutorWrap(m, `<div class="tutor-card">
        <p>Which subject is this about?</p>
        <div class="tc-actions">${S.enrolled.map((s) => `<button class="btn btn-secondary" type="button" data-action="pick-subject" data-subject="${esc(s)}" data-fk="pick-${esc(s)}" ${m.done ? 'disabled' : ''}>${ST.subjectIcon(s)}${esc(s)}</button>`).join('')}</div>
      </div>`);
    }
    if (m.kind === 'decline') {
      return tutorWrap(m, `<div class="tutor-card decline">
        <p>This conversation is about <em>${esc(m.subject)}</em>. Please ask a question about <em>${esc(m.subject)}</em>, or start a new conversation for other topics.</p>
        <div class="tc-actions"><button class="btn btn-secondary" type="button" data-action="new-conv-from" data-mid="${m.id}">${ic('plus', 'sm')}New conversation</button></div>
      </div>`);
    }
    if (m.kind === 'error') {
      return tutorWrap(m, `<div class="tutor-card error" role="alert">
        <p class="tc-head">${ic('alertCircle', 'sm')}This answer didn't come through.</p>
        <p class="small muted">Something went wrong while the tutor was answering. Your question is saved, so you can try again.</p>
        <div class="tc-actions"><button class="btn btn-secondary" type="button" data-action="retry" data-mid="${m.id}" data-fk="retry">${ic('retry', 'sm')}Retry</button></div>
      </div>`);
    }
    return '';
  }

  function headerHtml() {
    const t = T();
    const note = t.noteId ? ST.note(t.noteId) : null;
    const hasAnswer = t.messages.some((m) => m.kind === 'answer' && !m.streaming);
    const sub = t.subject
      ? `<span class="subject-chip">${ST.subjectChip(t.subject, 'chip-accent')}<button class="btn btn-ghost btn-sm" type="button" data-action="change-subject" data-fk="change" ${t.readOnly || t.streaming ? 'disabled' : ''} aria-label="Change subject (restarts the conversation)">Change</button></span>`
      : `<span>The tutor detects the subject from your first question.</span>`;
    const noteLink = note ? `<span class="th-sep" aria-hidden="true"></span><a href="#/note/${note.id}" class="od-row" style="--od-gap:6px">${ic('note', 'sm')}<span class="od-truncate">Lesson note: ${esc(note.title)}</span></a>` : '';
    let summarize = '';
    if (hasAnswer && t.readOnly !== 'archived') {
      if (t.summarizing) summarize = `<button class="btn btn-secondary" type="button" disabled data-fk="summ"><span class="spinner" aria-hidden="true"></span>Summarizing…</button>`;
      else summarize = `<button class="btn btn-secondary" type="button" data-action="summarize" data-fk="summ" ${t.readOnly || t.streaming ? 'disabled' : ''}>${ic('note', 'sm')}${note ? 'Update lesson note' : 'Summarize lesson'}</button>`;
    }
    const archiveBtn = t.convId && !t.readOnly ? `<button class="icon-btn" type="button" data-action="archive-thread" aria-label="Archive conversation" title="Archive conversation">${ic('archive')}</button>` : '';
    return `<header class="thread-head">
      <div class="th-title">
        <h1 class="od-truncate">${esc(t.title)}</h1>
        <div class="th-sub">${sub}${noteLink}</div>
      </div>
      <div class="th-actions">
        <button class="switch" type="button" role="switch" aria-checked="${S.citations}" data-action="toggle-citations" data-fk="cit-switch">
          <span class="track" aria-hidden="true"></span>Show citations<span class="state" aria-hidden="true">${S.citations ? 'On' : 'Off'}</span>
        </button>
        ${summarize ? '<span class="th-sep" aria-hidden="true"></span>' + summarize : ''}
        ${archiveBtn}
      </div>
    </header>`;
  }

  function summaryCard() {
    const t = T();
    if (t.summarizing) {
      return `<div class="tutor-card" role="status">
        <p class="tc-head"><span class="spinner" aria-hidden="true"></span>Summarizing this lesson into a note…</p>
        <div class="progress" aria-hidden="true"><span></span></div>
        <p class="small muted">This usually takes a few seconds. You can keep reading while it works.</p>
      </div>`;
    }
    if (t.summaryDone && t.noteId) {
      const n = ST.note(t.noteId);
      return `<div class="banner banner-success" role="status">${ic('checkCircle')}
        <div class="b-body"><strong>${t.summaryDone === 'updated' ? 'Lesson note updated' : 'Lesson note saved'}</strong><span>${esc(n.title)}</span></div>
        <a class="btn btn-secondary btn-sm" href="#/note/${n.id}">Open note</a></div>`;
    }
    return '';
  }

  function composerHtml() {
    const t = T();
    let banner = '';
    let disabled = false, placeholder = 'Ask a question…';
    if (t.readOnly === 'left') {
      disabled = true; placeholder = 'Read-only conversation';
      banner = `<div class="banner">${ic('lock')}<div class="b-body"><strong>This conversation is read-only.</strong><span>Enroll in <em>${esc(t.subject)}</em> again to continue.</span></div>
        <button class="btn btn-primary btn-sm" type="button" data-action="re-enroll">Enroll in ${esc(t.subject)}</button></div>`;
    } else if (t.readOnly === 'archived') {
      disabled = true; placeholder = 'Archived conversation';
      banner = `<div class="banner">${ic('archive')}<div class="b-body"><strong>This conversation is archived.</strong><span>Restore to continue.</span></div>
        <button class="btn btn-primary btn-sm" type="button" data-action="restore-thread">${ic('restore', 'sm')}Restore</button></div>`;
    } else if (t.rateLimit > 0) {
      disabled = true; placeholder = 'Sending is paused for a moment';
      banner = `<div class="banner banner-warn">${ic('clock')}<div class="b-body"><strong>Too many messages in a short time.</strong><span>Try again in <span id="rl-count" class="mono">${t.rateLimit}</span> seconds.</span></div></div>`;
    }
    const streaming = !!t.streaming;
    const btn = streaming
      ? `<button class="btn btn-secondary" type="button" data-action="stop" data-fk="stop">${ic('stop', 'sm')}Stop</button>`
      : `<button class="btn btn-primary send" type="button" data-action="send" data-fk="send" aria-label="Send question" ${disabled ? 'disabled' : ''}>${ic('send')}</button>`;
    return `<div class="composer-wrap"><div class="composer-inner">
      ${banner}
      <div class="composer ${disabled ? 'disabled' : ''}">
        <label class="vh" for="composer-input">Ask the tutor</label>
        <textarea id="composer-input" rows="1" placeholder="${placeholder}" data-input="draft" data-fk="composer" ${disabled ? 'disabled' : ''} ${t.messages.length === 0 && !disabled ? 'data-autofocus' : ''}>${esc(t.draft)}</textarea>
        ${btn}
      </div></div></div>`;
  }

  function statusHtml() {
    const t = T();
    return `<div class="status-wrap"><div class="status-line">
      <span class="tokens mono" id="token-line">Tokens: ${ST.num(t.tokens[0])} in · ${ST.num(t.tokens[1])} out</span>
      <span>Enter to send · Shift + Enter for a new line</span>
    </div></div>`;
  }

  function emptyHtml() {
    const subjects = ST.SUBJECTS.filter((s) => S.enrolled.includes(s.id));
    return `<div class="chat-empty">
      <div><h2>What would you like to learn today?</h2>
        <p class="lede">Ask about any of your subjects. The tutor works out which subject your question belongs to and answers only from that subject's documents.</p></div>
      <div class="examples">${subjects.map((s) => `<section class="example-group" aria-labelledby="ex-${s.icon}">
        <h3 id="ex-${s.icon}">${ST.subjectIcon(s.id)}${esc(s.name)}</h3>
        ${s.examples.map((q) => `<button class="example" type="button" data-action="example" data-q="${esc(q)}">${esc(q)}</button>`).join('')}
      </section>`).join('')}</div>
    </div>`;
  }

  ST.chatView = () => {
    const t = T();
    const fromNote = t.fromNote ? ST.note(t.fromNote) : null;
    const body = t.messages.length === 0 && !fromNote ? emptyHtml()
      : `<div class="thread" id="thread">
          ${fromNote ? `<div class="banner banner-info">${ic('note')}<div class="b-body">Started from note: <a href="#/note/${fromNote.id}"><em>${esc(fromNote.title)}</em></a></div></div>` : ''}
          ${t.messages.length === 0 ? `<p class="muted">Ask a question about <em>${esc(t.subject)}</em> to discuss this note.</p>` : ''}
          ${t.messages.map(msgHtml).join('')}
          ${summaryCard()}
        </div>`;
    return ST.shell({ nav: t.convId ? 'conversations' : 'chat', currentConv: t.convId, content: `<div class="chat">
      ${headerHtml()}
      <div class="thread-scroll" data-keep-scroll="thread" id="thread-scroll">${body}</div>
      ${composerHtml()}
      ${statusHtml()}
    </div>` });
  };

  const scrollBottom = (force = false) => {
    const el = document.getElementById('thread-scroll');
    if (!el) return;
    if (force || el.scrollHeight - el.scrollTop - el.clientHeight < 160) el.scrollTop = el.scrollHeight;
  };
  ST.chatAfter = () => { autosize(); };
  ST.chatEnter = () => { scrollBottom(true); };
  function autosize() {
    const ta = document.getElementById('composer-input');
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  }

  /* ---------- streaming ---------- */
  let streamTimer = null;
  ST.stopStream = (silent) => {
    if (streamTimer) { clearInterval(streamTimer); streamTimer = null; }
    const t = T();
    if (!t || !t.streaming) return;
    const m = t.messages.find((x) => x.id === t.streaming);
    if (m) { m.streaming = false; m.stopped = true; }
    t.streaming = null;
    if (!silent) { finishTokens(m, true); ST.announce('Answer stopped.'); ST.render(); }
  };
  function finishTokens(m, partial) {
    const t = T();
    const len = partial ? (m.partial || '').length : m.text.length;
    t.tokens[0] += 2140 + Math.round(t.messages.length * 180);
    t.tokens[1] += Math.round(len / 4);
    const c = t.convId && ST.conv(t.convId);
    if (c) c.tokens = t.tokens.slice();
  }
  ST.streamAnswer = (key, { startAt = 0, speed = 45 } = {}) => {
    const t = T();
    const m = answerMsg(key, { streaming: true, partial: '' });
    t.messages.push(m);
    t.streaming = m.id;
    const words = m.text.split(/(\s+)/);
    let i = Math.floor(words.length * startAt);
    m.partial = words.slice(0, i).join('');
    ST.render();
    scrollBottom(true);
    ST.announce('Smart Tutor is answering.');
    streamTimer = setInterval(() => {
      i += 2;
      m.partial = words.slice(0, i).join('');
      const node = document.getElementById('stream-' + m.id);
      if (node) { node.innerHTML = ST.mdParas(m.partial) + '<span class="cursor" aria-hidden="true"></span>'; scrollBottom(); }
      if (i >= words.length) {
        clearInterval(streamTimer); streamTimer = null;
        m.streaming = false; m.partial = null; t.streaming = null;
        finishTokens(m, false);
        ST.render();
        scrollBottom();
        ST.announce('Answer ready' + (S.citations && m.cites.length ? `, with ${m.cites.length} source${m.cites.length > 1 ? 's' : ''}.` : '.'));
      }
    }, speed);
  };

  /* ---------- asking ---------- */
  function ensureConv(q) {
    const t = T();
    if (t.convId) return;
    const id = 'c' + (S.convs.length + 10);
    t.convId = id; t.title = q;
    S.convs.push({ id, title: q, subject: t.subject, last: ST.TODAY + 'T11:02', noteId: null, archived: false, tokens: t.tokens, answer: null });
  }
  ST.ask = (q) => {
    const t = T();
    q = q.trim();
    if (!q || t.streaming || t.readOnly || t.rateLimit > 0) return;
    t.draft = '';
    t.messages.push(M({ role: 'user', text: q }));
    if (t.title === 'New conversation') t.title = q;
    if (!t.subject) {
      const s = ST.classify(q);
      if (!s || !S.enrolled.includes(s)) {
        t.messages.push(M({ role: 'tutor', kind: 'unsure', question: q }));
        ST.render(); scrollBottom(true);
        ST.announce('Which subject is this about?');
        return;
      }
      t.subject = s;
      ensureConv(q);
      ST.conv(t.convId).subject = s;
      t.messages.push(M({ role: 'sys', text: `Subject set to ${s} from your question.` }));
      ST.streamAnswer(ST.pickAnswer(q, s));
      return;
    }
    ensureConv(q);
    const s = ST.classify(q);
    if (s && s !== t.subject) {
      t.messages.push(M({ role: 'tutor', kind: 'decline', subject: t.subject, question: q }));
      t.tokens[0] += 640; t.tokens[1] += 38;
      ST.render(); scrollBottom(true);
      ST.announce(`This conversation is about ${t.subject}.`);
      return;
    }
    ST.streamAnswer(ST.pickAnswer(q, t.subject));
  };

  const findMsg = (el) => T().messages.find((m) => m.id === el.dataset.mid);

  Object.assign(ST.actions, {
    draft: (el) => { T().draft = el.value; autosize(); },
    send: () => ST.ask(T().draft),
    example: (el) => ST.ask(el.dataset.q),
    stop: () => ST.stopStream(false),
    'toggle-citations': () => {
      S.citations = !S.citations;
      ST.ls.set('st_citations', S.citations ? 'on' : 'off');
      ST.render();
      ST.announce(S.citations ? 'Citations shown.' : 'Citations hidden.');
    },
    cite: (el) => {
      const c = findMsg(el).cites[+el.dataset.ci];
      ST.openDialog({
        title: `${esc(c.doc)}, p. ${c.page}`,
        body: `${c.archived ? `<div class="banner banner-warn">${ic('archive')}<div class="b-body">This document is archived. The citation stays so you can see where the answer came from.</div></div>` : ''}
          <p class="label">Excerpt</p><blockquote style="margin:0;padding:12px 16px;background:var(--surface-2);border-radius:6px;color:var(--text)">${esc(ST.EXCERPTS[c.doc] || '')}</blockquote>`,
        actions: [{ label: 'Close', cls: 'btn-primary', autofocus: true }]
      });
    },
    'fb-up': (el) => { const m = findMsg(el); m.fb = m.fb === 'up' ? null : 'up'; m.reasonOpen = false; ST.render(); },
    'fb-down': (el) => { const m = findMsg(el); if (m.fb === 'down') { m.fb = null; m.reasonOpen = false; m.reasonSent = false; } else { m.fb = 'down'; m.reasonOpen = true; m.reasonSent = false; } ST.render(); if (m.reasonOpen) { const r = document.querySelector(`[data-fk="r-${m.id}-0"]`); if (r) r.focus(); } },
    'fb-reason': (el) => { findMsg(el).reason = el.value; },
    'fb-text': (el) => { findMsg(el).reasonText = el.value; },
    'fb-skip': (el) => { const m = findMsg(el); m.reasonOpen = false; m.reasonSent = true; ST.render(); const b = document.querySelector(`[data-fk="down-${m.id}"]`); if (b) b.focus(); },
    'fb-send': (el) => { const m = findMsg(el); m.reasonOpen = false; m.reasonSent = true; ST.render(); ST.announce('Feedback sent.'); const b = document.querySelector(`[data-fk="down-${m.id}"]`); if (b) b.focus(); },
    'pick-subject': (el) => {
      const t = T();
      const m = t.messages.find((x) => x.kind === 'unsure' && !x.done);
      if (!m) return;
      m.done = true;
      t.subject = el.dataset.subject;
      ensureConv(m.question);
      ST.conv(t.convId).subject = t.subject;
      t.messages.push(M({ role: 'sys', text: `Subject set to ${t.subject}.` }));
      ST.streamAnswer(ST.pickAnswer(m.question, t.subject));
    },
    'new-conv-from': (el) => { ST.pendingDraft = findMsg(el).question; ST.goto('chat-empty'); },
    retry: (el) => { const t = T(); t.messages = t.messages.filter((m) => m.id !== el.dataset.mid); const q = [...t.messages].reverse().find((m) => m.role === 'user'); ST.streamAnswer(ST.pickAnswer(q.text, t.subject)); },
    'change-subject': () => {
      const t = T();
      const others = S.enrolled.filter((s) => s !== t.subject);
      let choice = others[0];
      ST.openDialog({
        title: 'Change subject',
        body: `<p>Changing the subject restarts this conversation under the subject you choose. This conversation stays in Conversations.</p>
          <fieldset style="border:0;margin:0;padding:0;display:grid;gap:8px"><legend class="label" style="margin-bottom:8px">Subject</legend>
          ${S.enrolled.map((s) => `<label class="radio"><input type="radio" name="chg" value="${esc(s)}" ${s === t.subject ? 'disabled' : ''} ${s === choice ? 'checked' : ''}>${ST.subjectIcon(s)}<span class="od-fill">${esc(s)}</span>${s === t.subject ? '<span class="badge">Current</span>' : ''}</label>`).join('')}
          </fieldset>`,
        actions: [
          { label: 'Cancel' },
          { label: 'Restart conversation', cls: 'btn-primary', autofocus: true, onClick: (dlg) => {
            const v = dlg.querySelector('input[name="chg"]:checked');
            choice = v ? v.value : choice;
            const first = t.messages.find((m) => m.role === 'user');
            ST.pendingThread = ST.newThread({ subject: choice, draft: first ? first.text : '' });
            ST.goto('chat-empty');
            ST.toast(`New conversation under ${choice}. Your question is ready to send.`);
          } }
        ]
      });
    },
    summarize: () => {
      const t = T();
      if (t.noteId) {
        const n = ST.note(t.noteId);
        ST.openDialog({
          title: 'Update lesson note?',
          body: `<p>This replaces <strong>${esc(n.title)}</strong> with a new summary of the whole conversation.</p>
            <div class="banner banner-warn">${ic('alert')}<div class="b-body">The previous version is overwritten, including any edits you made to the note.</div></div>`,
          actions: [{ label: 'Cancel', autofocus: true }, { label: 'Update note', cls: 'btn-primary', onClick: () => startSummary('updated') }]
        });
      } else startSummary('saved');
    },
    'archive-thread': () => {
      const t = T(); const c = ST.conv(t.convId);
      c.archived = true; t.readOnly = 'archived'; ST.render();
      ST.toast('Conversation archived.', { undo: () => { c.archived = false; t.readOnly = null; ST.render(); } });
    },
    'restore-thread': () => {
      const t = T(); const c = ST.conv(t.convId);
      if (c) c.archived = false; t.readOnly = null; ST.render();
      ST.toast('Conversation restored.');
      const i = document.getElementById('composer-input'); if (i) i.focus();
    },
    're-enroll': () => {
      const t = T();
      if (!S.enrolled.includes(t.subject)) S.enrolled.push(t.subject);
      t.readOnly = null; ST.render();
      ST.toast(`Enrolled in ${t.subject}. You can continue this conversation.`);
      const i = document.getElementById('composer-input'); if (i) i.focus();
    }
  });

  function startSummary(kind) {
    const t = T();
    t.summarizing = true; t.summaryDone = false;
    ST.render(); scrollBottom(true);
    ST.announce('Summarizing this lesson.');
    if (t.summaryHold) return;
    ST.later(() => completeSummary(kind), 3200);
  }
  function completeSummary(kind) {
    const t = T();
    t.summarizing = false;
    if (!t.noteId) {
      const id = 'n' + (S.notes.length + 10);
      const first = t.messages.find((m) => m.role === 'user');
      ensureConv(first ? first.text : 'Lesson');
      S.notes.push({ id, title: first ? first.text.replace(/\?$/, '') : 'Lesson note', subject: t.subject, date: ST.TODAY + 'T11:05', convId: t.convId, archived: false, body: `# ${first ? first.text : 'Lesson note'}\n\n${t.messages.filter((m) => m.kind === 'answer').map((m) => m.text).join('\n\n')}` });
      t.noteId = id;
      const c = ST.conv(t.convId); if (c) c.noteId = id;
    }
    t.summaryDone = kind;
    t.tokens[0] += 3120; t.tokens[1] += 486;
    ST.render(); scrollBottom(true);
    ST.announce(kind === 'updated' ? 'Lesson note updated.' : 'Lesson note saved.');
  }
  ST.completeSummary = completeSummary;

  /* Enter sends, Shift+Enter adds a line. */
  document.addEventListener('keydown', (e) => {
    if (e.target.id === 'composer-input' && e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ST.ask(T().draft); }
  });

  ST.startRateLimit = (secs) => {
    const t = T();
    t.rateLimit = secs;
    ST.every(() => {
      if (t.rateLimit <= 0) return;
      t.rateLimit -= 1;
      const el = document.getElementById('rl-count');
      if (t.rateLimit <= 0) { ST.render(); ST.announce('You can send messages again.'); }
      else if (el) el.textContent = t.rateLimit;
    }, 1000);
  };

  ST.goto = (id) => {
    if (location.hash === '#/' + id) ST.route(); else location.hash = '#/' + id;
  };

  ST.dynamicConversation = (cid) => {
    const c = ST.conv(cid) || ST.conv('c1');
    return {
      id: 'open/' + c.id, fixed: false, label: 'conversation · ' + c.id, desc: 'Opened from Conversations — the full history with its linked lesson note.',
      setup: () => {
        S.thread = ST.threadFromConv(c.id);
        if (!S.enrolled.includes(c.subject)) S.thread.readOnly = 'left';
        if (c.archived) S.thread.readOnly = 'archived';
      },
      view: ST.chatView, afterRender: ST.chatAfter, afterEnter: ST.chatEnter
    };
  };
})();
