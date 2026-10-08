/* Smart Tutor v0.8 — every named state <screen>-<state>@v0.8, plus the four review flows (§5).
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
  const newUser = (docState) => { fresh(); S.docs = docState ? j1Docs(docState) : []; S.convs = []; S.notes = []; };

  const lib = (us, desc, setup, extra = {}) => Object.assign({ group: 'Library', ref: '§6.3 · ' + us, desc, view: ST.libraryView, setup: () => { fresh(); ST.resetList(); if (setup) setup(); } }, extra);
  const pick = (us, desc, open, setup, extra = {}) => Object.assign({ group: 'Choose subjects', ref: '§6.4 · ' + us, desc, view: ST.libraryView, setup: () => { fresh(); ST.resetList(); if (setup) setup(); }, afterEnter: open }, extra);
  const det = (us, desc, open, setup, extra = {}) => Object.assign({ group: 'Document details', ref: '§6.5 · ' + us, desc, view: ST.libraryView, setup: () => { fresh(); ST.resetList(); if (setup) setup(); }, afterEnter: open }, extra);
  const chat = (us, desc, setup, extra = {}) => Object.assign({ group: 'Chat', ref: '§6.6 · ' + us, desc, view: ST.chatView, afterRender: ST.chatAfter, afterEnter: ST.chatEnter, setup: () => { fresh(); setup(); } }, extra);
  const view = (desc, open, setup, extra = {}) => Object.assign({ group: 'Document viewer', ref: '§6.12 · US-4b', desc, view: ST.chatView, afterRender: ST.chatAfter, setup: () => { fresh(); setup(); }, afterEnter: () => { ST.chatEnter(); open(); } }, extra);
  const j2 = (n, o) => { ST.conv('cv1').noteId = null; S.thread = ST.j2Thread(n, Object.assign({ noteId: null }, o || {})); return S.thread; };

  const defs = [
    { id: 'index', group: 'Overview', ref: '§5 · review flows', desc: 'Round 8 overview: what changed in v0.8, the four review flows and every state.', view: ST.indexView, setup: () => { fresh(); } },

    /* §6.0 */
    { id: 'landing-default', group: 'Landing page', ref: '§6.0 · US-1', desc: 'Public page at /: what Smart Tutor does, how it works, trust points, “Create an account” and “Sign in”. Text only, outside the app shell.', view: ST.landingView, setup: () => { ST.noTray = true; } },

    /* §6.2 */
    { id: 'auth-sign-up', group: 'Sign in, sign up', ref: '§6.2 · US-1', desc: 'Keycloak registration page: stock keycloak.v2 layout, email as username (no Username field), with the Smart Tutor logo, colours, font and name (low-detail reference).', view: ST.authSignUp },
    { id: 'auth-verify-email', group: 'Sign in, sign up', ref: '§6.2 · US-1', desc: 'Keycloak email-verification page: stock keycloak.v2 layout (low-detail reference).', view: ST.authVerify },
    { id: 'auth-sign-in', group: 'Sign in, sign up', ref: '§6.2 · US-1', desc: 'Keycloak login page: stock keycloak.v2 layout (low-detail reference).', view: ST.authSignIn },

    /* §6.3 */
    lib('US-2', 'Live Library: the home screen, with the sample documents; the upload-rights line sits under “Upload” (where navigation lands).', null, { id: 'library-default', live: true, setup: () => { if (!ST.keepListFilters) ST.resetList(); ST.keepListFilters = false; } }),
    lib('US-2', 'Empty, first run: “Upload your first document”, with “Only upload documents you have the right to use.” under it.', () => { newUser(null); }, { id: 'library-empty' }),
    lib('US-2', 'Files dragged over the page: the whole page accepts the drop; the upload-rights line shows in the drop target.', () => { newUser(null); }, { id: 'library-drop-active', afterEnter: () => ST.showDrop(true) }),
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
    lib('US-10', 'Archived tab: Restore, what archiving means for answers; no “Change subjects” on archived rows or in their More menu (E7).', () => { ST.L.tab = 'archived'; S.rowMenu = 'd9'; }, { id: 'library-archived' }),
    lib('US-10', 'After archiving ReAct (J4): find it under Archived.', () => { doc('d3').archived = true; ST.L.tab = 'archived'; }, { id: 'library-archived-after-archive' }),
    lib('US-10', 'No results: “No documents match these filters” and Clear filters.', () => { Object.assign(ST.L, { subject: 'rl', from: '2026-10-01' }); }, { id: 'library-no-results' }),
    lib('US-10', 'Filtered by subject (matches any of a document\'s subjects).', () => { ST.L.subject = 'agents'; }, { id: 'library-filtered-by-subject' }),
    lib('US-10c', '“More” menu with Delete (K4); a processing row offers no Delete.', () => { S.rowMenu = 'd2'; }, { id: 'library-more-menu' }),
    lib('US-10c', 'Delete confirmation: Cancel focused, Delete in danger style, “Archive instead” under the warning. The same dialog opens from details.', null, { id: 'library-delete-confirm', afterEnter: () => ST.confirmDelete('d2') }),
    lib('US-10c', 'Deleted: the row is gone and “Chain-of-Thought Prompting… deleted.” confirms it. No undo.', () => { ST.deleteDoc(doc('d2')); }, { id: 'library-deleted' }),
    lib('US-2', 'Upload limit reached: hourly “You can upload again at 11:40 (GMT+7)”, daily “You can upload again at 00:00 (GMT+7)”; Upload disabled.', () => { S.uploadLimit = true; }, { id: 'library-rate-limited' }),

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


    /* §6.5 */
    det('US-10', 'Ready document: facts, summary, subjects; Open (viewer), Archive and Delete. No download.', () => ST.openDetails('d3'), () => { ST.L.subject = 'agents'; }, { id: 'details-ready' }),
    det('US-10', 'Editing the display title, with “Reset to extracted title”.', () => ST.openDetails('d3', { editing: true, draft: 'ReAct (Yao et al.)' }), () => { ST.L.subject = 'agents'; }, { id: 'details-edit-title' }),
    det('US-10', 'Processing a 424-page book: up to 15 minutes; no Open and no Delete while processing.', () => ST.openDetails('d6'), null, { id: 'details-processing' }),
    det('US-10', 'Failed: “No text layer (scanned PDFs are not supported yet)”, with Retry.', () => ST.openDetails('d7'), null, { id: 'details-failed' }),
    det('US-10', 'Archived document (J4): Restore, Open read-only and Delete; no “Change subjects” until it is restored (E7).', () => ST.openDetails('d3'), () => { doc('d3').archived = true; ST.L.tab = 'archived'; }, { id: 'details-archived' }),

    /* §6.6 */
    chat('US-3', 'New conversation: placeholder and optional example questions; no subjects (K1). Where navigation lands.', () => {}, { id: 'chat-new', live: true,
      setup: () => { S.thread = ST.pendingThread || ST.newThread(); ST.pendingThread = null; } }),
    chat('US-3', 'No documents yet: chat is replaced by “Upload a document first”.', () => { S.docs = []; S.convs = []; S.notes = []; S.thread = ST.newThread(); }, { id: 'chat-no-documents' }),
    chat('US-3', 'Documents still processing: a quiet hint above the input.', () => { S.thread = ST.newThread(); }, { id: 'chat-documents-processing' }),
    chat('US-4', 'Streaming answer with Stop.', () => {
      ST.conv('cv1').noteId = null;
      S.thread = ST.newThread({ convId: 'cv1', title: ST.J2[0].q });
      S.thread.messages.push(ST.M({ role: 'user', text: ST.J2[0].q }));
    }, { id: 'chat-streaming', afterEnter: () => ST.streamAnswer('react', { startAt: 0.2, speed: 130 }) }),
    chat('US-4', 'Answers with citations; the follow-up is answered from another document (one archived, “Archived”). No subject chips; citations open the viewer.', () => { S.citations = true; doc('d4').archived = true; j2(2); }, { id: 'chat-answer-citations' }),
    chat('US-4', 'Citations switched off: the same thread, answers unchanged.', () => { S.citations = false; j2(2); }, { id: 'chat-citations-off' }),
    chat('US-4', '“Not helpful” is pressed and opens an optional reason; “Helpful” pressed on the first answer.', () => {
      const t = j2(2); const a = t.messages.filter((m) => m.kind === 'answer');
      a[0].fb = 'up'; Object.assign(a[1], { fb: 'down', reasonOpen: true, reason: "Citation doesn't match" });
    }, { id: 'chat-feedback-reason' }),
    chat('US-4b', 'Documents used (3): ReAct, Retrieval-Augmented Generation and PPO, in order of first use.', () => { j2(3); }, { id: 'chat-documents-used', afterEnter: () => { ST.chatEnter(); ST.openDocsUsed(); } }),
    chat('US-4b', 'Documents used before the first answer: “Documents used to answer will appear here.”', () => { S.thread = ST.newThread(); }, { id: 'chat-documents-used-empty', afterEnter: () => ST.openDocsUsed() }),
    chat('US-4b', 'A deleted document stays listed as “Deleted”, can\'t be opened; “Deleted documents can\'t be opened.”', () => {
      const t = ST.newThread({ convId: 'cv2', title: ST.conv('cv2').title, tokens: [9870, 2140] });
      t.messages.push(ST.M({ role: 'user', text: t.title }), ST.answerMsg('cot'), ST.M({ role: 'user', text: ST.J2[0].q }), ST.answerMsg('react'));
      S.thread = t; ST.deleteDoc(doc('d2')); S.deletedNotice = null;
    }, { id: 'chat-documents-used-deleted', afterEnter: () => { ST.chatEnter(); ST.openDocsUsed(); } }),
    chat('US-10c', 'A citation to a deleted document reads “Deleted document”, with no link.', () => {
      const t = ST.newThread({ convId: 'cv2', title: ST.conv('cv2').title, tokens: [9870, 2140] });
      t.messages.push(ST.M({ role: 'user', text: t.title }), ST.answerMsg('cot'));
      S.thread = t; ST.deleteDoc(doc('d2')); S.deletedNotice = null;
    }, { id: 'chat-citation-deleted' }),
    chat('US-5', 'Decline: a document on the topic is needed to continue; “Upload a document” is the only action. Adds nothing to Documents used.', () => {
      const t = j2(1); const q = "What's the best laptop for research?";
      t.messages.push(ST.M({ role: 'user', text: q }), ST.M({ role: 'tutor', kind: 'decline', question: q, topic: 'choosing a laptop' }));
    }, { id: 'chat-decline' }),
    chat('US-10', 'No active documents: all documents archived; history stays readable and a new question gets “Upload”.', () => {
      S.docs.forEach((d) => { if (d.state === 'ready') d.archived = true; });
      const t = ST.threadFromConv('cv5'); const q = 'What does the clipping range control?';
      t.messages.push(ST.M({ role: 'user', text: q }), ST.M({ role: 'tutor', kind: 'nodocs', question: q }));
      S.thread = t;
    }, { id: 'chat-no-active-documents' }),
    chat('US-7', '“Summarize lesson” in progress.', () => { j2(2, { summarizing: true, summaryHold: true }); }, { id: 'chat-summarize-progress' }),
    chat('US-7', 'Note saved: confirmation with a link; the header now links the note.', () => { const t = j2(2); ST.makeNote(t, 'saved'); }, { id: 'chat-summarize-done' }),
    chat('US-7', 'A note exists and wasn\'t edited: “Update lesson note” replaces it directly.', () => { S.thread = ST.threadFromConv('cv1'); }, { id: 'chat-update-note' }),
    chat('US-7', 'The note was edited: “You\'ve edited this note. Replace it with a new summary?”', () => { S.thread = ST.threadFromConv('cv2'); }, { id: 'chat-update-edited-note', afterEnter: () => { ST.chatEnter(); ST.actions.summarize(); } }),
    chat('US-13', 'Archived conversation: banner with Restore, input disabled.', () => { S.thread = ST.threadFromConv('cv6'); }, { id: 'chat-archived' }),
    chat('US-9', 'Rate limited: per minute “You can send again at 11:25 (GMT+7)”, daily “You can send again at 00:00 (GMT+7)”; input disabled until then.', () => { j2(2, { rateLimit: 42 }); }, { id: 'chat-rate-limited', afterEnter: () => { ST.chatEnter(); ST.startRateLimit(42); } }),
    chat('US-4', 'The answer failed: Retry.', () => { const t = j2(1); t.messages.push(ST.M({ role: 'user', text: ST.J2[1].q }), ST.M({ role: 'tutor', kind: 'error' })); }, { id: 'chat-error' }),
    chat('US-7', 'Started from a note: “Started from note: title” at the top.', () => {
      if (ST.pendingThread) { S.thread = ST.pendingThread; ST.pendingThread = null; return; }
      S.thread = ST.newThread({ fromNote: 'n2', title: 'When does chain-of-thought stop helping?' });
      S.thread.messages.push(ST.M({ role: 'user', text: 'When does chain-of-thought stop helping?' }), ST.answerMsg('cot'));
      S.thread.tokens = [3260, 402];
    }, { id: 'chat-from-note' }),
    chat('US-4', 'J1 ends here: the first cited answer from freshly uploaded papers; no subjects to choose.', () => {
      newUser('ready'); S.thread = ST.j2Thread(1, { convId: null }); S.convs.push({ id: 'cv1', title: ST.J2[0].q, answers: ['react'], subjects: ['agents'], last: ST.TODAY + 'T11:31', noteId: null, archived: false, tokens: [3920, 412] }); S.thread.convId = 'cv1';
    }, { id: 'chat-first-answer' }),

    /* §6.12 */
    view('Opened from Documents used: page 1 of ReAct…, no highlight.', () => ST.openViewer('d3', { page: 1, from: 'docs' }), () => { j2(3); }, { id: 'viewer-document' }),
    view('Opened from the citation “ReAct…, p. 3”: page 3, the cited passage highlighted and in view.', () => ST.openViewer('d3', { page: 3, highlight: { page: 3 }, from: 'chat' }), () => { j2(2); }, { id: 'viewer-citation-highlight' }),
    view('Cited page shown: “Couldn\'t highlight the passage on this page.”', () => ST.openViewer('d3', { page: 5, highlight: { page: 5 }, noHighlight: true, from: 'chat' }), () => { j2(2); }, { id: 'viewer-no-highlight' }),
    view('An archived document opens read-only with “Archived” and “Restore” in the header.', () => ST.openViewer('d4', { page: 2, highlight: { page: 2 }, from: 'chat' }), () => { doc('d4').archived = true; j2(2); }, { id: 'viewer-archived' }),
    view('Loading: page skeleton while the cited page loads first.', () => ST.openViewer('d3', { page: 3, highlight: { page: 3 }, from: 'chat', status: 'loading' }), () => { j2(2); }, { id: 'viewer-loading' }),
    view('Error: “We couldn\'t open this document.” with Retry.', () => ST.openViewer('d3', { page: 3, highlight: { page: 3 }, from: 'chat', status: 'error' }), () => { j2(2); }, { id: 'viewer-error' }),

    /* §6.7 */
    { id: 'conversations-active', live: true, group: 'Conversations', ref: '§6.7 · US-13', desc: 'Live list: subject chips of the documents used, number of documents used, last activity, note indicator.', setup: () => ST.resetList(), view: ST.conversationsView },
    { id: 'conversations-archived', group: 'Conversations', ref: '§6.7 · US-13', desc: 'Archived tab with Restore.', setup: () => { fresh(); ST.resetList({ tab: 'archived' }); }, view: ST.conversationsView },
    { id: 'conversations-filtered', group: 'Conversations', ref: '§6.7 · US-13', desc: 'Subject filter matches any subject of a conversation\'s documents used.', setup: () => { fresh(); ST.resetList({ subject: 'agents' }); }, view: ST.conversationsView },
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

    /* §6.10 */
    { id: 'usage-overview', live: true, group: 'Usage', ref: '§6.10 · US-9', desc: 'Today (the GMT+7 day) and all time; Conversations, Document processing, Background.', setup: () => { ST.U = { key: 'last', dir: 'desc' }; }, view: ST.usageView },


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
    { id: 'J1', title: 'First run', summary: 'From the landing page, sign up, land on the empty Library, upload 3 PDFs, accept subjects, get a first cited answer.', steps: [
      { state: 'landing-default', text: 'Landing page: “Create an account”' },
      { state: 'auth-sign-up', text: 'Sign up on the Keycloak page' },
      { state: 'auth-verify-email', text: 'Verify the email address' },
      { state: 'library-empty', text: 'Land on the empty Library' },
      { state: 'library-uploading', text: 'Drop 3 PDFs: progress in the upload tray' },
      { state: 'library-first-processing', text: 'Watch processing: titles first, subjects later' },
      { state: 'library-first-choose', text: 'Processing finished: 3 documents need subjects' },
      { state: 'picker-step-through', text: 'Accept suggestions; each document is ready on save' },
      { state: 'library-first-ready', text: 'All ready: “Ask a question”' },
      { state: 'chat-first-answer', text: 'The first cited answer' }
    ] },
    { id: 'J2', title: 'Everyday question', summary: 'Ask with no subject to choose, get a cited answer, follow up from another document, check Documents used, summarize, open the note.', steps: [
      { state: 'chat-new', text: 'Open Chat: nothing to choose, just ask' },
      { state: 'chat-streaming', text: 'Ask: the answer streams in' },
      { state: 'chat-answer-citations', text: 'Cited answer; the follow-up comes from another document' },
      { state: 'chat-documents-used', text: 'Open Documents used' },
      { state: 'chat-summarize-progress', text: '“Summarize lesson”' },
      { state: 'chat-summarize-done', text: 'Note saved' },
      { state: 'notes-editor', text: 'Open the note' }
    ] },
    { id: 'J3', title: 'Check the source', summary: 'Open a citation in the document viewer with the passage highlighted, go back, and open another document from Documents used.', steps: [
      { state: 'chat-answer-citations', text: 'An answer with citations' },
      { state: 'viewer-citation-highlight', text: 'Select “ReAct…, p. 3”: the passage is highlighted' },
      { state: 'chat-documents-used', text: 'Back to the conversation; open Documents used' },
      { state: 'viewer-document', text: 'Open a document from the list at page 1' }
    ] },
    { id: 'J4', title: 'Library upkeep', summary: 'Filter, open, change subjects, fix the title, archive, restore, delete another document, and retry a failed file.', steps: [
      { state: 'library-filtered-by-subject', text: 'Filter the Library by AI Agents' },
      { state: 'details-ready', text: 'Open ReAct' },
      { state: 'picker-change-subjects', text: 'Change its subjects' },
      { state: 'details-edit-title', text: 'Fix its display title' },
      { state: 'library-archived-after-archive', text: 'Archive it, then find it under Archived' },
      { state: 'details-archived', text: 'Restore it' },
      { state: 'library-more-menu', text: 'More → Delete on Chain-of-Thought Prompting…' },
      { state: 'library-delete-confirm', text: 'Confirm: Cancel is focused; Delete' },
      { state: 'library-deleted', text: 'Deleted: the row is gone' },
      { state: 'chat-documents-used-deleted', text: 'Marked “Deleted” in a conversation\'s documents used' },
      { state: 'library-failed', text: 'A failed document' },
      { state: 'library-retry-processing', text: 'Retry: processing again' }
    ] }
  ];

  ST.boot();
})();
