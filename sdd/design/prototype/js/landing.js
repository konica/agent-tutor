/* Smart Tutor v0.5 — public landing page at / (§6.0). Outside the app shell: no left navigation,
   no upload tray. Text only: no product image or illustration. Copy from §9, verbatim. */
(function () {
  const ST = window.ST;

  const STEPS = ['Upload your PDFs', 'Ask a question', 'Check the page it came from'];
  const TRUST = [
    ['Only your documents:', 'the tutor never answers from anything else.'],
    ['Private to you:', 'no one else sees your documents, conversations, or notes.'],
    ['Cited answers:', 'every answer cites the document title and page.']
  ]; /* M9: three points, each with a bold lead, in the same three columns as How it works */
  const ctas = (where) => `<div class="ld-ctas">
      <a class="btn btn-primary btn-lg" href="#/auth-sign-up" data-od-id="landing-${where}-create-account">Create an account</a>
      <a class="btn btn-secondary btn-lg" href="#/auth-sign-in" data-od-id="landing-${where}-sign-in">Sign in</a>
    </div>`;

  ST.landingView = () => `<div class="landing" data-od-id="landing">
    <header class="ld-head" data-od-id="landing-header">
      <a class="brand" href="#/landing-default" aria-label="Smart Tutor, home">${ST.logo()}<span class="word">Smart Tutor</span></a>
      <a class="ld-text-link" href="#/auth-sign-in" data-od-id="landing-header-sign-in">Sign in</a>
    </header>
    <main class="ld-main" id="main-content" tabindex="-1">
      <section class="ld-hero" aria-labelledby="ld-h1" data-od-id="landing-hero">
        <h1 id="ld-h1"><span>Ask your own documents.</span> <span>Get answers you can check.</span></h1>
        <p class="ld-sub">Upload your PDFs. Smart Tutor answers only from them and shows the title and page for every answer.</p>
        ${ctas('hero')}
        <p class="ld-pilot">Pilot · laptop browsers only.</p>
      </section>

      <section class="ld-section" aria-labelledby="ld-how" data-od-id="landing-how-it-works">
        <h2 class="ld-kicker" id="ld-how">How it works</h2>
        <ol class="ld-steps">${STEPS.map((s, i) => `<li data-od-id="landing-step-${i + 1}"><span class="ld-num" aria-hidden="true">0${i + 1}</span><span class="ld-step">${ST.esc(s)}</span></li>`).join('')}</ol>
      </section>

      <section class="ld-section" aria-label="What you can rely on" data-od-id="landing-trust">
        <ul class="ld-trust">${TRUST.map(([lead, rest], i) => `<li data-od-id="landing-trust-${i + 1}"><strong>${ST.esc(lead)}</strong> ${ST.esc(rest)}</li>`).join('')}</ul>
      </section>

      <section class="ld-close" aria-labelledby="ld-close-h" data-od-id="landing-closing">
        <h2 id="ld-close-h">Ask your own documents.</h2>
        ${ctas('closing')}
      </section>
    </main>
    <footer class="ld-foot" data-od-id="landing-footer">
      <span>© 2026 Smart Tutor</span>
    </footer>
  </div>`;
})();
