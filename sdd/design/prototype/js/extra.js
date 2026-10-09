/* Smart Tutor v0.10 — overview with what changed and the flows, R2 research map and R3 learning loop
   wireframes, components page (§10), decisions and questions for the brief owner (§11.5). */
(function () {
  const ST = window.ST;
  const S = ST.S;
  const esc = ST.esc, ic = ST.ic;

  /* =========================================================
     Overview
     ========================================================= */
  /* §0 What changed in v0.10: [source, change, states redone or added, states removed]. Chat only. */
  ST.CHANGES = [
    ['P1', 'Conversation panel (260px): Documents used, Lesson Note, Actions; header = toggle, title, overflow', ['chat-answer-citations', 'chat-documents-used', 'chat-documents-used-empty', 'chat-documents-used-deleted', 'chat-summarize-done', 'chat-update-note', 'chat-panel-collapsed'], []],
    ['P2', 'One click opens the document beside the conversation (split view)', ['viewer-citation-highlight', 'viewer-document'], []],
    ['P3', 'The pane: a labelled region with one 40px toolbar; loading, error and no-highlight inside it', ['viewer-no-highlight', 'viewer-loading', 'viewer-error'], []],
    ['P3', 'Outside chat the viewer stays the overlay', ['viewer-archived'], []]
  ];
  ST.CHANGES.push(['P4', 'Open in dialog from the pane, with a details strip', ['viewer-dialog'], []], ['P5', 'Choose the conversation\'s documents; Only search these documents', ['chat-documents-add', 'chat-scope-limited', 'chat-decline-limited', 'chat-documents-used'], []]);
  ST.CHANGES.unshift(['P8', 'v0.11: the nav collapse chevron moves to a 40px brand row at the top, aligned with the chat header; below the logo on the rail', ['shell-nav-collapsed', 'library-default', 'chat-answer-citations'], []]);
  ST.NEW_IDS = ['chat-panel-collapsed', 'viewer-dialog', 'chat-documents-add', 'chat-scope-limited', 'chat-decline-limited', 'chat-new-from-document', 'chat-title-editing'];
  const changed = () => { const set = new Set(); ST.CHANGES.forEach((c) => c[2].forEach((id) => set.add(id))); return set; };
  ST.indexView = () => {
    const groups = [];
    const ch = changed();
    ST.STATES.forEach((s) => { if (s.id === 'index') return; let g = groups.find((x) => x.name === s.group); if (!g) { g = { name: s.group, ref: s.ref || '', items: [] }; groups.push(g); } g.items.push(s); });
    return `<main class="index-page" id="main-content" tabindex="-1">
      <section class="index-hero">
        <div><span class="brand" style="padding:0 0 24px">${ST.logo('logo', 'Smart Tutor logo')}<span class="word">Smart Tutor</span></span>
          <h1>Round 11: the nav toggle at the top</h1>
          <p>Brief v0.11 moves the nav collapse chevron to a 40px brand row at the top, aligned with the chat header (P8). From v0.10: A 260px conversation panel holds Documents used, the Lesson Note and the conversation's actions, and one click on a Sources chip or a document opens it beside the conversation: the conversation keeps at least 480px, the panel collapses and the nav drops to its rail. Everything else is the round 9 design.</p>
          <div class="od-cluster" style="margin-top:24px;--od-gap:12px">
            <button class="btn btn-primary btn-lg" type="button" data-action="start-flow" data-flow="J1">Start with J1 · First run${ic('arrowRight', 'sm')}</button>
            <a class="btn btn-secondary btn-lg" href="#/library-default">Open the Library</a>
            <a class="btn btn-ghost btn-lg" href="#/brief-questions">Questions for the brief</a>
          </div></div>
        <dl class="meta">
          <div><dt>Brief</dt><dd>v0.11 · #163</dd></div><div><dt>Owner</dt><dd>Thao Dinh</dd></div><div><dt>Date</dt><dd>9 Oct 2026</dd></div>
          <div><dt>Screens</dt><dd>Laptop, 1280–1920 px</dd></div><div><dt>Themes</dt><dd>Light and dark</dd></div><div><dt>States</dt><dd>${ST.STATES.length - 1}</dd></div>
          <div><dt>Round 1</dt><dd><a href="v0.2/index.html">v0.2 prototype</a></dd></div>
        </dl>
      </section>

      <h2 class="section-title">What changed in v0.11 and v0.10</h2>
      <div class="changes" role="table" aria-label="Decisions and the states they changed">
        ${ST.CHANGES.map(([id, title, states, removed]) => `<div class="change-row" role="row"><span class="qid" role="cell">${esc(id)}</span><span class="change-title" role="cell">${esc(title)}</span>
          <span class="change-states" role="cell">${states.length ? '' : '<span class="small muted">No state changes</span>'}${states.map((sid) => `<a href="#/${sid}"><code>${sid}</code>${ST.NEW_IDS.includes(sid) ? '<span class="badge badge-note">New</span>' : ''}</a>`).join('')}${(removed || []).map((sid) => `<span class="removed-id"><del><code>${sid}</code></del><span class="badge badge-archived">Removed</span></span>`).join('')}</span></div>`).join('')}
        <div class="change-row" role="row"><span class="qid" role="cell">§11.6</span><span class="change-title" role="cell">Prototype contract</span><span class="change-states" role="cell"><span class="small muted">Every state: one user story in <code class="mono">ref</code>, <code class="mono">?shot=1</code> hides the review bar.</span></span></div>
      </div>

      <h2 class="section-title">Review flows</h2>
      <div class="flow-grid">${ST.FLOWS.map((f) => `<section class="flow-card" aria-labelledby="fl-${f.id}">
        <h3 id="fl-${f.id}"><code>${f.id}</code>${esc(f.title)}</h3><p class="small muted">${esc(f.summary)}</p>
        <ol>${f.steps.map((s) => `<li><a href="#/${s.state}" data-action="start-flow-at" data-flow="${f.id}">${esc(s.text)}</a></li>`).join('')}</ol>
        <button class="btn btn-secondary" type="button" data-action="start-flow" data-flow="${f.id}">Walk through ${f.id}${ic('arrowRight', 'sm')}</button></section>`).join('')}</div>

      <h2 class="section-title">What's new in the visual system</h2>
      <section class="direction" aria-label="Visual system additions">
        <div><h3>Subject chips</h3><div class="chips">${['llm', 'agents', 'rag', 'rl'].map((s) => ST.schip(s)).join('')}</div><p class="small muted">One chip everywhere, with a stable colour per subject. The text always meets AA contrast and the name is always shown.</p></div>
        <div><h3>Document states</h3><div class="od-stack" style="--od-gap:6px;align-items:flex-start">${['processing', 'choose', 'ready', 'failed'].map((st) => ST.stateBadge({ state: st, subjects: [], attempts: 1, failReason: '' }, false)).join('')}${ST.stateBadge({ archived: true }, false)}</div></div>
        <div><h3>Cited passage</h3><div class="vw-hl" style="margin:8px 0 0"><span class="vw-hl-label" aria-hidden="true">Cited passage</span>Reasoning traces help the model induce, track, and update action plans.</div><p class="small muted">Soft accent fill plus an outline and a label, so the highlight never relies on colour alone.</p></div>
        <div><h3>Quoted material</h3><figure class="excerpt"><blockquote>“An attention function can be described as mapping a query and a set of key-value pairs to an output…”</blockquote><figcaption>Quoted from your document</figcaption></figure></div>
      </section>

      <h2 class="section-title">All states</h2>
      <div class="index-groups">${groups.map((g) => `<section class="index-group ${g.items.length > 12 ? 'span2' : ''}" aria-labelledby="g-${g.items[0].id}">
        <h2 id="g-${g.items[0].id}">${esc(g.name)}<span class="ig-ref">${esc(g.ref)}</span></h2>
        <ul>${g.items.map((s) => `<li><a href="#/${s.id}"><code>${s.id}@${ST.BRIEF}</code>${ST.NEW_IDS.includes(s.id) ? '<span class="badge badge-note">New in v0.10</span>' : ch.has(s.id) ? '<span class="badge">Changed in v0.10</span>' : ''}<span>${esc(s.desc)}</span></a></li>`).join('')}</ul></section>`).join('')}</div>
    </main>`;
  };
  ST.actions['start-flow-at'] = (el, e) => { ST.flow = el.dataset.flow; try { sessionStorage.setItem('st3_flow', ST.flow); } catch (x) {} };

  /* =========================================================
     Wireframe helpers
     ========================================================= */
  const wfBanner = (rel, ref) => `<div class="banner banner-wf" style="margin-bottom:24px">${ic('info')}<div class="b-body"><strong>Release ${rel} · low-fidelity wireframe</strong><span>Agrees structure and navigation only (${ref}). No visual polish yet.</span></div></div>`;
  const wfPage = (nav, rel, ref, inner) => ST.shell({ nav, content: `<div class="page wf">${wfBanner(rel, ref)}${inner}</div>` });
  const wfTools = (extra = '') => `<div class="wf-box wf-solid" style="display:flex;flex-wrap:wrap;gap:16px;align-items:center"><span>[Subject ▾]</span><span>[From ▾]</span><span>[To ▾]</span>${extra}<span class="wf-note" style="margin-left:auto">Same filter bar as Library</span></div>
    <div style="display:flex;gap:24px;margin:16px 0;border-bottom:1.5px dashed var(--wf-line);padding-bottom:8px"><strong>Active (n)</strong><span class="muted">Archived (n)</span></div>`;

  /* ---------- R2 research map ---------- */
  ST.R2 = { subject: 'agents', node: 'd3' };
  const MAPWORKS = { agents: [['d2', 2022], ['d3', 2022], ['d5', 2023]], llm: [['d1', 2017], ['d2', 2022], ['d5', 2023]] };
  const short = (id) => ({ d1: 'Attention Is All You Need', d2: 'Chain-of-Thought Prompting…', d3: 'ReAct', d5: 'Toolformer', d6: 'Agentic Design Patterns', d8: 'Proximal Policy Optimization…' }[id]);
  const subjSelect = () => `<div class="od-row" role="radiogroup" aria-label="Subject" style="margin-bottom:16px">${['agents', 'llm', 'rag', 'rl'].map((s) => `<button class="wf-btn ${ST.R2.subject === s ? 'primary' : ''}" type="button" role="radio" aria-checked="${ST.R2.subject === s}" data-action="r2-subj" data-s="${s}">${esc(ST.sname(s))}</button>`).join('')}</div>`;
  ST.actions['r2-subj'] = (el) => { ST.R2.subject = el.dataset.s; if (['rag', 'rl'].includes(el.dataset.s)) ST.goto('r2-sparse-map'); else if (ST.current.id === 'r2-sparse-map') ST.goto('r2-map'); else ST.render(); };
  ST.r2Map = () => {
    const works = MAPWORKS[ST.R2.subject] || MAPWORKS.agents;
    const years = [2017, 2020, 2022, 2023, 2024];
    return wfPage('map', 2, 'US-19, US-20', `
      <div class="page-head"><div><h1>Research map</h1><p>How your papers in one subject connect: a timeline, citation links between works you hold, and a reading order.</p></div>
        <div class="od-row"><a class="wf-btn" href="#/r2-reading-order">Reading order</a><a class="wf-btn primary" href="#/r2-ask-path">Ask about a reading path</a></div></div>
      ${subjSelect()}
      <div class="wf-map" aria-label="Timeline of works">
        ${years.map((y) => `<div class="wf-year"><span>${y}</span>${works.filter((w) => w[1] === y).map(([id]) => `<button class="wf-node" type="button" data-action="r2-node" data-id="${id}" aria-pressed="${ST.R2.node === id}">${esc(short(id))}<br><span class="wf-note">1 file</span></button>`).join('') || '<span class="wf-note">—</span>'}</div>`).join('')}
        <div class="wf-axis"><span>older</span><span>Year →</span><span>newer</span></div>
        <div class="wf-arrows"><span>→ ReAct cites Chain-of-Thought Prompting</span><span>→ other arrows appear when citation links are found between works you hold</span></div>
      </div>
      <div class="wf-box" style="margin-top:16px"><strong>Works without a year</strong><span>Agentic Design Patterns (book) · <span class="wf-note">shown here, not on the timeline</span></span></div>
      <p class="wf-note" style="margin-top:12px">Several files of the same paper collapse into one node, labelled “2 files”. Selecting a node opens Work details.</p>`);
  };
  ST.actions['r2-node'] = (el) => { ST.R2.node = el.dataset.id; ST.goto('r2-work-details'); };
  ST.r2Work = () => {
    const d = ST.doc(ST.R2.node) || ST.doc('d3');
    return wfPage('map', 2, 'US-19', `
      <div class="page-head"><div><h1>Work details</h1></div><a class="wf-btn" href="#/r2-map">${ic('arrowLeft', 'sm')}Back to map</a></div>
      <div style="display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:24px;align-items:start">
        <div class="wf-box"><strong style="font-size:20px">${esc(d.title)}</strong><span>${esc(d.authors || '')} · ${d.year || 'no year'}</span>
          <span class="wf-note">Your file(s): ${esc(d.file)}</span>
          <div class="wf-line" style="width:90%"></div><div class="wf-line" style="width:70%"></div></div>
        <div class="wf-grid">
          <div class="wf-box"><strong>Cites (in your library)</strong><span>Chain-of-Thought Prompting… <a href="#/r2-map">[open citing passage, p. 2]</a></span></div>
          <div class="wf-box"><strong>Cited by (in your library)</strong><span class="wf-note">No works in your library cite this one yet.</span></div>
        </div></div>`);
  };
  ST.r2Reading = () => wfPage('map', 2, 'US-20', `
    <div class="page-head"><div><h1>Reading order · ${esc(ST.sname('agents'))}</h1><p>Foundational works first. Each step says why it's there.</p></div><a class="wf-btn" href="#/r2-map">${ic('arrowLeft', 'sm')}Map</a></div>
    <ol class="wf-grid" style="max-width:760px;list-style:none;padding:0">
      ${[['Chain-of-Thought Prompting…', '2022', 'Cited by 1 later paper in your library'], ['ReAct', '2022', 'Builds on step 1: adds actions to reasoning'], ['Toolformer', '2023', 'Newest work; extends tool use'], ['Agentic Design Patterns', 'book', 'No year; read alongside for practice']].map(([t, y, r], i) => `<li class="wf-box" style="grid-template-columns:40px minmax(0,1fr);display:grid"><strong style="font-size:24px">${i + 1}</strong><span><strong>${t}</strong> · ${y}<br><span class="wf-note">${r}</span></span></li>`).join('')}
    </ol>`);
  ST.r2Ask = () => wfPage('map', 2, 'US-20', `
    <div class="page-head"><div><h1>Ask about a reading path</h1><p>From the map: “How did <em>idea</em> develop?”</p></div><a class="wf-btn" href="#/r2-map">${ic('arrowLeft', 'sm')}Map</a></div>
    <div class="wf-box wf-solid" style="max-width:760px;display:flex;gap:12px;align-items:center"><span style="flex:1">How did <u>tool use in agents</u> develop?</span><button class="wf-btn primary" type="button">Ask</button></div>
    <div class="wf-box" style="max-width:760px;margin-top:16px"><strong>Opens a chat answer that walks the works in order:</strong>
      <span>1 · Chain-of-Thought Prompting (2022): reasoning written out step by step <span class="wf-tag">[cite p. 2]</span></span>
      <span>2 · ReAct (2022): reasoning interleaved with tool actions <span class="wf-tag">[cite p. 3]</span></span>
      <span>3 · Toolformer (2023): the model learns when to call tools <span class="wf-tag">[cite p. 1]</span></span>
      <span class="wf-note">Normal chat rules apply: documents used, citations switch and status line.</span></div>`);
  ST.r2Sparse = () => wfPage('map', 2, 'US-19', `
    <div class="page-head"><div><h1>Research map</h1></div></div>${subjSelect()}
    <div class="wf-box" style="justify-items:center;text-align:center;padding:48px">
      <strong style="font-size:20px">Not enough to map yet</strong>
      <span>You have 1 work in ${esc(ST.sname(ST.R2.subject))}. Add more papers in this subject to see how they connect.</span>
      <a class="wf-btn primary" href="#/library-default">Go to Library</a></div>
    <p class="wf-note" style="margin-top:12px">Same message when 2+ works exist but no citation links were found: “We didn't find citations between these works.”</p>`);

  /* ---------- R3 learning loop ---------- */
  ST.R3 = { picked: ['n1', 'n3'] };
  ST.r3Select = () => {
    const notes = S.notes.filter((n) => !n.archived); const k = ST.R3.picked.length;
    return wfPage('notes', 3, 'US-14', `
      <div class="page-head"><div><h1>Notes · select for a quiz</h1><p>Select 1–10 active notes.</p></div>
        <div class="od-row"><span aria-live="polite">${k} of 10 selected</span><a class="wf-btn primary" href="#/r3-quiz-generating" ${k ? '' : 'aria-disabled="true"'}>Generate quiz</a></div></div>
      ${wfTools()}
      <div class="wf-box" style="padding:0;gap:0">${notes.map((n) => `<label class="wf-row"><input type="checkbox" data-change="r3-pick" value="${n.id}" ${ST.R3.picked.includes(n.id) ? 'checked' : ''} aria-label="Select ${esc(n.title)}" style="width:18px;height:18px;accent-color:var(--text)">
        <span>${esc(n.title)}</span><span>${n.subjects.map((s) => esc(ST.sname(s))).join(', ')}</span><span>${ST.fmtDate(n.date, false)}</span><span class="wf-note">→ source</span></label>`).join('')}</div>`);
  };
  ST.actions['r3-pick'] = (el) => { ST.R3.picked = el.checked ? [...ST.R3.picked, el.value].slice(0, 10) : ST.R3.picked.filter((x) => x !== el.value); ST.render(); };
  ST.r3Generating = () => wfPage('quizzes', 3, 'US-14', `
    <div class="page-head"><div><h1>Generating your quiz…</h1><p>From 2 notes: ReAct: reasoning and acting · Dense retrieval in RAG</p></div></div>
    <div class="wf-box" style="max-width:640px" role="status"><div class="wf-bar"><span style="width:55%"></span></div><span>Writing questions… usually up to 15 seconds.</span>
      <div class="od-row"><a class="wf-btn" href="#/r3-quiz-select">Cancel</a><a class="wf-btn" href="#/r3-quiz-take">(Skip to quiz)</a></div></div>`);
  ST.r3Take = () => wfPage('quizzes', 3, 'US-14', `
    <div class="page-head"><div><h1>Quiz · ReAct &amp; retrieval</h1><p>${ST.QUIZ.length} questions · 4 options · one correct</p></div><a class="wf-btn primary" href="#/r3-quiz-results">Submit answers</a></div>
    <div class="wf-grid" style="max-width:760px">${ST.QUIZ.map((q, i) => `<fieldset class="wf-box"><legend style="padding:0 4px"><strong>Q${i + 1}.</strong> ${esc(q.q)}</legend>
      ${q.opts.map((o, j) => `<label class="wf-opt"><input type="radio" name="q${i}" ${j === q.pick && i < 3 ? 'checked' : ''} style="accent-color:var(--text)">${esc(o)}</label>`).join('')}</fieldset>`).join('')}</div>`);
  ST.r3Results = () => {
    const ok = ST.QUIZ.filter((q) => q.a === q.pick).length; const topics = {};
    ST.QUIZ.forEach((q) => { topics[q.topic] = topics[q.topic] || [0, 0]; topics[q.topic][1]++; if (q.a === q.pick) topics[q.topic][0]++; });
    return wfPage('quizzes', 3, 'US-14', `
      <div class="page-head"><div><h1>Results · ${ok} / ${ST.QUIZ.length}</h1></div><div class="od-row"><a class="wf-btn" href="#/r3-quiz-take">Retake</a><a class="wf-btn primary" href="#/r3-learn-next">What should I learn next?</a></div></div>
      <div style="display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:24px;align-items:start">
        <div class="wf-grid">${ST.QUIZ.map((q, i) => { const good = q.a === q.pick; return `<div class="wf-box"><div class="od-row" style="justify-content:space-between"><strong>Q${i + 1}. ${esc(q.q)}</strong><span class="wf-tag">${good ? '✓ Correct' : '✗ Incorrect'}</span></div>
          ${good ? '' : `<div class="wf-opt wrong">Your answer: ${esc(q.opts[q.pick])}</div>`}<div class="wf-opt correct">Correct: ${esc(q.opts[q.a])}</div><span class="wf-note">Short explanation with a citation to the source page.</span>
          <span class="wf-note">[Flag question]</span></div>`; }).join('')}</div>
        <div class="wf-box"><strong>Score per topic</strong>${Object.entries(topics).map(([t, [a, b]]) => `<div class="od-stack" style="--od-gap:4px"><span class="od-row" style="justify-content:space-between"><span>${esc(ST.sname({ 'AI Agents': 'agents', LLMs: 'llm', 'Retrieval-Augmented Generation': 'rag', 'Reinforcement Learning': 'rl' }[t] || t))}</span><span>${a}/${b}</span></span><div class="wf-bar"><span style="width:${a / b * 100}%"></span></div></div>`).join('')}</div></div>`);
  };
  ST.r3List = () => wfPage('quizzes', 3, 'US-14', `
    <div class="page-head"><div><h1>Quizzes</h1></div><a class="wf-btn primary" href="#/r3-quiz-select">New quiz from notes</a></div>${wfTools()}
    <div class="wf-box" style="padding:0;gap:0">${[['ReAct & retrieval', 'AI Agents, RAG', 'Today', '3/5'], ['Chain-of-thought', 'LLMs', '30 Sep', '4/5']].map(([t, s, d, sc]) => `<div class="wf-row" style="grid-template-columns:minmax(0,1fr) 180px 100px 80px 140px"><span>${t}</span><span>${s}</span><span>${d}</span><span>${sc}</span><span class="wf-note">[Open] [Archive]</span></div>`).join('')}</div>`);
  ST.r3Reports = () => wfPage('reports', 3, 'US-15', `
    <div class="page-head"><div><h1>Reports</h1><p>Daily and weekly, across all your subjects.</p></div><div class="od-row"><a class="wf-btn" href="#/r3-learn-next">What should I learn next?</a><button class="wf-btn primary" type="button">Generate now</button></div></div>
    ${wfTools('<span>[Daily | Weekly]</span>')}
    <div class="wf-box" style="padding:0;gap:0">${[['Daily · 3 Oct', '3 topics · 2 conversations'], ['Weekly · 22–28 Sep', '6 topics · 7 conversations · 1 quiz'], ['Daily · 2 Oct', '2 topics · 1 conversation']].map(([t, s]) => `<a class="wf-row" style="grid-template-columns:minmax(0,1fr) 320px;color:inherit;text-decoration:none" href="#/r3-report-view"><span>${t}</span><span class="wf-note">${s}</span></a>`).join('')}</div>`);
  ST.r3Report = () => wfPage('reports', 3, 'US-15', `
    <div class="page-head"><div><h1>Weekly report · 22–28 Sep</h1></div><a class="wf-btn" href="#/r3-reports">${ic('arrowLeft', 'sm')}Reports</a></div>
    <div class="wf-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="wf-box"><span class="wf-note">Conversations</span><strong style="font-size:32px">7</strong></div><div class="wf-box"><span class="wf-note">Topics learned</span><strong style="font-size:32px">6</strong></div><div class="wf-box"><span class="wf-note">Quiz average</span><strong style="font-size:32px">60%</strong></div>
      <div class="wf-box" style="grid-column:span 2"><strong>Topics learned</strong><span>LLMs: self-attention, chain-of-thought · AI Agents: ReAct · RAG: dense retrieval</span></div>
      <div class="wf-box"><strong>Weak topics</strong><span>PPO clipping (quiz 0/1)</span></div>
      <div class="wf-box" style="grid-column:1/-1"><strong>Recommendations</strong><span>→ Re-read PPO, p. 3 · → Next in reading order: Toolformer</span></div></div>`);
  ST.r3Next = () => wfPage('reports', 3, 'US-16', `
    <div class="page-head"><div><h1>What should I learn next?</h1></div></div>
    <div class="od-row" style="margin-bottom:16px"><button class="wf-btn primary" type="button">What should I learn tomorrow?</button><button class="wf-btn" type="button">…next week?</button></div>
    <div class="wf-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">${[['Reinforcement Learning', 'PPO clipped objective', 'Quiz score 0%', 'Proximal Policy Optimization…, p. 3'], ['AI Agents', 'Toolformer', 'Next in reading order', 'Toolformer, p. 1'], ['Retrieval-Augmented Generation', 'Dense vs sparse retrieval', 'Quiz score 50%', 'Retrieval-Augmented Generation…, p. 4']].map(([s, t, r, d]) => `<div class="wf-box"><span class="wf-tag" style="justify-self:start">${s}</span><strong style="font-size:18px">${t}</strong><span>Why: ${r}</span><span class="wf-note">Read: ${d}</span><a class="wf-btn primary" style="justify-self:start" href="#/chat-new">Start learning</a></div>`).join('')}</div>`);

  /* =========================================================
     Components page (§10)
     ========================================================= */
  const TOKENS = [['--bg', 'Page ground'], ['--surface', 'Surface'], ['--text', 'Text'], ['--text-2', 'Secondary text'], ['--accent', 'Accent / action'], ['--attn', 'Needs action'], ['--success', 'Ready'], ['--danger', 'Failed'], ['--subj-llm', 'Subject · LLMs'], ['--subj-agents', 'Subject · AI Agents'], ['--subj-rag', 'Subject · RAG'], ['--subj-rl', 'Subject · RL']];
  const tokenGrid = (theme) => `<div data-theme="${theme}" style="background:var(--surface);color:var(--text);padding:16px;border-radius:10px;border:1px solid var(--border)"><p class="label" style="margin-bottom:12px">${theme === 'dark' ? 'Dark' : 'Light'}</p>
    <div class="token-table" style="grid-template-columns:repeat(3,minmax(0,1fr))">${TOKENS.map(([t, l]) => `<div class="token"><span class="sw" style="background:var(${t})"></span><span><code>${t}</code>${l}</span></div>`).join('')}</div></div>`;
  const spec = (label, inner, full = false) => `<div class="specimen ${full ? 'full' : ''}"><span class="spec-label">${label}</span>${inner}</div>`;
  ST.componentsView = () => {
    const d = { id: 'dx', title: 'Toolformer: Language Models Can Teach Themselves to Use Tools', authors: 'Schick et al.', year: 2023, state: 'choose', subjects: [], attempts: 0 };
    return `<main class="index-page" id="main-content" tabindex="-1">
    <div class="page-head" style="margin-bottom:48px"><div><h1 style="font-size:48px">Components</h1><p>The compact set for v0.9 (DESIGN.md → Density). Tokens live once in <code class="mono">styles.css</code> and <code class="mono">v03.css</code>, for light and dark.</p></div><a class="btn btn-secondary" href="#/index">${ic('arrowLeft', 'sm')}Overview</a></div>

    <section class="cmp-section"><h2>Tokens</h2><p>The round 1 palette, plus an attention colour for “needs action” and one hue per subject. Chip text always uses the main text colour, so contrast holds whatever the hue.</p>
      <div class="cmp-grid">${tokenGrid('light')}${tokenGrid('dark')}</div></section>

    <section class="cmp-section"><h2>App shell</h2><p>Library is home. Research map (R2) will sit after Library, and Quizzes and Reports (R3) after Notes. Their places are reserved but not shown.</p>
      <div class="cmp-grid">${spec('navigation · library badge', `<ul class="nav-list" style="max-width:240px">
        <li><span class="nav-link" aria-current="page">${ic('library')}<span>Library</span><span class="nav-count">2</span></span></li>
        <li><span class="nav-link">${ic('message')}<span>Chat</span></span></li><li><span class="nav-link">${ic('list')}<span>Conversations</span></span></li>
        <li><span class="nav-link">${ic('note')}<span>Notes</span></span></li><li><span class="nav-link">${ic('tag')}<span>Subjects</span></span></li>
        <li><span class="nav-link">${ic('usage')}<span>Usage</span></span></li></ul>`)}
      ${spec('status line', `<div class="status-line" style="margin:0;max-width:none"><span class="tokens mono">Tokens: 12,480 in · 3,215 out</span><span>Enter to send · Shift + Enter for a new line</span></div>
        <p class="input-hint">${ic('clock', 'sm')}2 documents are still processing and can't be used yet.</p>`)}</div></section>

    <section class="cmp-section"><h2>Subject chip &amp; document state</h2><p>The same chip appears in the Library, the picker, the chat header and every list. States pair a colour with an icon and a label.</p>
      <div class="cmp-grid">
        ${spec('subject chip · default / small / selectable / disabled / highlight', `<div class="chips">${['llm', 'agents', 'rag', 'rl', 'tool'].map((s) => ST.schip(s)).join('')}</div><div class="chips">${['llm', 'agents'].map((s) => ST.schip(s, 'sm')).join('')}</div>
          <div class="sugg"><button type="button" class="schip" data-s="agents" aria-pressed="true">${ic('check', 'sm ck')}<span class="dot" aria-hidden="true"></span>AI Agents<span class="origin">· Your subject</span></button>
          <button type="button" class="schip" data-s="llm" aria-pressed="false">${ic('check', 'sm ck')}<span class="dot" aria-hidden="true"></span>LLMs<span class="origin">· Your subject</span></button>
          <button type="button" class="schip" data-s="tool" aria-pressed="false" disabled>${ic('check', 'sm ck')}<span class="dot" aria-hidden="true"></span>Tool Use<span class="origin">· New</span></button></div>`)}
        ${spec('document state badge', `<div class="od-stack" style="align-items:flex-start">${['uploading', 'processing', 'choose', 'ready'].map((st) => `<span>${ST.stateBadge({ state: st, subjects: [], attempts: 0 })}</span>`).join('')}
          <span>${ST.stateBadge({ state: 'failed', subjects: [], attempts: 1, failReason: "We couldn't read this PDF" })}</span><span>${ST.stateBadge({ state: 'failed', subjects: [], attempts: 3 })}</span><span>${ST.stateBadge({ archived: true })}</span></div>`)}
      </div></section>

    <section class="cmp-section"><h2>Filter bar, tabs &amp; table row</h2><p>One list pattern for Library, Conversations and Notes (and later Quizzes and Reports).</p>
      ${spec('filter bar · tabs · library rows', `<div class="tabs" role="tablist" aria-label="Example"><button class="tab" role="tab" aria-selected="true" type="button">Active<span class="count">8</span></button><button class="tab" role="tab" aria-selected="false" tabindex="-1" type="button">Archived<span class="count">1</span></button></div>
        <div class="filter-bar" style="margin:0"><div class="field"><label for="cf0">Subject</label><select class="select" id="cf0"><option>AI Agents</option></select></div><div class="range"><div class="field"><label for="cf1">From</label><input class="input" type="date" id="cf1"></div><span class="dash" aria-hidden="true">–</span><div class="field"><label for="cf2">To</label><input class="input" type="date" id="cf2"></div></div>
          <div class="field"><label for="cf3">State</label><select class="select" id="cf3"><option>All states</option></select></div><div class="active-filters"><span>4 documents</span><button class="btn btn-ghost btn-sm" type="button">${ic('x', 'sm')}Clear filters</button></div></div>
        <div class="list"><div class="lib-row needs"><div class="doc-cell"><span class="doc-icon">${ic('doc')}</span><div class="od-stack" style="--od-gap:2px"><span class="doc-title">${esc(d.title)}</span><span class="doc-meta">Schick et al. · 2023</span></div></div><div><span class="small muted">Not chosen yet</span></div><div>${ST.stateBadge(d)}</div><div class="row-meta">Today</div><div class="row-actions"><button class="btn btn-primary btn-sm" type="button">Choose subjects</button><button class="icon-btn sm" type="button" aria-label="More actions">${ic('more')}</button></div></div>
          <div class="lib-row"><div class="doc-cell"><span class="doc-icon">${ic('doc')}</span><div class="od-stack" style="--od-gap:2px"><span class="doc-title">ReAct: Synergizing Reasoning and Acting in Language Models</span><span class="doc-meta">Yao et al. · 2022</span></div></div><div>${ST.chips(['agents'], 'sm')}</div><div>${ST.stateBadge({ state: 'ready', subjects: [] })}</div><div class="row-meta">20 Sep</div><div class="row-actions"><button class="btn btn-quiet btn-sm" type="button">Open</button><button class="icon-btn sm" type="button" aria-label="More actions">${ic('more')}</button></div></div></div>`, true)}
    </section>

    <section class="cmp-section"><h2>Uploading</h2><p>A page-wide drop zone with a keyboard-accessible Upload button, and a tray that stays put while you keep working.</p>
      <div class="cmp-grid">
        ${spec('drop zone', `<div class="dropzone" style="padding:32px"><span class="dz-icon">${ic('upload', 'lg')}</span><h2 style="font-size:24px">Upload your first document</h2><p>PDFs up to 50 MB and 500 pages. Your documents stay private to you.</p><p class="dz-rights">${esc(ST.RIGHTS)}</p><button class="btn btn-primary" type="button">${ic('upload', 'sm')}Choose PDFs</button></div>
          <div class="upload-area" style="margin-top:16px"><button class="btn btn-primary" type="button">${ic('upload', 'sm')}Upload</button><p class="upload-rights">${esc(ST.RIGHTS)}</p></div>
          <p class="small muted">First-run drop zone, and the page header's Upload with the same line (G2). A plain line: no checkbox, nothing to accept.</p>`)}
        ${spec('upload tray items', `<section class="tray" style="position:static;width:auto;animation:none"><div class="tray-head"><strong>Uploading 1 file…</strong></div><ul class="tray-list">
          <li class="tray-item"><span class="ti-icon">${ic('doc')}</span><div class="od-stack" style="--od-gap:0"><span class="ti-name">lewis-rag-2020.pdf</span><span class="ti-status">Uploading · 0.9 MB</span><div class="bar"><span style="transform:scaleX(.6)"></span></div></div></li>
          <li class="tray-item ok"><span class="ti-icon">${ic('checkCircle')}</span><div class="od-stack" style="--od-gap:0"><span class="ti-name">react-yao-2022.pdf</span><span class="ti-status">Uploaded · processing</span></div></li>
          <li class="tray-item"><span class="ti-icon">${ic('info')}</span><div class="od-stack" style="--od-gap:0"><span class="ti-name">attention-is-all-you-need.pdf</span><span class="ti-status">Already in your library</span><div class="ti-actions"><button class="btn btn-ghost btn-sm" type="button">Open document</button></div></div></li>
          <li class="tray-item bad"><span class="ti-icon">${ic('alertCircle')}</span><div class="od-stack" style="--od-gap:0"><span class="ti-name">reading-list.docx</span><span class="ti-status">Not uploaded. Only PDF files can be uploaded.</span></div></li></ul></section>`)}
      </div></section>

    <section class="cmp-section"><h2>Conversation pieces</h2><p>Citations, quoted material and system notices each look different from the tutor's own words and from your messages.</p>
      <div class="cmp-grid">
        ${spec('citation', `<div class="cite-list"><button class="cite" type="button">${ic('doc')}<span><span class="doc-name">ReAct: Synergizing Reasoning and Acting in Language Models</span><span class="cite-page">· p. 3</span></span></button>
          <button class="cite" type="button">${ic('doc')}<span><span class="doc-name">Proximal Policy Optimization Algorithms</span><span class="cite-page">· page unavailable</span></span></button>
          <button class="cite" type="button">${ic('doc')}<span><span class="doc-name">Language Models are Few-Shot Learners</span><span class="cite-page">· p. 8</span></span><span class="badge badge-archived">${ic('archive')}Archived</span></button>
          <span class="cite cite-deleted">${ic('doc')}<span><span class="doc-name">Deleted document</span></span></span></div>
          <p class="small muted">A citation opens the document viewer at the cited page. A deleted document's citation reads “Deleted document” and isn't a link.</p>`)}
        ${spec('documents used · row / archived / deleted', `<ol class="du-list">
          <li><button class="du-row" type="button"><span class="du-icon">${ic('doc')}</span><span class="du-text"><span class="du-title">ReAct: Synergizing Reasoning and Acting in Language Models</span><span class="du-meta">Yao et al. · 2022</span></span></button></li>
          <li><button class="du-row" type="button"><span class="du-icon">${ic('doc')}</span><span class="du-text"><span class="du-title">Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks</span><span class="du-meta">Lewis et al. · 2020</span></span><span class="badge badge-archived">${ic('archive')}Archived</span></button></li>
          <li class="du-row is-deleted"><span class="du-icon">${ic('doc')}</span><span class="du-text"><span class="du-title">Chain-of-Thought Prompting Elicits Reasoning in Large Language Models</span><span class="du-meta">Wei et al. · 2022</span></span><span class="badge badge-deleted">${ic('x')}Deleted</span></li></ol>`)}
        ${spec('answer feedback · default / “Helpful” pressed / “Not helpful” pressed (D1)', `<div class="feedback" role="group" aria-label="Example, default"><button class="fb-btn" type="button" aria-pressed="false">${ic('thumb', 'sm')}Helpful</button><button class="fb-btn" type="button" aria-pressed="false">${ic('thumb', 'sm flip-y')}Not helpful</button></div>
          <div class="feedback" role="group" aria-label="Example, helpful pressed"><button class="fb-btn" type="button" aria-pressed="true">${ic('thumb', 'sm')}Helpful</button><button class="fb-btn" type="button" aria-pressed="false">${ic('thumb', 'sm flip-y')}Not helpful</button><span class="fb-thanks">Thanks — glad it helped.</span></div>
          <div class="feedback" role="group" aria-label="Example, not helpful pressed"><button class="fb-btn" type="button" aria-pressed="false">${ic('thumb', 'sm')}Helpful</button><button class="fb-btn" type="button" aria-pressed="true">${ic('thumb', 'sm flip-y')}Not helpful</button></div>
          <p class="small muted">Outline icons with a text label. Pressed adds a tinted fill, an accent border and a heavier label, so the state never relies on colour alone.</p>`)}
        ${spec('system notice · started from a note', `<div class="banner banner-info">${ic('note')}<div class="b-body">Started from note: <a href="#/note/n2"><em>Chain-of-thought prompting</em></a></div></div>`)}
        ${spec('buttons · destructive', `<div class="od-cluster"><button class="btn btn-secondary" type="button">Cancel</button><button class="btn btn-danger" type="button">${ic('trash', 'sm')}Delete</button><button class="btn btn-danger-quiet" type="button">${ic('trash', 'sm')}Delete…</button></div>
          <p class="small muted">Delete is never the default button: Cancel takes the initial focus, and Archive is offered first.</p>`)}
        ${spec('quoted material', `<figure class="excerpt"><blockquote>“reasoning traces help the model induce, track, and update action plans as well as handle exceptions”</blockquote><figcaption>${ic('quote', 'sm')}Quoted from <span style="text-transform:none;letter-spacing:0"><em>ReAct…</em>, p. 3</span></figcaption></figure>`)}
        ${spec('banner', `<div class="banner" style="background:var(--attn-soft);border-color:transparent">${ic('tag')}<div class="b-body"><strong>2 documents need subjects</strong><span>Processing has finished.</span></div><button class="btn btn-primary btn-sm" type="button">Choose subjects</button></div>
          <div class="banner">${ic('archive')}<div class="b-body"><strong>This conversation is archived.</strong></div><button class="btn btn-primary btn-sm" type="button">Restore</button></div>`)}
      </div></section>

    <section class="cmp-section"><h2>Dialog, side panel, empty state &amp; toast</h2><p>Dialogs and panels trap focus, close with Esc and return focus. Toasts offer Undo after archiving.</p>
      <div class="cmp-grid">
        ${spec('subject picker (dialog)', `<div class="dialog picker static" role="group" aria-label="Picker example" style="width:auto"><header><h2 style="font-size:20px">Choose subjects</h2></header>
          <div class="d-body" style="color:var(--text)"><div class="sugg"><button type="button" class="schip" data-s="agents" aria-pressed="true">${ic('check', 'sm ck')}<span class="dot" aria-hidden="true"></span>AI Agents<span class="origin">· Your subject</span></button><button type="button" class="schip" data-s="tool" aria-pressed="false">${ic('check', 'sm ck')}<span class="dot" aria-hidden="true"></span>Tool Use<span class="origin">· New</span></button></div>
            <div class="field"><label for="cmp-ta">Add your own</label><input class="input" id="cmp-ta" value="LLM" aria-describedby="cmp-ta-h"><span class="helper" id="cmp-ta-h">Subject names are visible to everyone. Don't include personal information.</span>
              <p class="field-note info">${ic('info')}<span>We'll use the existing subject <em>Large Language Models</em>.</span></p></div></div>
          <footer><button class="btn btn-secondary" type="button">Cancel</button><button class="btn btn-primary" type="button">Save</button></footer></div>`)}
        ${spec('side panel (document details)', `<div style="border:1px solid var(--border);border-radius:10px;overflow:hidden"><div style="padding:16px 20px;border-bottom:1px solid var(--border)"><span class="sp-kicker" style="font-size:12px;font-weight:650;text-transform:uppercase;color:var(--text-2)">Document details</span><br>${ST.stateBadge({ state: 'ready', subjects: [] })}</div>
          <div style="padding:20px;display:grid;gap:16px"><span class="sp-title" style="font-size:20px">ReAct: Synergizing Reasoning and Acting in Language Models</span><dl class="facts"><dt>Authors</dt><dd>Yao et al.</dd><dt>Year</dt><dd>2022</dd><dt>Pages</dt><dd>33</dd></dl>${ST.chips(['agents'])}</div>
          <div style="display:flex;justify-content:flex-end;gap:12px;padding:12px 20px;border-top:1px solid var(--border)"><button class="btn btn-secondary btn-sm" type="button">${ic('archive', 'sm')}Archive</button></div></div>`)}
        ${spec('empty state', ST.emptyState({ icon: 'filter', title: 'No documents match these filters', text: 'Try another subject, state or a wider date range.', actions: '<button class="btn btn-secondary" type="button">Clear filters</button>' }))}
        ${spec('toast', `<div class="toast" style="justify-self:start;animation:none"><span>Archived “ReAct”. It won't be used for answers.</span><button class="btn btn-sm" type="button">Undo</button></div>`)}
      </div></section>
  </main>`;
  };

  /* =========================================================
     Brief v0.5 decisions and questions
     ========================================================= */
  const DECISIONS = [
    ['P1', 'Conversation panel', 'A 260px panel on the left, toggled from the chat header and remembered: Documents used (32px rows with page count and Archived / Deleted badges), Lesson Note (Open note, Summarize lesson / Update lesson note) and Actions (Show citations, Archive conversation). The header is the toggle, the title and an overflow.', ['chat-answer-citations', 'chat-documents-used', 'chat-panel-collapsed']],
    ['P2', 'Split view in one click', 'A Sources chip opens its cited page with the passage highlighted beside the conversation, and the chip stays highlighted; a panel row opens page 1. The conversation keeps at least 480px (about 550px at 1440, 490px at 1280) and the document takes the rest; the panel collapses and the nav drops to its 56px rail. Another chip swaps the document in place; Close or Esc restores the layout and returns focus to the chip or row.', ['viewer-citation-highlight', 'viewer-document']],
    ['P3', 'The pane', 'A labelled region (not a modal) with one 40px toolbar: title, “p. 3 / 33”, zoom, Close. Loading, error and no-highlight render inside it. viewer-archived stays the overlay, opened from the Library.', ['viewer-no-highlight', 'viewer-loading', 'viewer-error', 'viewer-archived']]
  ];
  DECISIONS.push(
    ['P4', 'Open in dialog', 'A maximize button before Close opens the same document at the same page and highlight in the large overlay, with a details strip (authors, year, pages, subjects, Archived). Close returns to the split view with focus on the button.', ['viewer-dialog']],
    ['P5', 'The conversation\'s documents', 'The panel\'s first section is Documents: documents used plus added ones, each with a remove button on hover and focus; “Add documents” opens a searchable picker; “Only search these documents” (off by default, disabled while empty) shows “Searching N documents · Change” above the composer and declines with “Add documents” / “Search all my documents”.', ['chat-documents-add', 'chat-scope-limited', 'chat-decline-limited']],
    ['P6', 'Chat header', 'Only the panel toggle (sidebar icon, “Hide panel” / “Show panel”) and the title, which is edited inline: Enter or clicking away saves, Esc cancels, 1–120 characters. No “⋯” overflow menu.', ['chat-title-editing', 'chat-panel-collapsed']],
    ['P7', '“Chat” on ready rows', 'Every ready Library row shows “Chat”, which starts a conversation with that document listed; the row title opens the viewer; “More” keeps Details, Change subjects, Edit title, Archive, Delete.', ['library-default', 'library-more-menu']],
    ['R1–R3', 'Answered', 'R1 no new state; R2 Show citations and Archive live in the panel\'s Actions (the header overflow was removed by P6); R3 the panel can be re-opened in split view and the pane then fits the page to its width.', ['viewer-citation-highlight']],
    ['P8', 'Nav toggle at the top (v0.11)', 'The collapse chevron sits at the right of a 40px brand row, aligned with the chat header; on the 56px rail the expand chevron sits below the logo. Chevrons stay, so it differs from the sidebar-icon panel toggle. The nav foot keeps only the user menu. Tab order: brand, toggle, nav items, user menu.', ['shell-nav-collapsed', 'library-default']]
  );
  const QUESTIONS = [
    ['S1', 'Answered', 'Removing a document the answers already cited', 'Removing a used document takes it out of the list and the search scope, but its citations in earlier answers still open it.', 'Answered: citations keep working; removal only affects future answers.'],
    ['S2', 'Answered', '“Change” in the scope line', 'It opens the panel and focuses the switch, where the list can be edited.', 'Answered: “Change” opens the panel at the switch.'],
    ['S3', 'Answered', 'Archived documents in the picker', 'The picker lists ready, active documents only.', 'Answered: ready, active documents only.'],
    ['N2', 'Closed', 'Show citations hidden in a menu', 'Now also a switch in the panel, so it is visible whenever the panel is open.', 'Closed by P1.'],
    ['L1, L2, N3', 'Answered', 'Owner answers', 'L1 a deleted document\'s subjects no longer count for conversations and notes · L2 the row title opens the viewer (P7) · N3 search covers titles only (“Search titles”).', 'PRD Q63.'],
    ['I1, F4, H1, E5, E10', 'Open', 'Smaller items', 'Unchanged.', 'Unchanged.'],
    ['Q4, Q5, Q8', 'Defaults kept', 'Still open in §12', 'Q4 the citations switch also covers notes · Q5 several files at once · Q8 first suggestion pre-selected.', 'All shown as designed.']
  ];
  ST.questionsView = () => `<main class="index-page" id="main-content" tabindex="-1">
    <div class="page-head" style="margin-bottom:32px"><div><h1 style="font-size:48px">Decisions &amp; questions</h1><p>For brief v0.11, round 11 (nav toggle) on top of round 10 (chat). First what P1–P8 changed and where, then open questions.</p></div><a class="btn btn-secondary" href="#/index">${ic('arrowLeft', 'sm')}Overview</a></div>
    <h2 class="section-title" style="margin-top:0">Applied in v0.10 and v0.11</h2>
    <ol class="qa-list">${DECISIONS.map(([id, title, what, states]) => `<li class="qa-item"><span class="qid">${esc(id)}</span>
      <div><h3>${esc(title)}</h3><p>${esc(what)}</p><p class="proposal"><strong>Applied in:</strong> ${states.length ? '' : 'no change needed'}${states.map((sid) => `<a href="#/${sid}"><code class="mono">${sid}</code></a>`).join(', ')}</p></div>
      <span class="badge qtype badge-ready-q">${ic('check')}Applied</span></li>`).join('')}</ol>
    <h2 class="section-title" style="margin-top:48px">Open questions and proposals</h2>
    <ol class="qa-list">${QUESTIONS.map(([id, type, title, ctx, prop]) => `<li class="qa-item"><span class="qid">${esc(id)}</span>
      <div><h3>${esc(title)}</h3><p>${esc(ctx)}</p><p class="proposal"><strong>Proposed:</strong> ${esc(prop)}</p></div>
      <span class="badge qtype ${/Open|Question/.test(type) ? 'badge-archived' : type === 'Proposal' ? 'badge-note' : ''}">${type}</span></li>`).join('')}</ol></main>`;
})();
