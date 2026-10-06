/* Smart Tutor v0.5 — every named state <screen>-<state>@v0.5, plus the four review flows (§5).
   Contract (§11 item 6): window.ST.STATES = [{ id, group, ref, desc }], one user story per ref,
   each state at index.html#/<state-id>, review chrome hidden with ?shot=1.
   "live" states are where the app's own navigation lands: they keep whatever the reviewer did.
   Every other state starts from the §9 sample data and sets up its own situation. */
(function () {
  const ST = window.ST;
  const S = ST.S;
  const fresh = () => ST.resetData();
  const doc = (id) => ST.doc(id);

  /* J1 documents built from the sample library */
  const j1Docs = (state) => ST.J1_FILES.map((f, i) => {
    const src = ST.clone(ST.DOCS.find((d) => d.id === f.from));
    return Object.assign(src, { uploaded: ST.TODAY + 'T11:2' + i, state, suggestions: f.suggestions, subjects: state === 'ready' ? [f.suggestions[0].id] : [], dedup: false, tokens: state === 'ready' ? src.tokens : [5800, 410] });
  });
  const newUser = (docState) => { fresh(); S.docs = docState ? j1Docs(docState) : []; S.convs = []; S.notes = []; ST.T.accepted = true; };

  const lib = (us, desc, setup, extra = {}) => Object.assign({ group: 'Library', ref: '§6.3 · ' + us, desc, view: ST.libraryView, setup: () => { fresh(); ST.resetList(); if (setup) setup(); } }, extra);
  const pick = (us, desc, open, setup, extra = {}) => Object.assign({ group: 'Choose subjects', ref: '§6.4 · ' + us, desc, view: ST.libraryView, setup: () => { fresh(); ST.resetList(); if (setup) setup(); }, afterEnter: open }, extra);
  const det = (us, desc, open, setup, extra = {}) => Object.assign({ group: 'Document details', ref: '§6.5 · ' + us, desc, view: ST.libraryView, setup: () => { fresh(); ST.resetList(); if (setup) setup(); }, afterEnter: open }, extra);
  const chat = (us, desc, setup, extra = {}) => Object.assign({ group: 'Chat', ref: '§6.6 · ' + us, desc, view: ST.chatView, afterRender: ST.chatAfter, afterEnter: ST.chatEnter, setup: () => { fresh(); setup(); } }, extra);
  const j2 = (n, o) => { ST.conv('cv1').noteId = null; S.thread = ST.j2Thread(n, Object.assign({ noteId: null }, o || {})); return S.thread; };

  const defs = [
    { id: 'index', group: 'Overview', ref: '§5 · review flows', desc: 'Round 4 overview: what changed in v0.5, the four review flows and every state.', view: ST.indexView, setup: () => { fresh(); } },

    /* §6.2 */
    /* §6.0 */
    { id: 'landing-default', group: 'Landing page', ref: '§6.0 · US-1', desc: 'Public page at /: what Smart Tutor does, how it works, trust points, “Create an account” and “Sign in”. Text only, outside the app shell.', view: ST.landingView, setup: () => { ST.noTray = true; } },

    /* §6.2 */
    { id: 'auth-sign-up', group: 'Sign in, sign up, terms', ref: '§6.2 · US-1', desc: 'Keycloak registration page: stock keycloak.v2 layout with the Smart Tutor logo, colours, font and name (low-detail reference).', view: ST.authSignUp },
    { id: 'auth-verify-email', group: 'Sign in, sign up, terms', ref: '§6.2 · US-1', desc: 'Keycloak email-verification page: stock keycloak.v2 layout (low-detail reference).', view: ST.authVerify },
    { id: 'auth-sign-in', group: 'Sign in, sign up, terms', ref: '§6.2 · US-1', desc: 'Keycloak login page: stock keycloak.v2 layout (low-detail reference).', view: ST.authSignIn },
    { id: 'terms-first-run', group: 'Sign in, sign up, terms', ref: '§6.2 · US-1', desc: 'Terms of use on first sign-in; Continue is disabled until accepted.', view: ST.termsView, setup: () => { ST.T.accepted = false; } },
    { id: 'terms-accepted', group: 'Sign in, sign up, terms', ref: '§6.2 · US-1', desc: 'Terms accepted; Continue leads to the empty Library.', view: ST.termsView, setup: () => { ST.T.accepted = true; } },

    /* §6.3 */
    lib('US-2', 'Live Library: the home screen, with the sample documents (where navigation lands).', null, { id: 'library-default', live: true, setup: () => { if (!ST.keepListFilters) ST.resetList(); ST.keepListFilters = false; } }),
    lib('US-2', 'Empty, first run: “Upload your first document”.', () => { newUser(null); }, { id: 'library-empty' }),
    lib('US-2', 'Files dragged over the page: the whole page accepts the drop.', () => { newUser(null); }, { id: 'library-drop-active', afterEnter: () => ST.showDrop(true) }),
    lib('US-2', 'Three PDFs uploading, each with a progress bar in the tray.', () => { newUser(null); }, { id: 'library-uploading', afterEnter: () => ST.simulateDrop() }),
    lib('US-2', 'Processing: titles appear first; no “Choose subjects” until processing finishes.', () => {
      newUser('processing'); S.tray = ST.J1_FILES.map((f, i) => ({ id: 'tp' + i, name: f.file, size: f.size, status: 'done', progress: 100, docId: f.from }));
      const last = S.docs[S.docs.length - 1]; Object.assign(last, { titlePending: true, realTitle: last.title, title: last.file });
    }, { id: 'library-first-processing', afterEnter: () => {
      if (ST.shot) return; // keep the snapshot still for tools
      ST.later(() => { S.docs.forEach((d) => { if (d.titlePending) { d.titlePending = false; d.title = d.realTitle; } }); ST.render(); }, 1500);
      ST.later(() => { S.docs.forEach((d) => { if (d.state === 'processing') d.state = 'choose'; }); ST.announce('3 documents have finished processing and need subjects.'); ST.render(); }, 5000);
    } }),
    lib('US-2', 'Processing finished: highlighted rows, “Choose subjects” and “3 documents need subjects”.', () => { newUser('choose'); }, { id: 'library-first-choose' }),
    lib('US-2', 'All three documents ready; “Ask a question” leads to the first answer.', () => { newUser('ready'); }, { id: 'library-first-ready' }),
    lib('US-2', 'Needs action: Toolformer needs subjects; banner and Library badge.', null, { id: 'library-choose-subjects' }),
    lib('US-2', 'Rejected before upload: not a PDF, or over 50 MB.', () => {
      S.tray = [{ id: 'r1', name: 'reading-list.docx', size: '0.1 MB', status: 'rejected', reason: 'Only PDF files can be uploaded.' }, { id: 'r2', name: 'deep-learning-book-full.pdf', size: '72 MB', status: 'rejected', reason: 'This file is 72 MB; the limit is 50 MB.' }];
    }, { id: 'library-rejected' }),
    lib('US-2', 'Already in your library: a link to the document, or Restore if archived.', () => {
      S.tray = [{ id: 'a1', name: 'attention-is-all-you-need.pdf', size: '2.2 MB', status: 'duplicate', docId: 'd1' }, { id: 'a2', name: 'gpt3-brown-2020.pdf', size: '6.6 MB', status: 'duplicate-archived', docId: 'd9' }];
    }, { id: 'library-already-in-library' }),
    lib('US-2', 'Failed: the scanned PDF has no text layer, with Retry; after 3 attempts, no Retry.', () => {
      S.docs.push({ id: 'd10', title: 'seminar-slides-week2.pdf', extracted: null, authors: null, year: null, doi: null, file: 'seminar-slides-week2.pdf', pages: 612, size: '24.0 MB', uploaded: '2026-10-01T18:02', state: 'failed', failReason: 'This PDF has more than 500 pages', attempts: 3, subjects: [], archived: false, tokens: [0, 0], summary: null });
      ST.L.state = 'failed';
    }, { id: 'library-failed' }),
    lib('US-2', 'After Retry: the document is processing again (attempt 2 of 3).', () => { const d = doc('d7'); d.state = 'processing'; d.attempts = 2; }, { id: 'library-retry-processing' }),
    lib('US-10', 'Archived tab: Restore, what archiving means for answers, and “Change subjects” still available under More.', () => { ST.L.tab = 'archived'; S.rowMenu = 'd9'; }, { id: 'library-archived' }),
    lib('US-10', 'After archiving ReAct (J4): find it under Archived.', () => { doc('d3').archived = true; ST.L.tab = 'archived'; }, { id: 'library-archived-after-archive' }),
    lib('US-10', 'No results: “No documents match these filters” and Clear filters.', () => { Object.assign(ST.L, { subject: 'rl', from: '2026-10-01' }); }, { id: 'library-no-results' }),
    lib('US-10', 'Filtered by subject (matches any of a document\'s subjects).', () => { ST.L.subject = 'agents'; }, { id: 'library-filtered-by-subject' }),
    lib('US-2', 'Upload limit reached: “You can upload again at 11:40 (GMT+7)”; Upload disabled.', () => { S.uploadLimit = true; }, { id: 'library-rate-limited' }),

    /* §6.4 */
    pick('US-2b', 'Toolformer: summary, 3 suggestions with origin, first pre-selected.', () => ST.openPicker(['d5']), null, { id: 'picker-default' }),
    pick('US-2b', 'Type-ahead searches the shared catalog; existing subjects come first.', () => ST.openPicker(['d5'], { typed: 'retriev' }), null, { id: 'picker-typeahead' }),
    pick('US-2b', 'Near-duplicate: “We\'ll use the existing subject Large Language Models.”', () => ST.openPicker(['d5'], { typed: 'LLM' }), null, { id: 'picker-near-duplicate' }),
    pick('US-2b', 'Rejected name: “Please choose a different name.” with the reason.', () => ST.openPicker(['d5'], { typed: 'Mai Nguyen thesis notes' }), null, { id: 'picker-rejected-name' }),
    pick('US-2b', 'Over 60 characters: blocked, with a counter.', () => ST.openPicker(['d5'], { typed: 'Methods for evaluating retrieval-augmented language model agents' }), null, { id: 'picker-too-long' }),
    pick('US-2b', 'Nothing selected: Save is disabled.', () => { ST.openPicker(['d5']); ST.PK.sel = []; ST.redrawOverlay(); }, null, { id: 'picker-none-selected' }),
    pick('US-2b', 'Three selected: the other chips and the type-ahead are disabled.', () => { ST.openPicker(['d5']); ST.PK.sel = ['agents', 'llm', 'tool']; ST.redrawOverlay(); }, null, { id: 'picker-maximum' }),
    pick('US-2b', 'Saved: “Subjects saved. Toolformer… is ready to use.” The document is Ready right away.', () => ST.openPicker(['d5'], { saved: true }), () => { const d = doc('d5'); d.subjects = ['agents', 'llm']; d.state = 'ready'; }, { id: 'picker-saved' }),
    pick('US-2b', 'Several documents waiting: step through them (“1 of 3”, Next, Skip).', () => ST.openPicker(S.docs.filter((d) => d.state === 'choose').map((d) => d.id)), () => { newUser('choose'); }, { id: 'picker-step-through' }),
    pick('US-10', 'Change subjects of a ready document (J4).', () => ST.openPicker(['d3'], { mode: 'change' }), () => { ST.L.subject = 'agents'; }, { id: 'picker-change-subjects' }),
    pick('US-10', 'Change subjects of an archived document from the Archived tab (D7); it stays archived.', () => ST.openPicker(['d9'], { mode: 'change' }), () => { ST.L.tab = 'archived'; }, { id: 'picker-change-subjects-archived' }),

    /* §6.5 */
    det('US-10', 'Ready document: facts, summary, subjects, Archive. No download, no delete.', () => ST.openDetails('d3'), () => { ST.L.subject = 'agents'; }, { id: 'details-ready' }),
    det('US-10', 'Editing the display title, with “Reset to extracted title”.', () => ST.openDetails('d3', { editing: true, draft: 'ReAct (Yao et al.)' }), () => { ST.L.subject = 'agents'; }, { id: 'details-edit-title' }),
    det('US-10', 'Processing a 424-page book: up to 15 minutes; subjects can be chosen when processing finishes.', () => ST.openDetails('d6'), null, { id: 'details-processing' }),
    det('US-10', 'Failed: “No text layer (scanned PDFs are not supported yet)”, with Retry.', () => ST.openDetails('d7'), null, { id: 'details-failed' }),
    det('US-10', 'Archived document with Restore (J4); “Change subjects” stays available (D7).', () => ST.openDetails('d3'), () => { doc('d3').archived = true; ST.L.tab = 'archived'; }, { id: 'details-archived' }),

    /* §6.6 */
    chat('US-3', 'Live chat: a new conversation (where navigation lands).', () => {}, { id: 'chat-new', live: true,
      setup: () => { S.thread = ST.pendingThread || ST.newThread(); ST.pendingThread = null; },
      afterEnter: () => { if (ST.pendingAsk) { const p = ST.pendingAsk; ST.pendingAsk = null; ST.ask(p.q, { subjects: p.subjects.length ? p.subjects : null }); } } }),
    chat('US-3', 'No documents yet: chat is replaced by “Upload a document first”.', () => { S.docs = []; S.convs = []; S.notes = []; S.thread = ST.newThread(); }, { id: 'chat-no-documents' }),
    chat('US-3', 'New conversation: “Your subjects”, optional example questions, no subject picker.', () => {
      ['d5', 'd6'].forEach((id) => { const d = doc(id); d.state = 'ready'; if (!d.subjects.length) d.subjects = ['agents', 'llm']; });
      S.thread = ST.newThread();
    }, { id: 'chat-new-conversation' }),
    chat('US-3', 'Documents still processing: a quiet hint above the input.', () => { S.thread = ST.newThread(); }, { id: 'chat-documents-processing' }),
    chat('US-4', 'Streaming answer with Stop.', () => {
      ST.conv('cv1').noteId = null;
      S.thread = ST.newThread({ convId: 'cv1', title: ST.J2[0].q, subjects: ['agents'] });
      S.thread.messages.push(ST.M({ role: 'user', text: ST.J2[0].q }));
    }, { id: 'chat-streaming', afterEnter: () => ST.streamAnswer('react', { startAt: 0.2, speed: 130 }) }),
    chat('US-3', 'Subjects detected: one chip in the header, cited answer with a quoted passage.', () => { j2(1); }, { id: 'chat-subjects-detected' }),
    chat('US-3', 'First question covering two subjects: two chips.', () => {
      const q = 'How does chain-of-thought prompting help agents plan their actions?';
      S.thread = ST.newThread({ convId: 'cv2', title: q, subjects: ['llm', 'agents'], tokens: [4210, 520] });
      S.thread.messages.push(ST.M({ role: 'user', text: q }), ST.answerMsg('cot'));
    }, { id: 'chat-subjects-detected-multi' }),
    chat('US-3', 'Detection unsure: pick 1–3 subjects, then Continue; the question stays.', () => {
      const q = 'How do these methods handle long documents?';
      S.thread = ST.newThread({ title: q });
      S.thread.messages.push(ST.M({ role: 'user', text: q }), ST.M({ role: 'tutor', kind: 'unsure', question: q, picks: [] }));
    }, { id: 'chat-detection-unsure' }),
    chat('US-4', 'Answer with citations (one to an archived document shows “Archived”), and labelled “Helpful” / “Not helpful” thumbs.', () => { S.citations = true; doc('d4').archived = true; j2(2); }, { id: 'chat-answer-citations' }),
    chat('US-4', 'Citations switched off: the same thread, answers unchanged.', () => { S.citations = false; j2(2); }, { id: 'chat-citations-off' }),
    chat('US-4', '“Not helpful” is pressed and opens an optional reason; “Helpful” pressed on the first answer.', () => {
      const t = j2(2); const a = t.messages.filter((m) => m.kind === 'answer');
      a[0].fb = 'up'; Object.assign(a[1], { fb: 'down', reasonOpen: true, reason: "Citation doesn't match" });
    }, { id: 'chat-feedback-reason' }),
    chat('US-10', 'Clicking a citation opens the document details at the cited page.', () => { j2(1); }, { id: 'chat-citation-opens-details', afterEnter: () => { ST.chatEnter(); ST.openDetails('d3', { cited: { page: 3 } }); } }),
    chat('US-3b', 'Subject added: inline notice, new chip highlighted in the header.', () => { j2(2, { highlight: 'rag' }); }, { id: 'chat-subject-added',
      afterEnter: () => { ST.chatEnter(); setTimeout(() => { if (S.thread) { S.thread.highlight = null; document.querySelectorAll('.schip.flash').forEach((e) => e.classList.remove('flash')); } }, 2600); } }),
    chat('US-3b', 'Maximum reached: the third subject is added and the learner is told.', () => { j2(3, { highlight: 'llm' }); }, { id: 'chat-maximum-reached' }),
    chat('US-3b', 'Fourth subject refused: no answer; “A new conversation will answer it straight away.”', () => { j2(4); }, { id: 'chat-fourth-subject-refused' }),
    chat('US-3b', 'The carried question was sent right away; the new conversation answers it (Reinforcement Learning).', () => {
      const q = ST.J2[3].q;
      S.thread = ST.newThread({ convId: 'cv5', title: q, subjects: ['rl'], tokens: [3410, 388], carriedFrom: 'cv1' });
      S.thread.messages.push(ST.M({ role: 'user', text: q }), ST.answerMsg('ppo'));
    }, { id: 'chat-new-from-refused' }),
    chat('US-5', 'Decline, no subject fits: a document on the topic is needed to continue; “Upload a document” is the only action.', () => {
      const t = j2(1); const q = "What's the best laptop for research?";
      t.messages.push(ST.M({ role: 'user', text: q }), ST.M({ role: 'tutor', kind: 'decline', question: q, topic: 'choosing a laptop' }));
    }, { id: 'chat-decline' }),
    chat('US-5', 'Decline, another of the learner\'s subjects fits: “New conversation” sends the question there right away.', () => {
      const t = j2(3); const q = 'How is an agent\'s policy updated during training?';
      t.messages.push(ST.M({ role: 'user', text: q }), ST.M({ role: 'tutor', kind: 'decline', question: q, other: 'rl' }));
      t.tokens = [13720, 3267];
    }, { id: 'chat-decline-other-subject' }),
    chat('US-10', 'No active documents in these subjects: history readable, input disabled.', () => { doc('d8').archived = true; S.thread = ST.threadFromConv('cv5'); }, { id: 'chat-no-active-documents' }),
    chat('US-7', '“Summarize lesson” in progress.', () => { j2(2, { summarizing: true, summaryHold: true }); }, { id: 'chat-summarize-progress' }),
    chat('US-7', 'Note saved: confirmation with a link; the header now links the note.', () => { const t = j2(2); ST.makeNote(t, 'saved'); }, { id: 'chat-summarize-done' }),
    chat('US-7', 'A note exists and wasn\'t edited: “Update lesson note” replaces it directly.', () => { S.thread = ST.threadFromConv('cv1'); }, { id: 'chat-update-note' }),
    chat('US-7', 'The note was edited: “You\'ve edited this note. Replace it with a new summary?”', () => { S.thread = ST.threadFromConv('cv2'); }, { id: 'chat-update-edited-note', afterEnter: () => { ST.chatEnter(); ST.actions.summarize(); } }),
    chat('US-13', 'Archived conversation: banner with Restore, input disabled.', () => { S.thread = ST.threadFromConv('cv6'); }, { id: 'chat-archived' }),
    chat('US-9', 'Rate limited: “You can send again at 11:25 (GMT+7)”; input disabled until then.', () => { j2(2, { rateLimit: 42 }); }, { id: 'chat-rate-limited', afterEnter: () => { ST.chatEnter(); ST.startRateLimit(42); } }),
    chat('US-4', 'The answer failed: Retry.', () => { const t = j2(1); t.messages.push(ST.M({ role: 'user', text: ST.J2[1].q }), ST.M({ role: 'tutor', kind: 'error' })); }, { id: 'chat-error' }),
    chat('US-7', 'Started from a note: “Started from note: title” at the top.', () => {
      if (ST.pendingThread) { S.thread = ST.pendingThread; ST.pendingThread = null; return; }
      S.thread = ST.newThread({ fromNote: 'n2', subjects: ['llm', 'agents'], title: 'When does chain-of-thought stop helping?' });
      S.thread.messages.push(ST.M({ role: 'user', text: 'When does chain-of-thought stop helping?' }), ST.answerMsg('cot'));
      S.thread.tokens = [3260, 402];
    }, { id: 'chat-from-note' }),
    chat('US-4', 'J1 ends here: the first cited answer from freshly uploaded papers.', () => {
      newUser('ready'); S.thread = ST.j2Thread(1, { convId: null }); S.convs.push({ id: 'cv1', title: ST.J2[0].q, subjects: ['agents'], last: ST.TODAY + 'T11:31', noteId: null, archived: false, tokens: [3920, 412] }); S.thread.convId = 'cv1';
    }, { id: 'chat-first-answer' }),

    /* §6.7 */
    { id: 'conversations-active', live: true, group: 'Conversations', ref: '§6.7 · US-13', desc: 'Live list: subject chips (up to 3), last activity, note indicator.', setup: () => ST.resetList(), view: ST.conversationsView },
    { id: 'conversations-archived', group: 'Conversations', ref: '§6.7 · US-13', desc: 'Archived tab with Restore.', setup: () => { fresh(); ST.resetList({ tab: 'archived' }); }, view: ST.conversationsView },
    { id: 'conversations-filtered', group: 'Conversations', ref: '§6.7 · US-13', desc: 'Subject filter matches any of a conversation\'s subjects.', setup: () => { fresh(); ST.resetList({ subject: 'agents' }); }, view: ST.conversationsView },
    { id: 'conversations-no-results', group: 'Conversations', ref: '§6.7 · US-13', desc: 'No results for these filters.', setup: () => { fresh(); ST.resetList({ subject: 'rl', from: '2026-10-01' }); }, view: ST.conversationsView },
    { id: 'conversations-empty', group: 'Conversations', ref: '§6.7 · US-13', desc: 'No conversations yet, with “Start a conversation”.', setup: () => { fresh(); ST.resetList(); ST.emptyDemo = true; }, view: ST.conversationsView },
    chat('US-13', 'Opened from the list: history plus its Lesson Note linked in the header.', () => { S.thread = ST.threadFromConv('cv1'); }, { id: 'conversations-open', group: 'Conversations', ref: '§6.7 · US-13' }),

    /* §6.8 */
    { id: 'notes-active', live: true, group: 'Notes', ref: '§6.8 · US-13b', desc: 'Live list: subjects, date, source conversation, “Edited” marker.', setup: () => ST.resetList(), view: ST.notesView },
    { id: 'notes-archived', group: 'Notes', ref: '§6.8 · US-13b', desc: 'Archived notes with Restore.', setup: () => { fresh(); ST.resetList({ tab: 'archived' }); }, view: ST.notesView },
    { id: 'notes-empty', group: 'Notes', ref: '§6.8 · US-13b', desc: 'No lesson notes yet.', setup: () => { fresh(); ST.resetList(); ST.emptyDemo = true; }, view: ST.notesView },
    { id: 'notes-editor', group: 'Notes', ref: '§6.8 · US-7', desc: 'Generated note: Markdown and preview, Discuss this note, source link.', setup: () => { fresh(); ST.openEditor('n1'); }, view: ST.editorView },
    { id: 'notes-editor-edited', group: 'Notes', ref: '§6.8 · US-7', desc: 'Edited note: the “Edited” marker that triggers the overwrite confirmation.', setup: () => { fresh(); ST.openEditor('n2'); }, view: ST.editorView },
    { id: 'notes-editor-unsaved', group: 'Notes', ref: '§6.8 · US-7', desc: 'Unsaved changes; Save enabled.', setup: () => { fresh(); ST.openEditor('n3'); ST.ed.body += '\n\n## My question\n\n- Would BM25 + dense hybrid help my thesis corpus?'; ST.ed.dirty = true; }, view: ST.editorView },
    { id: 'notes-archived-view', group: 'Notes', ref: '§6.8 · US-13b', desc: 'Archived note: read-only with Restore.', setup: () => { fresh(); ST.openEditor('n4'); }, view: ST.editorView },

    /* §6.9 */
    { id: 'subjects-list', live: true, group: 'Subjects', ref: '§6.9 · US-10b', desc: 'My subjects with counts; LLMs shows its shared name and Reset name.', setup: () => { ST.SB = { editing: null, draft: '' }; }, view: ST.subjectsView },
    { id: 'subjects-rename', group: 'Subjects', ref: '§6.9 · US-10b', desc: 'Renaming inline: “Only you see this name.”', setup: () => { fresh(); ST.SB = { editing: 'agents', draft: 'Agents' }; }, view: ST.subjectsView },
    { id: 'subjects-rename-duplicate', group: 'Subjects', ref: '§6.9 · US-10b', desc: 'Rename clashes with another of the learner\'s own subject names (a shared name she doesn\'t have is allowed, D6).', setup: () => { fresh(); ST.SB = { editing: 'rag', draft: 'AI Agents' }; }, view: ST.subjectsView },
    { id: 'subjects-rename-rejected', group: 'Subjects', ref: '§6.9 · US-10b', desc: 'Same naming checks as the picker: personal information is rejected.', setup: () => { fresh(); ST.SB = { editing: 'rag', draft: 'Mai thesis chapter 2' }; }, view: ST.subjectsView },

    /* §6.10–6.11 */
    { id: 'usage-overview', live: true, group: 'Usage & settings', ref: '§6.10 · US-9', desc: 'Today (the GMT+7 day) and all time; Conversations, Document processing, Background.', setup: () => { ST.U = { key: 'last', dir: 'desc' }; }, view: ST.usageView },
    { id: 'settings-default', live: true, group: 'Usage & settings', ref: '§6.11 · no user story', desc: 'Time zone “GMT+7 (Ho Chi Minh City)”, read-only; the accepted terms version and date.', view: ST.settingsView },

    /* §7 */
    { id: 'r2-map', group: 'R2 research map (wireframes)', ref: '§7 · US-19', desc: 'Subject selector, timeline by year, citation links, works without a year.', release: 2, setup: () => { fresh(); ST.R2.subject = 'agents'; }, view: ST.r2Map },
    { id: 'r2-work-details', group: 'R2 research map (wireframes)', ref: '§7 · US-19', desc: 'Work details: files, cites and cited-by within the library.', release: 2, setup: () => { fresh(); }, view: ST.r2Work },
    { id: 'r2-reading-order', group: 'R2 research map (wireframes)', ref: '§7 · US-20', desc: 'Numbered reading order with a reason for each step.', release: 2, view: ST.r2Reading },
    { id: 'r2-ask-path', group: 'R2 research map (wireframes)', ref: '§7 · US-20', desc: '“How did idea develop?” opens a chat answer that walks the works in order.', release: 2, view: ST.r2Ask },
    { id: 'r2-sparse-map', group: 'R2 research map (wireframes)', ref: '§7 · US-19', desc: 'Sparse subject: explains what is missing.', release: 2, setup: () => { fresh(); ST.R2.subject = 'rl'; }, view: ST.r2Sparse },

    /* §8 */
    { id: 'r3-quiz-select', group: 'R3 learning loop (wireframes)', ref: '§8 · US-14', desc: 'Select 1–10 active notes and generate a quiz.', release: 3, setup: () => { fresh(); }, view: ST.r3Select },
    { id: 'r3-quiz-generating', group: 'R3 learning loop (wireframes)', ref: '§8 · US-14', desc: 'Quiz generation progress (up to ~15 s).', release: 3, view: ST.r3Generating },
    { id: 'r3-quiz-take', group: 'R3 learning loop (wireframes)', ref: '§8 · US-14', desc: 'Multiple-choice questions, 4 options.', release: 3, view: ST.r3Take },
    { id: 'r3-quiz-results', group: 'R3 learning loop (wireframes)', ref: '§8 · US-14', desc: 'Score, explanations, score per topic, retake, flag.', release: 3, view: ST.r3Results },
    { id: 'r3-quizzes-list', group: 'R3 learning loop (wireframes)', ref: '§8 · US-14', desc: 'Same list pattern for quizzes.', release: 3, view: ST.r3List },
    { id: 'r3-reports', group: 'R3 learning loop (wireframes)', ref: '§8 · US-15', desc: 'Daily / weekly reports with Generate now.', release: 3, view: ST.r3Reports },
    { id: 'r3-report-view', group: 'R3 learning loop (wireframes)', ref: '§8 · US-15', desc: 'Report: topics, conversations, quiz results, weak topics, recommendations.', release: 3, view: ST.r3Report },
    { id: 'r3-learn-next', group: 'R3 learning loop (wireframes)', ref: '§8 · US-16', desc: '“What should I learn next?” cards with Start learning.', release: 3, view: ST.r3Next },

    /* §10–11 */
    { id: 'components', group: 'Components & questions', ref: '§10 · components', desc: 'Every reusable component, in both themes.', view: ST.componentsView },
    { id: 'brief-questions', group: 'Components & questions', ref: '§11 · questions', desc: 'Brief v0.4 decisions (Q7, D1–D8) and new questions.', view: ST.questionsView }
  ];

  ST.STATES = defs.map((d) => {
    const own = d.setup;
    return Object.assign({}, d, {
      setup: () => {
        if (ST.showDrop) ST.showDrop(false);
        S.citations = ST.ls.get('st3_citations', 'on') !== 'off';
        S.release = d.release || 0;
        if (own) own();
      }
    });
  });

  /* §5 review flows */
  ST.FLOWS = [
    { id: 'J1', title: 'First run', summary: 'From the landing page, sign up, accept terms, upload 3 PDFs, accept subjects, get a first cited answer.', steps: [
      { state: 'landing-default', text: 'Landing page: “Create an account”' },
      { state: 'auth-sign-up', text: 'Sign up on the Keycloak page' },
      { state: 'auth-verify-email', text: 'Verify the email address' },
      { state: 'terms-first-run', text: 'Accept the terms of use' },
      { state: 'library-empty', text: 'Land on the empty Library' },
      { state: 'library-uploading', text: 'Drop 3 PDFs: progress in the upload tray' },
      { state: 'library-first-processing', text: 'Watch processing: titles first, subjects later' },
      { state: 'library-first-choose', text: 'Processing finished: 3 documents need subjects' },
      { state: 'picker-step-through', text: 'Accept suggestions; each document is ready on save' },
      { state: 'library-first-ready', text: 'All ready: “Ask a question”' },
      { state: 'chat-first-answer', text: 'The first cited answer' }
    ] },
    { id: 'J2', title: 'Everyday question', summary: 'Ask, see subjects detected, follow up into a second subject, summarize, open the note.', steps: [
      { state: 'chat-new-conversation', text: 'Open Chat' },
      { state: 'chat-streaming', text: 'Ask: the answer streams in' },
      { state: 'chat-subjects-detected', text: 'Subject detected, cited answer' },
      { state: 'chat-subject-added', text: 'Follow-up adds Retrieval-Augmented Generation' },
      { state: 'chat-summarize-progress', text: '“Summarize lesson”' },
      { state: 'chat-summarize-done', text: 'Note saved' },
      { state: 'notes-editor', text: 'Open the note' }
    ] },
    { id: 'J3', title: 'Conversation reaches its limit', summary: 'Three subjects, then a fourth is refused and carried into a new conversation.', steps: [
      { state: 'chat-maximum-reached', text: 'The conversation now covers 3 subjects' },
      { state: 'chat-fourth-subject-refused', text: 'A question about a fourth subject is refused' },
      { state: 'chat-new-from-refused', text: 'The question is sent right away and answered' }
    ] },
    { id: 'J4', title: 'Library upkeep', summary: 'Filter, open, change subjects, fix the title, archive, restore, and retry a failed file.', steps: [
      { state: 'library-filtered-by-subject', text: 'Filter the Library by AI Agents' },
      { state: 'details-ready', text: 'Open ReAct' },
      { state: 'picker-change-subjects', text: 'Change its subjects' },
      { state: 'details-edit-title', text: 'Fix its display title' },
      { state: 'library-archived-after-archive', text: 'Archive it, then find it under Archived' },
      { state: 'details-archived', text: 'Restore it' },
      { state: 'library-failed', text: 'A failed document' },
      { state: 'library-retry-processing', text: 'Retry: processing again' }
    ] }
  ];

  ST.boot();
})();
