/* Smart Tutor v0.9 — Documents used panel (K2, §6.6) and the in-app document viewer (K3, §6.12). */
(function () {
  const ST = window.ST;
  const S = ST.S;
  const esc = ST.esc, ic = ST.ic;

  /* =========================================================
     Documents used: side panel listing the documents that answered this conversation
     ========================================================= */
  ST.openDocsUsed = ({ focusId = null } = {}) => {
    ST.DU = { focusId };
    ST.showOverlay(docsUsedView, { onClose: () => { ST.DU = null; }, keepFocus: !!focusId });
    if (focusId) { const r = document.querySelector(`[data-fk="du-${focusId}"]`); if (r) r.focus(); }
  };
  const meta = (d) => d.book ? `${esc(d.authors)} · Book` : d.authors ? `${esc(d.authors)}${d.year ? ' · ' + d.year : ''}` : esc(d.file);
  function docsUsedView() {
    const ids = ST.docsUsed(S.thread);
    const docs = ids.map((id) => ST.doc(id)).filter(Boolean);
    const anyDeleted = docs.some((d) => d.deleted);
    const row = (d) => {
      const inner = `<span class="du-icon">${ic(d.book ? 'book' : 'doc')}</span>
        <span class="du-text"><span class="du-title">${esc(d.title)}</span><span class="du-meta">${meta(d)}</span></span>
        ${d.deleted ? `<span class="badge badge-deleted">${ic('x')}Deleted</span>` : d.archived ? `<span class="badge badge-archived">${ic('archive')}Archived</span>` : ''}`;
      return d.deleted
        ? `<li class="du-row is-deleted" data-od-id="documents-used-${d.id}"><span class="vh">Deleted: </span>${inner}</li>`
        : `<li><button class="du-row" type="button" data-action="du-open" data-id="${d.id}" data-fk="du-${d.id}" data-od-id="documents-used-${d.id}" aria-label="Open ${esc(d.title)} at page 1">${inner}</button></li>`;
    };
    return `<div class="panel-scrim" data-scrim></div>
      <aside class="side-panel du-panel" role="dialog" aria-modal="true" aria-labelledby="du-h" data-od-id="documents-used-panel">
        <header><div class="od-fill od-stack" style="--od-gap:4px"><span class="sp-kicker">This conversation</span><h2 id="du-h" class="sp-title">Documents used (${docs.length})</h2></div>
          <button class="icon-btn sm" type="button" data-action="du-close" aria-label="Close documents used" data-autofocus>${ic('x')}</button></header>
        <div class="sp-body">
          ${docs.length ? `<p class="small muted">In order of first use. Select one to open it at page 1.</p>
            <ol class="du-list">${docs.map(row).join('')}</ol>
            ${anyDeleted ? `<p class="du-note">${ic('info', 'sm')}Deleted documents can't be opened.</p>` : ''}`
          : `<div class="du-empty">${ic('layers', 'lg')}<p>Documents used to answer will appear here.</p></div>`}
        </div>
      </aside>`;
  }
  Object.assign(ST.actions, {
    'du-close': () => ST.hideOverlay(),
    'du-open': (el) => { const id = el.dataset.id; ST.hideOverlay(false); ST.openViewer(id, { page: 1, from: 'docs' }); }
  });

  /* =========================================================
     Document viewer: modal overlay, ~720 px, PDF pages as paper mocks
     ========================================================= */
  const PAGE_HEADINGS = {
    d3: { 3: '2  ReAct: Synergizing Reasoning + Acting', 5: '3  Knowledge-Intensive Reasoning Tasks', 6: '3.2  Methods' },
    d4: { 2: '2  Methods', 4: '2.2  Retriever: DPR' },
    d8: { 3: '3  Clipped Surrogate Objective' }
  };
  /* The cited chunk for each citation (doc + page). */
  ST.passageFor = (docId, page) => {
    const hit = Object.values(ST.ANSWERS).find((a) => a.quote && a.quote.doc === docId && a.quote.page === page);
    if (hit) return hit.quote.text;
    const generic = {
      'd4|2': 'we combine a pre-trained retriever with a pre-trained seq2seq model and fine-tune end-to-end, treating the retrieved document as a latent variable',
      'd8|3': 'the clipped term removes the incentive for moving the probability ratio outside of the interval [1 − ε, 1 + ε]',
      'd3|5': 'the agent interacts with a simple Wikipedia API to retrieve information that supports its reasoning',
      'd3|6': 'retrieval actions ground each reasoning step in passages the model has actually read'
    };
    return generic[docId + '|' + page] || 'the passage the answer cites on this page';
  };

  ST.VW = null;
  ST.openViewer = (docId, { page = 1, highlight = null, from = 'docs', status = 'ready', noHighlight = false } = {}) => {
    const d = ST.doc(docId);
    if (!d || d.deleted || !['ready', 'choose'].includes(d.state)) return;
    ST.VW = { id: docId, page, zoom: 100, from, status, noHighlight, highlight: highlight ? { page: highlight.page, text: ST.passageFor(docId, highlight.page) } : null };
    ST.showOverlay(viewerView, { onClose: () => {
      const back = ST.VW && ST.VW.from, id = ST.VW && ST.VW.id; ST.VW = null;
      if (back === 'docs') setTimeout(() => ST.openDocsUsed({ focusId: id }), 0);
      if (back === 'details') setTimeout(() => ST.openDetails(id), 0);
    } });
    afterDraw(true);
    if (status === 'loading' && !ST.shot) ST.later(() => { if (ST.VW && ST.VW.status === 'loading') { ST.VW.status = 'ready'; ST.redrawOverlay(); afterDraw(true); } }, 1200);
  };
  const statusText = () => {
    const V = ST.VW, d = ST.doc(V.id);
    if (V.status === 'loading') return `Loading page ${V.page} of ${d.pages}…`;
    if (V.status === 'error') return "We couldn't open this document.";
    const base = `Opened page ${V.page} of ${d.pages}.`;
    if (V.noHighlight) return `${base} Couldn't highlight the passage on this page.`;
    return V.highlight && V.highlight.page === V.page ? `${base} Cited passage highlighted.` : base;
  };
  function afterDraw(announce) {
    const sc = document.getElementById('vw-scroll'); const tgt = document.getElementById('vw-target');
    if (sc && tgt) { let y = 0, el = tgt; while (el && el !== sc) { y += el.offsetTop; el = el.offsetParent; } sc.scrollTop = Math.max(0, y - (tgt.classList.contains('vw-hl') ? 160 : 16)); }
    if (announce) ST.announce(statusText());
  }

  /* Deterministic text lines so every render of a page looks the same. */
  const lines = (seed, n, last = true) => { let out = ''; for (let i = 0; i < n; i++) { const w = i === n - 1 && last ? 38 + ((seed * 7 + i * 13) % 40) : 90 + ((seed * 11 + i * 17) % 11); out += `<span class="pl" style="width:${w}%"></span>`; } return out; };
  const para = (seed, n) => `<div class="pp">${lines(seed, n)}</div>`;
  function pageHtml(d, p) {
    const V = ST.VW;
    const isTarget = p === V.page;
    const heading = (PAGE_HEADINGS[d.id] || {})[p];
    const hl = V.highlight && V.highlight.page === p && !V.noHighlight;
    let body;
    if (p === 1) {
      body = `<div class="pg-title">${esc(d.title)}</div><div class="pg-authors">${esc(d.authors || '')}${d.year ? ` · ${d.year}` : ''}</div>
        <div class="pg-abs"><div class="pg-h">Abstract</div>${para(1, 6)}</div>
        <div class="pg-cols"><div><div class="pg-h">1  Introduction</div>${para(2, 8)}${para(3, 7)}</div><div>${para(4, 9)}${para(5, 8)}</div></div>`;
    } else {
      const passage = hl ? `<div class="vw-hl" ${isTarget ? 'id="vw-target"' : ''} data-od-id="viewer-highlight"><span class="vw-hl-label" aria-hidden="true">Cited passage</span><span class="vh">Cited passage begins. </span>${esc(ST.passageFor(d.id, p).replace(/^./, (c) => c.toUpperCase()))}.<span class="vh"> Cited passage ends.</span></div>` : '';
      body = `${heading ? `<div class="pg-h pg-sec">${esc(heading)}</div>` : ''}
        <div class="pg-cols"><div>${para(p * 3, 7)}${passage}${para(p * 3 + 1, 8)}${para(p * 3 + 2, 6)}</div><div>${para(p * 5, 9)}${para(p * 5 + 1, 7)}${para(p * 5 + 2, 8)}</div></div>`;
    }
    return `<article class="pg" ${isTarget && !hl ? 'id="vw-target"' : ''} aria-label="Page ${p} of ${d.pages}" data-od-id="viewer-page-${p}" style="--zoom:${V.zoom / 100}">
      ${body}<div class="pg-num" aria-hidden="true">${p}</div></article>`;
  }
  function viewerView() {
    const V = ST.VW, d = ST.doc(V.id);
    const fromChat = V.from === 'chat' || V.from === 'docs';
    const pages = [];
    for (let p = Math.max(1, V.page - 1); p <= Math.min(d.pages, V.page + 1); p++) pages.push(p);
    let body;
    if (V.status === 'loading') body = `<div class="vw-pages" aria-busy="true">${[0, 1].map((i) => `<div class="pg pg-skel" style="--zoom:${V.zoom / 100}" ${i === 0 ? 'id="vw-target"' : ''}><span class="sk" style="width:62%;height:22px"></span><span class="sk" style="width:40%"></span><div class="pg-cols"><div>${'<span class="sk"></span>'.repeat(12)}</div><div>${'<span class="sk"></span>'.repeat(12)}</div></div></div>`).join('')}</div>`;
    else if (V.status === 'error') body = `<div class="vw-error" role="alert">${ic('alertCircle', 'lg')}<p class="vw-error-t">We couldn't open this document.</p><p class="small muted">Check your connection and try again.</p><button class="btn btn-secondary" type="button" data-action="vw-retry" data-od-id="viewer-retry">${ic('retry', 'sm')}Retry</button></div>`;
    else body = `${V.noHighlight ? `<p class="vw-note" role="note">${ic('info', 'sm')}Couldn't highlight the passage on this page.</p>` : ''}<div class="vw-pages">${pages.map((p) => pageHtml(d, p)).join('')}</div>`;
    const ready = V.status === 'ready';
    return `<div class="dialog-scrim vw-scrim" data-scrim>
      <section class="viewer" role="dialog" aria-modal="true" aria-labelledby="vw-title" data-od-id="document-viewer">
        <header class="vw-head" role="toolbar" aria-label="Document viewer" data-od-id="viewer-toolbar">
          <button class="btn btn-quiet btn-sm" type="button" data-action="vw-close" data-od-id="viewer-close" ${fromChat ? '' : 'aria-label="Close document viewer"'}>${fromChat ? `${ic('arrowLeft', 'sm')}Back to conversation` : `${ic('x', 'sm')}Close`}</button>
          <span class="th-sep" aria-hidden="true"></span>
          <h2 class="vw-title od-truncate" id="vw-title" tabindex="-1" data-autofocus title="${esc(d.title)} · ${meta(d)}">${esc(d.title)}<span class="vh">, ${meta(d)}</span></h2>
          ${d.archived ? `<span class="badge badge-archived">${ic('archive')}Archived · read-only</span><button class="btn btn-secondary btn-sm" type="button" data-action="vw-restore" data-od-id="viewer-restore">${ic('restore', 'sm')}Restore</button>` : ''}
          <span class="od-fill"></span>
          <button class="icon-btn sm" type="button" data-action="vw-prev" aria-label="Previous page" data-tip="Previous page" ${V.page <= 1 || !ready ? 'disabled' : ''}>${ic('chevronLeft')}</button>
          <span class="vw-page mono" aria-label="Page ${V.page} of ${d.pages}">p. ${V.page} / ${d.pages}</span>
          <button class="icon-btn sm" type="button" data-action="vw-next" aria-label="Next page" data-tip="Next page" ${V.page >= d.pages || !ready ? 'disabled' : ''}>${ic('chevronRight')}</button>
          <span class="th-sep" aria-hidden="true"></span>
          <button class="icon-btn sm" type="button" data-action="vw-zoom" data-dir="-1" aria-label="Zoom out" data-tip="Zoom out" ${V.zoom <= 75 || !ready ? 'disabled' : ''}>${ic('minus')}</button>
          <output class="vw-zoom mono" aria-label="Zoom">${V.zoom}%</output>
          <button class="icon-btn sm" type="button" data-action="vw-zoom" data-dir="1" aria-label="Zoom in" data-tip="Zoom in" ${V.zoom >= 150 || !ready ? 'disabled' : ''}>${ic('plus')}</button>
        </header>
        <div class="vw-body" id="vw-scroll" data-keep-scroll="vw">${body}</div>
        <p class="vh" role="status">${esc(statusText())}</p>
      </section></div>`;
  }
  const goPage = (p) => { const V = ST.VW, d = ST.doc(V.id); V.page = Math.min(d.pages, Math.max(1, p)); ST.redrawOverlay(); afterDraw(true); };
  Object.assign(ST.actions, {
    'vw-close': () => ST.hideOverlay(),
    'vw-prev': () => goPage(ST.VW.page - 1),
    'vw-next': () => goPage(ST.VW.page + 1),
    'vw-zoom': (el) => { const V = ST.VW; V.zoom = Math.min(150, Math.max(75, V.zoom + 25 * +el.dataset.dir)); ST.redrawOverlay(); afterDraw(false); ST.announce(`Zoom ${V.zoom}%`); },
    'vw-retry': () => { const V = ST.VW; V.status = 'loading'; ST.redrawOverlay(); afterDraw(true); ST.later(() => { if (ST.VW) { ST.VW.status = 'ready'; ST.redrawOverlay(); afterDraw(true); } }, 1200); },
    'vw-restore': () => { const d = ST.doc(ST.VW.id); d.archived = false; ST.render(); afterDraw(false); ST.toast(`Restored “${d.title}”.`); ST.announce('Document restored.'); const t = document.getElementById('vw-title'); if (t) t.focus(); }
  });
  document.addEventListener('keydown', (e) => {
    if (!ST.VW || ST.VW.status !== 'ready' || !document.querySelector('#overlay-root .viewer')) return;
    if (e.key === 'PageDown') { e.preventDefault(); goPage(ST.VW.page + 1); }
    if (e.key === 'PageUp') { e.preventDefault(); goPage(ST.VW.page - 1); }
  });
})();
