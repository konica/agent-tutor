/* Smart Tutor — overview index, Release 2 wireframes, components page, questions for the brief owner. */
(function () {
  const ST = window.ST;
  const S = ST.S;
  const esc = ST.esc, ic = ST.ic;

  /* =========================================================
     Overview / state index
     ========================================================= */
  ST.indexView = () => {
    const groups = [];
    ST.STATES.forEach((s) => { if (s.id === 'index') return; let g = groups.find((x) => x.name === s.group); if (!g) { g = { name: s.group, ref: s.ref || '', items: [] }; groups.push(g); } g.items.push(s); });
    return `<main class="index-page" id="main-content" tabindex="-1">
      <section class="index-hero">
        <div>
          <span class="brand" style="padding:0 0 24px">${ST.logo('logo', 'Smart Tutor logo')}<span class="word">Smart Tutor</span></span>
          <h1>Round 1 design for the learner web app</h1>
          <p>Every Release 1 screen and state from design brief v0.2 as one clickable prototype, plus Release 2 wireframes, a components page and questions for the brief owner. Each state is labelled <code class="mono">&lt;screen&gt;-&lt;state&gt;@v0.2</code>. Use <strong>All states</strong>, <strong>Prev</strong> and <strong>Next</strong> in the bar at the top to move between them.</p>
          <div class="od-cluster" style="margin-top:24px;--od-gap:12px">
            <a class="btn btn-primary btn-lg" href="#/auth-sign-in">Start at sign-in${ic('arrowRight', 'sm')}</a>
            <a class="btn btn-secondary btn-lg" href="#/chat-empty">Open the chat</a>
            <a class="btn btn-ghost btn-lg" href="#/brief-questions">Questions for the brief</a>
          </div>
        </div>
        <dl class="meta">
          <div><dt>Brief</dt><dd>v0.2 · PRD v1.6</dd></div>
          <div><dt>Owner</dt><dd>Thao Dinh</dd></div>
          <div><dt>Date</dt><dd>2 Oct 2026</dd></div>
          <div><dt>Screens</dt><dd>Laptop, 1280–1920 px</dd></div>
          <div><dt>Themes</dt><dd>Light and dark</dd></div>
          <div><dt>States</dt><dd>${ST.STATES.length - 1}</dd></div>
        </dl>
      </section>

      <section class="direction" aria-label="Proposed brand direction">
        <div><h3>Logo mark</h3><span class="od-row">${ST.logo('logo', '')}<span style="font-family:var(--font-display);font-size:24px;font-weight:600">Smart Tutor</span></span>
          <p class="small muted">An open book with a tick on the right-hand page: every answer is checked against its source.</p></div>
        <div><h3>Palette</h3><div class="swatch-row"><span class="sw" style="background:var(--accent)" title="Accent"></span><span class="sw" style="background:var(--text)"></span><span class="sw" style="background:var(--surface-2)"></span><span class="sw" style="background:var(--bg)"></span></div>
          <p class="small muted">Cool neutral grounds and one deep teal for actions, sources and focus of attention. Status colours only carry meaning.</p></div>
        <div><h3>Type</h3><span style="font-family:var(--font-display);font-size:32px;line-height:1.1">Aa Charter</span><span class="small">Body: system sans, 16 px</span>
          <p class="small muted">A bookish serif for headings, the system sans for reading and controls, mono for token counts.</p></div>
        <div><h3>Character</h3><p class="small">A calm, focused study tool: quiet surfaces, clear sources, friendly declines.</p>
          <p class="small muted">No gradients, glass or decoration. The thread's subject is always visible.</p></div>
      </section>

      <div class="index-groups">${groups.map((g) => `<section class="index-group ${g.items.length > 10 ? 'span2' : ''}" aria-labelledby="g-${g.items[0].id}">
        <h2 id="g-${g.items[0].id}">${esc(g.name)}<span class="ig-ref">${esc(g.ref)}</span></h2>
        <ul>${g.items.map((s) => `<li><a href="#/${s.id}"><code>${s.id}@${ST.BRIEF}</code><span>${esc(s.desc)}</span></a></li>`).join('')}</ul>
      </section>`).join('')}</div>
    </main>`;
  };

  /* =========================================================
     Release 2 — low-fidelity wireframes (§6)
     ========================================================= */
  const wfBanner = (ref) => `<div class="banner banner-wf" style="margin-bottom:24px">${ic('info')}<div class="b-body"><strong>Release 2 · low-fidelity wireframe</strong><span>Checks content and navigation fit only (${ref}). No visual polish yet.</span></div></div>`;
  const wfPage = (nav, ref, inner) => ST.shell({ nav, content: `<div class="page wf">${wfBanner(ref)}${inner}</div>` });
  const wfListTools = (extra = '') => `<div class="wf-box wf-solid" style="grid-template-columns:repeat(4,auto) 1fr;align-items:end;display:grid">
      <span>[From ▾]</span><span>[To ▾]</span><span>[Subject: All ▾]</span>${extra}<span style="justify-self:end" class="wf-note">Same filter bar as Conversations</span></div>
    <div style="display:flex;gap:24px;margin:16px 0;border-bottom:1.5px dashed var(--wf-line);padding-bottom:8px"><strong>Active (n)</strong><span class="muted">Archived (n)</span></div>`;

  ST.R2 = { picked: ['n1', 'n2'] };
  ST.r2QuizSelect = () => {
    const notes = S.notes.filter((n) => !n.archived);
    const k = ST.R2.picked.length;
    return wfPage('notes', 'US-14', `
      <div class="page-head"><div><h1>Notes · select for quiz</h1><p>Select 1–10 active notes, then generate a quiz.</p></div>
        <div class="od-row"><span aria-live="polite">${k} of 10 selected</span><button class="wf-btn primary" type="button" data-action="go" data-href="#/r2-quiz-generating" ${k ? '' : 'disabled'}>Generate quiz</button></div></div>
      ${wfListTools()}
      <div class="wf-box" style="padding:0;gap:0">${notes.map((n) => `<label class="wf-row"><input type="checkbox" data-change="r2-pick" value="${n.id}" ${ST.R2.picked.includes(n.id) ? 'checked' : ''} aria-label="Select ${esc(n.title)}" style="width:18px;height:18px;accent-color:var(--text)">
        <span>${esc(n.title)}</span><span>${esc(n.subject)}</span><span>${ST.fmtDate(n.date, false)}</span><span class="wf-note">→ source conv.</span></label>`).join('')}</div>
      <p class="wf-note" style="margin-top:12px">Archived notes can't be selected. Selecting an 11th note is blocked with an inline message.</p>`);
  };
  ST.actions['r2-pick'] = (el) => { ST.R2.picked = el.checked ? [...ST.R2.picked, el.value].slice(0, 10) : ST.R2.picked.filter((x) => x !== el.value); ST.render(); };

  ST.r2QuizGenerating = () => wfPage('quizzes', 'US-14', `
    <div class="page-head"><div><h1>Generating your quiz…</h1><p>From 2 notes: Structuring a Task 2 essay · The ReAct pattern</p></div></div>
    <div class="wf-box" style="max-width:640px" role="status">
      <div class="wf-bar"><span style="width:55%"></span></div>
      <span>Writing questions… usually up to 15 seconds.</span>
      <div class="od-row"><button class="wf-btn" type="button" data-action="go" data-href="#/r2-quiz-select">Cancel</button><button class="wf-btn" type="button" data-action="go" data-href="#/r2-quiz-take">(Skip to quiz)</button></div>
    </div>
    <p class="wf-note" style="margin-top:12px">If it takes longer than 15 s: “Still working — this is taking longer than usual.” On failure: error banner with Retry.</p>`);

  ST.r2QuizTake = () => wfPage('quizzes', 'US-14', `
    <div class="page-head"><div><h1>Quiz · Task 2 structure &amp; ReAct</h1><p>${ST.QUIZ.length} questions · 4 options each · one correct answer</p></div><button class="wf-btn primary" type="button" data-action="go" data-href="#/r2-quiz-results">Submit answers</button></div>
    <div class="wf-grid" style="max-width:760px">${ST.QUIZ.map((q, i) => `<fieldset class="wf-box"><legend style="padding:0 4px"><strong>Q${i + 1}.</strong> ${esc(q.q)}</legend>
      ${q.opts.map((o, j) => `<label class="wf-opt"><input type="radio" name="q${i}" ${j === q.pick && i < 4 ? 'checked' : ''} style="accent-color:var(--text)">${esc(o)}</label>`).join('')}</fieldset>`).join('')}</div>
    <p class="wf-note" style="margin-top:12px">Submit stays enabled; unanswered questions are listed in a summary before submitting.</p>`);

  ST.r2QuizResults = () => {
    const correct = ST.QUIZ.filter((q) => q.a === q.pick).length;
    const topics = {};
    ST.QUIZ.forEach((q) => { topics[q.topic] = topics[q.topic] || [0, 0]; topics[q.topic][1]++; if (q.a === q.pick) topics[q.topic][0]++; });
    return wfPage('quizzes', 'US-14', `
      <div class="page-head"><div><h1>Results · ${correct} / ${ST.QUIZ.length} (${Math.round(correct / ST.QUIZ.length * 100)}%)</h1><p>Task 2 structure &amp; ReAct · Today</p></div>
        <div class="od-row"><button class="wf-btn" type="button" data-action="go" data-href="#/r2-quiz-take">Retake</button><button class="wf-btn primary" type="button" data-action="go" data-href="#/r2-learn-next">What should I learn next?</button></div></div>
      <div style="display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:24px;align-items:start">
        <div class="wf-grid">${ST.QUIZ.map((q, i) => { const ok = q.a === q.pick; return `<div class="wf-box">
          <div class="od-row" style="justify-content:space-between"><strong>Q${i + 1}. ${esc(q.q)}</strong><span class="wf-tag">${ok ? '✓ Correct' : '✗ Incorrect'}</span></div>
          ${!ok ? `<div class="wf-opt wrong">Your answer: ${esc(q.opts[q.pick])}</div>` : ''}
          <div class="wf-opt correct">Correct: ${esc(q.opts[q.a])}</div>
          <span class="wf-note">${esc(q.why)}</span>
          <button class="wf-btn" type="button" style="justify-self:start" data-action="r2-flag">${ic('flag', 'sm')}Flag question</button></div>`; }).join('')}</div>
        <div class="wf-box"><strong>Score per topic</strong>${Object.entries(topics).map(([t, [a, b]]) => `<div class="od-stack" style="--od-gap:4px"><span class="od-row" style="justify-content:space-between"><span>${esc(t)}</span><span>${a}/${b}</span></span><div class="wf-bar"><span style="width:${a / b * 100}%"></span></div></div>`).join('')}</div>
      </div>`);
  };
  ST.actions['r2-flag'] = () => ST.toast('Question flagged for review. Thanks.');

  ST.r2QuizzesList = () => wfPage('quizzes', 'US-14', `
    <div class="page-head"><div><h1>Quizzes</h1></div><button class="wf-btn primary" type="button" data-action="go" data-href="#/r2-quiz-select">New quiz from notes</button></div>
    ${wfListTools()}
    <div class="wf-box" style="padding:0;gap:0">
      ${[['Task 2 structure & ReAct', 'IELTS · AI Agents', 'Today', '4/6'], ['Human-in-the-loop approvals', 'AI Agents', '26 Sep', '5/5'], ['Paraphrasing practice', 'IELTS', '19 Sep', '3/8']].map(([t, s, d, sc]) => `<div class="wf-row" style="grid-template-columns:minmax(0,1fr) 160px 100px 80px 120px"><span>${t}</span><span>${s}</span><span>${d}</span><span>${sc}</span><span class="wf-note">[Open] [Archive]</span></div>`).join('')}
    </div>
    <p class="wf-note" style="margin-top:12px">Same list pattern as Conversations and Notes: date range, subject, Active/Archived, archive and restore.</p>`);

  ST.r2ReportsList = () => wfPage('reports', 'US-15', `
    <div class="page-head"><div><h1>Reports</h1><p>Daily and weekly reports across all your subjects.</p></div>
      <div class="od-row"><button class="wf-btn" type="button" data-action="go" data-href="#/r2-learn-next">What should I learn next?</button><button class="wf-btn primary" type="button" data-action="r2-gen">Generate now</button></div></div>
    ${wfListTools('<span>[Type: Daily | Weekly]</span>')}
    <div class="wf-box" style="padding:0;gap:0">
      ${[['Daily report · 2 Oct', 'Daily', 'Today', '3 topics · 2 conversations'], ['Weekly report · 22–28 Sep', 'Weekly', '28 Sep', '7 topics · 9 conversations · 1 quiz'], ['Daily report · 1 Oct', 'Daily', 'Yesterday', '2 topics · 1 conversation']].map(([t, ty, d, s]) => `<a class="wf-row" style="grid-template-columns:minmax(0,1fr) 100px 100px 260px;color:inherit;text-decoration:none" href="#/r2-report-view"><span>${t}</span><span>${ty}</span><span>${d}</span><span class="wf-note">${s}</span></a>`).join('')}
    </div>`);
  ST.actions['r2-gen'] = () => ST.toast('Generating report… it will appear in this list.');

  ST.r2ReportView = () => wfPage('reports', 'US-15', `
    <div class="page-head"><div><h1>Weekly report · 22–28 Sep 2026</h1><p>All subjects · IELTS, AI Agents</p></div><button class="wf-btn" type="button" data-action="go" data-href="#/r2-reports-list">${ic('arrowLeft', 'sm')}All reports</button></div>
    <div class="wf-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
      <div class="wf-box"><span class="wf-note">Conversations</span><strong style="font-size:32px">9</strong></div>
      <div class="wf-box"><span class="wf-note">Topics learned</span><strong style="font-size:32px">7</strong></div>
      <div class="wf-box"><span class="wf-note">Quiz average</span><strong style="font-size:32px">62%</strong></div>
      <div class="wf-box" style="grid-column:span 2"><strong>Topics learned</strong><span>IELTS: Task 2 structure · paraphrasing · Speaking Part 2 vs 3</span><span>AI Agents: ReAct · tools vs skills · human in the loop · planners</span></div>
      <div class="wf-box"><strong>Weak topics</strong><span>Tools and skills (quiz 40%)</span><span>Task 2 length (quiz 50%)</span></div>
      <div class="wf-box" style="grid-column:1/-1"><strong>Recommendations</strong><span>→ Review “Tools and skills” — Agentic Design Patterns, p. 58</span><span>→ Practise Task 2 timing — IELTS Writing Guide, p. 21</span>
        <button class="wf-btn" type="button" style="justify-self:start" data-action="go" data-href="#/r2-learn-next">What should I learn next?</button></div>
    </div>`);

  ST.R2.when = 'tomorrow';
  ST.r2LearnNext = () => {
    const cards = [
      ['AI Agents', 'Tools vs skills', 'Quiz score 40%', 'Agentic Design Patterns, p. 58'],
      ['IELTS', 'Task 2 timing and length', 'Quiz score 50%', 'IELTS Writing Guide, p. 21'],
      ['AI Agents', 'Plan-and-execute agents', 'Not studied yet', 'Agentic Design Patterns, p. 88'],
      ['IELTS', 'Coherence and cohesion', 'Not studied yet', 'IELTS Writing Guide, p. 30']
    ].slice(0, ST.R2.when === 'tomorrow' ? 3 : 4);
    return wfPage('reports', 'US-16', `
      <div class="page-head"><div><h1>What should I learn next?</h1><p>Based on your reports, quiz results and what you haven't studied yet.</p></div></div>
      <div class="od-row" role="radiogroup" aria-label="Time frame" style="margin-bottom:16px">
        <button class="wf-btn ${ST.R2.when === 'tomorrow' ? 'primary' : ''}" type="button" role="radio" aria-checked="${ST.R2.when === 'tomorrow'}" data-action="r2-when" data-w="tomorrow">What should I learn tomorrow?</button>
        <button class="wf-btn ${ST.R2.when === 'week' ? 'primary' : ''}" type="button" role="radio" aria-checked="${ST.R2.when === 'week'}" data-action="r2-when" data-w="week">…next week?</button>
      </div>
      <div class="wf-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">${cards.map(([s, t, r, d]) => `<div class="wf-box">
        <span class="wf-tag" style="justify-self:start">${s}</span><strong style="font-size:18px">${t}</strong>
        <span>Why: ${r}</span><span class="wf-note">Read: ${d}</span>
        <button class="wf-btn primary" type="button" style="justify-self:start" data-action="go" data-href="#/chat-empty">Start learning</button></div>`).join('')}</div>
      <p class="wf-note" style="margin-top:12px">3–5 cards. “Start learning” opens a new conversation in that subject with the topic prefilled.</p>`);
  };
  ST.actions['r2-when'] = (el) => { ST.R2.when = el.dataset.w; ST.render(); };

  /* =========================================================
     Components page (§8)
     ========================================================= */
  const TOKENS = [['--bg', 'Page ground'], ['--surface', 'Surface'], ['--surface-2', 'Subtle fill'], ['--border', 'Border'], ['--text', 'Text'], ['--text-2', 'Secondary text'], ['--accent', 'Accent / action'], ['--accent-soft', 'Accent tint'], ['--success', 'Success'], ['--warn', 'Warning'], ['--danger', 'Error'], ['--info', 'Info']];
  const tokenGrid = (theme) => `<div data-theme="${theme}" style="background:var(--surface);color:var(--text);padding:16px;border-radius:10px;border:1px solid var(--border)">
    <p class="label" style="margin-bottom:12px">${theme === 'dark' ? 'Dark' : 'Light'}</p>
    <div class="token-table">${TOKENS.map(([t, l]) => `<div class="token"><span class="sw" style="background:var(${t})"></span><span><code>${t}</code>${l}</span></div>`).join('')}</div></div>`;

  ST.componentsView = () => {
    const sampleMsg = ST.answerMsg('react');
    return `<main class="index-page" id="main-content" tabindex="-1">
    <div class="page-head" style="margin-bottom:48px"><div><h1 style="font-size:48px">Components</h1><p>The small reusable set every screen is built from. Tokens live once on <code class="mono">:root</code> and <code class="mono">[data-theme="dark"]</code> in <code class="mono">styles.css</code>.</p></div>
      <a class="btn btn-secondary" href="#/index">${ic('arrowLeft', 'sm')}Overview</a></div>

    <section class="cmp-section"><h2>Brand &amp; tokens</h2><p>One accent, neutral cool grounds, status colours only for meaning. Each theme's contrast is chosen on its own: body text is at least 4.5:1 and large text and icons at least 3:1.</p>
      <div class="cmp-grid">
        <div class="specimen"><span class="spec-label">logo</span><div class="od-row" style="--od-gap:16px">${ST.logo('logo')}<span style="font-family:var(--font-display);font-size:28px;font-weight:600">Smart Tutor</span></div>
          <div data-theme="dark" class="od-row" style="--od-gap:16px;background:var(--bg);color:var(--text);padding:16px;border-radius:10px">${ST.logo('logo')}<span style="font-family:var(--font-display);font-size:28px;font-weight:600">Smart Tutor</span></div></div>
        <div class="specimen"><span class="spec-label">type scale</span>
          <div class="type-row"><code>40 · display</code><span style="font-family:var(--font-display);font-size:40px;line-height:1.1">Learn from sources</span></div>
          <div class="type-row"><code>24 · heading</code><span style="font-family:var(--font-display);font-size:24px">Lesson notes</span></div>
          <div class="type-row"><code>16 · body</code><span>Answers come only from your subject's documents.</span></div>
          <div class="type-row"><code>14 · small</code><span class="small">Last activity · Today, 10:14</span></div>
          <div class="type-row"><code>12 · mono</code><span class="mono xsmall">Tokens: 12,480 in · 3,215 out</span></div></div>
        <div class="specimen full"><span class="spec-label">colour tokens</span><div class="cmp-grid">${tokenGrid('light')}${tokenGrid('dark')}</div></div>
      </div></section>

    <section class="cmp-section"><h2>Buttons &amp; controls</h2><p>Every control is at least 40 px tall (32 px for compact row actions) and has a visible focus ring. Disabled buttons keep readable labels.</p>
      <div class="cmp-grid">
        <div class="specimen"><span class="spec-label">button · default / hover / focus / disabled</span>
          <div class="state-row"><button class="btn btn-primary" type="button">Primary</button><button class="btn btn-primary force-hover" type="button" tabindex="-1">Hover</button><button class="btn btn-primary force-focus" type="button" tabindex="-1">Focus</button><button class="btn btn-primary" type="button" disabled>Disabled</button></div>
          <div class="state-row"><button class="btn btn-secondary" type="button">Secondary</button><button class="btn btn-secondary force-hover" type="button" tabindex="-1">Hover</button><button class="btn btn-ghost" type="button">Ghost</button><button class="btn btn-secondary" type="button"><span class="spinner" aria-hidden="true"></span>Loading…</button></div>
          <div class="state-row"><button class="icon-btn" type="button" aria-label="Archive">${ic('archive')}</button><button class="icon-btn" type="button" aria-pressed="true" aria-label="Helpful">${ic('thumb')}</button><button class="btn btn-primary send" style="width:40px;padding:0" type="button" aria-label="Send">${ic('send')}</button><button class="btn btn-secondary" type="button">${ic('stop', 'sm')}Stop</button></div></div>
        <div class="specimen"><span class="spec-label">input · select · switch · tabs</span>
          <div class="field"><label for="cmp-in">Label</label><input class="input" id="cmp-in" value="Typed value" aria-describedby="cmp-in-h"><span class="helper" id="cmp-in-h">Helper text sits under the field.</span></div>
          <div class="field"><label for="cmp-in2">With error</label><input class="input" id="cmp-in2" value="studyhard" aria-invalid="true" aria-describedby="cmp-in2-e"><span class="field-error" id="cmp-in2-e">${ic('alertCircle', 'sm')}Passwords don't match.</span></div>
          <div class="od-row"><button class="switch" type="button" role="switch" aria-checked="true"><span class="track" aria-hidden="true"></span>Show citations<span class="state" aria-hidden="true">On</span></button>
            <button class="switch" type="button" role="switch" aria-checked="false"><span class="track" aria-hidden="true"></span>Show citations<span class="state" aria-hidden="true">Off</span></button></div>
          <div class="tabs" role="tablist" aria-label="Example tabs"><button class="tab" role="tab" aria-selected="true" type="button">Active<span class="count">7</span></button><button class="tab" role="tab" aria-selected="false" tabindex="-1" type="button">Archived<span class="count">2</span></button></div></div>
      </div></section>

    <section class="cmp-section"><h2>Chips, badges &amp; citation</h2><p>Subject chips always pair an icon with the name. A citation is a button showing the document title and page; it opens the excerpt.</p>
      <div class="cmp-grid">
        <div class="specimen"><span class="spec-label">chip · badge</span>
          <div class="state-row">${ST.subjectChip('IELTS')}${ST.subjectChip('AI Agents')}${ST.subjectChip('IELTS', 'chip-accent')}<span class="subject-chip">${ST.subjectChip('IELTS', 'chip-accent')}<button class="btn btn-ghost btn-sm" type="button">Change</button></span></div>
          <div class="state-row"><span class="badge badge-note">${ic('note')}Lesson note</span><span class="badge badge-archived">${ic('archive')}archived</span><span class="badge">Current</span><span class="badge badge-r2">R2</span></div></div>
        <div class="specimen"><span class="spec-label">citation</span>
          <div class="cite-list"><button class="cite" type="button">${ic('doc')}<span>Agentic Design Patterns<span class="page">, p. 42</span></span></button>
            <button class="cite" type="button">${ic('doc')}<span>IELTS Writing Guide<span class="page">, p. 18</span></span></button>
            <button class="cite" type="button">${ic('doc')}<span>Agent Architectures Primer (2024 edition)<span class="page">, p. 7</span></span><span class="badge badge-archived">${ic('archive')}archived</span></button></div></div>
      </div></section>

    <section class="cmp-section"><h2>Banners</h2><p>Banners explain a state and offer the next step. Declines are never styled as errors.</p>
      <div class="cmp-grid">
        <div class="specimen"><span class="spec-label">banner · neutral (read-only)</span><div class="banner">${ic('lock')}<div class="b-body"><strong>This conversation is read-only.</strong><span>Enroll in <em>IELTS</em> again to continue.</span></div><button class="btn btn-primary btn-sm" type="button">Enroll in IELTS</button></div></div>
        <div class="specimen"><span class="spec-label">banner · info</span><div class="banner banner-info">${ic('note')}<div class="b-body">Started from note: <a href="#/note/n1"><em>Structuring a Task 2 essay</em></a></div></div></div>
        <div class="specimen"><span class="spec-label">banner · warning (rate limit)</span><div class="banner banner-warn">${ic('clock')}<div class="b-body"><strong>Too many messages in a short time.</strong><span>Try again in <span class="mono">24</span> seconds.</span></div></div></div>
        <div class="specimen"><span class="spec-label">banner · success</span><div class="banner banner-success">${ic('checkCircle')}<div class="b-body"><strong>Lesson note saved</strong><span>Structuring a Task 2 essay</span></div><a class="btn btn-secondary btn-sm" href="#/note/n1">Open note</a></div></div>
      </div></section>

    <section class="cmp-section"><h2>List pattern</h2><p>Conversations, notes, quizzes and reports share one layout: filter bar (date range and subject), Active / Archived tabs, rows with open and archive or restore.</p>
      <div class="specimen full"><span class="spec-label">filter bar · tabs · list row</span>
        <div class="tabs" role="tablist" aria-label="Example status tabs"><button class="tab" role="tab" aria-selected="true" type="button">Active<span class="count">7</span></button><button class="tab" role="tab" aria-selected="false" tabindex="-1" type="button">Archived<span class="count">2</span></button></div>
        <div class="filter-bar" style="margin:0"><div class="range"><div class="field"><label for="cf1">From</label><input class="input" type="date" id="cf1" value="2026-09-25"></div><span class="dash" aria-hidden="true">–</span><div class="field"><label for="cf2">To</label><input class="input" type="date" id="cf2"></div></div>
          <div class="field"><label for="cf3">Subject</label><select class="select" id="cf3"><option>AI Agents</option></select></div><div class="active-filters"><span>2 conversations</span><button class="btn btn-ghost btn-sm" type="button">${ic('x', 'sm')}Clear filters</button></div></div>
        <div class="list"><div class="row"><div class="row-title"><a class="od-truncate" href="#/open/c2">What is the ReAct pattern?</a><span class="row-meta"><span class="badge badge-note">${ic('note')}Lesson note</span></span></div><div>${ST.subjectChip('AI Agents')}</div><div class="row-meta">Yesterday, 16:40</div><div class="row-actions"><a class="btn btn-quiet btn-sm" href="#/open/c2">Open</a><button class="btn btn-secondary btn-sm" type="button">${ic('archive', 'sm')}Archive</button></div></div>
          <div class="row"><div class="row-title"><a class="od-truncate" href="#/open/c8">Is a planner agent the same as a router?</a></div><div>${ST.subjectChip('AI Agents')}</div><div class="row-meta">10 Sep</div><div class="row-actions"><a class="btn btn-quiet btn-sm" href="#/open/c8">Open</a><button class="btn btn-secondary btn-sm" type="button">${ic('restore', 'sm')}Restore</button></div></div></div>
      </div></section>

    <section class="cmp-section"><h2>Empty state, dialog &amp; toast</h2><p>Empty states say why and what to do next. Dialogs trap focus, close with Esc and return focus. Toasts offer Undo after archiving.</p>
      <div class="cmp-grid">
        <div class="specimen">${ST.emptyState({ icon: 'filter', title: 'No conversations match these filters', text: 'Try a wider date range or another subject.', actions: '<button class="btn btn-secondary" type="button">Clear filters</button>' })}</div>
        <div class="specimen"><div class="dialog static" role="group" aria-label="Dialog example"><header><h2 style="font-size:24px">Leave IELTS?</h2><button class="icon-btn sm" type="button" aria-label="Close">${ic('x')}</button></header>
          <div class="d-body"><p>Your <strong>IELTS</strong> conversations become read-only until you enroll again. Your lesson notes stay available, and nothing is deleted.</p></div>
          <footer><button class="btn btn-secondary" type="button">Stay enrolled</button><button class="btn btn-primary" type="button">Leave IELTS</button></footer></div>
          <div class="toast" style="justify-self:start;animation:none"><span>Conversation archived.</span><button class="btn btn-sm" type="button">Undo</button></div></div>
      </div></section>

    <section class="cmp-section"><h2>Messages &amp; status line</h2><p>The learner's question sits in a quiet bubble on the right; the tutor's answer reads as plain text with its sources and feedback underneath.</p>
      <div class="specimen full" style="background:var(--bg)">
        <div class="thread" style="padding:0;max-width:760px">
          <div class="msg-user">What is the ReAct pattern?</div>
          <article class="msg-tutor">${ST.logo('logo')}<div class="msg-body"><span class="msg-name">Smart Tutor</span>${ST.mdParas(sampleMsg.text.split('\n\n')[0])}
            <div class="cites"><span class="cites-label">Sources</span><div class="cite-list"><button class="cite" type="button">${ic('doc')}<span>Agentic Design Patterns<span class="page">, p. 42</span></span></button></div></div>
            <div class="feedback"><span class="fb-label">Helpful?</span><button class="icon-btn sm" type="button" aria-label="Helpful" aria-pressed="false">${ic('thumb', 'sm')}</button><button class="icon-btn sm" type="button" aria-label="Not helpful" aria-pressed="false">${ic('thumb', 'sm flip-y')}</button></div></div></article>
          <article class="msg-tutor">${ST.logo('logo')}<div class="msg-body"><span class="msg-name">Smart Tutor</span><div class="tutor-card decline"><p>This conversation is about <em>IELTS</em>. Please ask a question about <em>IELTS</em>, or start a new conversation for other topics.</p><div class="tc-actions"><button class="btn btn-secondary" type="button">${ic('plus', 'sm')}New conversation</button></div></div></div></article>
        </div>
        <div class="status-line" style="margin:0;max-width:760px"><span class="tokens mono">Tokens: 12,480 in · 3,215 out</span><span>Enter to send · Shift + Enter for a new line</span></div>
      </div></section>
  </main>`;
  };

  /* =========================================================
     Questions & proposed changes (§9.3)
     ========================================================= */
  const QUESTIONS = [
    ['D1', 'Proposal', 'Theme switch placement', 'The brief lists only time zone and a Subjects link in Settings (§5.8). Dark mode needs a home.', 'Add an “Appearance” section to Settings (light/dark) plus a shortcut in the user menu. The “Show citations” switch is mirrored there too.'],
    ['D2', 'Question', 'What happens to the old thread when the learner presses “Change”?', '§5.4 says Change “restarts the conversation under the chosen subject”.', 'Keep the original thread in Conversations unchanged, open a new thread under the chosen subject, and pre-fill the first question so the learner only presses Enter.'],
    ['D3', 'Proposal', 'Decline → “New conversation” carries the question over', 'The decline state offers a New conversation button but doesn\'t say what it opens.', 'Open a new conversation with the declined question already in the input, so the tutor can detect its real subject.'],
    ['D4', 'Question', 'Thumbs-down reasons', 'The brief says “optional reason” without a list.', 'Proposed reasons: Not accurate · Didn\'t answer my question · Source doesn\'t match · Hard to follow, plus an optional free-text field. Please confirm or replace them.'],
    ['D5', 'Question', 'Does the chat status line include background tokens?', '§5.7 says Usage includes background work (notes, learning records). §5.4 shows per-thread tokens only.', 'Include this thread\'s background work (e.g. summarizing into a note) in its status line, so it adds up to the Usage table.'],
    ['D6', 'Question', 'Read-only threads and their notes', 'When a learner leaves a subject, its conversations become read-only. The brief doesn\'t say what happens to the subject\'s notes.', 'Notes stay editable, but “Discuss this note” is disabled until the learner enrolls again, with the reason shown.'],
    ['D7', 'Question', 'Rate-limit wording and duration', '“Try again in N seconds”: who sets N, and can it exceed a minute?', 'Show seconds up to 90, then “about N minutes”. The input re-enables on its own when the timer ends.'],
    ['D8', 'Proposal', 'Archived-document citations', 'The brief asks for an “archived” badge. Should the excerpt still open?', 'Yes: the excerpt opens with a short note that the document is archived. The answer stays traceable.'],
    ['D9', 'Proposal', 'Release 2 nav slots', '§5.1 asks to leave room for Quizzes and Reports.', 'Show them now under a “Release 2” heading, disabled with a “Soon” label, so the navigation length is final. Hide them instead if you prefer.'],
    ['Q4', 'Default adopted', 'Citations toggle and Lesson Notes (Release 2)', 'Open question Q4 in §10.', 'Adopted the default: the same remembered setting will also hide or show citations carried into Lesson Notes.'],
    ['D10', 'Note', 'Brand fonts', 'This round uses the computer\'s own fonts (Charter or a similar serif for headings, the system sans for body) so the prototype works offline.', 'If the direction is approved, license a matching web font (for example Source Serif) so headings look the same on every operating system.'],
    ['D11', 'Note', 'PRD conflicts', 'The brief asks the designer to flag conflicts with the PRD.', 'The PRD (v1.6) wasn\'t shared with the designer, so no conflicts could be checked. Every decision follows the brief.']
  ];
  ST.questionsView = () => `<main class="index-page" id="main-content" tabindex="-1">
    <div class="page-head" style="margin-bottom:32px"><div><h1 style="font-size:48px">Questions &amp; proposed changes</h1><p>For brief v0.2, round 1. Items marked “Proposal” are already shown in the prototype. Items marked “Question” need a decision from the brief owner.</p></div>
      <a class="btn btn-secondary" href="#/index">${ic('arrowLeft', 'sm')}Overview</a></div>
    <ol class="qa-list">${QUESTIONS.map(([id, type, title, ctx, prop]) => `<li class="qa-item">
      <span class="qid">${id}</span>
      <div><h3>${esc(title)}</h3><p>${esc(ctx)}</p><p class="proposal"><strong>Proposed:</strong> ${esc(prop)}</p></div>
      <span class="badge qtype ${type === 'Question' ? 'badge-archived' : type === 'Proposal' ? 'badge-note' : ''}">${type}</span></li>`).join('')}</ol>
  </main>`;
})();
