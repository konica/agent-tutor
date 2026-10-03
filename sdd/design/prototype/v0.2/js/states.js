/* Smart Tutor — the state index: every named state <screen>-<state>@v0.2, in review order. */
(function () {
  const ST = window.ST;
  const S = ST.S;

  const chat = (desc, setup, extra = {}) => Object.assign({ group: 'Chat', ref: '§5.4 · US-3–7, US-9', desc, setup, view: ST.chatView, afterRender: ST.chatAfter, afterEnter: ST.chatEnter }, extra);
  const thread = (cid, o) => { S.thread = ST.threadFromConv(cid, o); return S.thread; };
  const persistedCitations = () => ST.ls.get('st_citations', 'on') !== 'off';

  const defs = [
    { id: 'index', group: 'Overview', desc: 'Round 1 overview, brand direction and links to every state.', view: ST.indexView },

    /* 5.2 */
    { id: 'auth-sign-in', group: 'Sign in / sign up', ref: '§5.2 · US-1', desc: 'Keycloak hosted login page with the Smart Tutor theme.', view: ST.authSignIn },
    { id: 'auth-sign-up', group: 'Sign in / sign up', ref: '§5.2 · US-1', desc: 'Keycloak registration, showing an inline field error.', view: ST.authSignUp },
    { id: 'auth-verify-email', group: 'Sign in / sign up', ref: '§5.2 · US-1', desc: 'Keycloak email-verification page.', view: ST.authVerify },

    /* 5.3 */
    { id: 'subjects-first-run', group: 'Subject enrollment', ref: '§5.3 · US-2', desc: 'First sign-in: Continue stays disabled until a subject is chosen.', setup: () => { ST.fr.picked = []; }, view: ST.firstRunView },
    { id: 'subjects-first-run-selected', group: 'Subject enrollment', ref: '§5.3 · US-2', desc: 'First run with IELTS chosen; Continue is enabled.', setup: () => { ST.fr.picked = ['IELTS']; }, view: ST.firstRunView },
    { id: 'subjects-manage', group: 'Subject enrollment', ref: '§5.3 · US-2', desc: 'All subjects with enroll / leave.', setup: () => { S.enrolled = ['IELTS', 'AI Agents']; }, view: ST.subjectsView },
    { id: 'subjects-leave-dialog', group: 'Subject enrollment', ref: '§5.3 · US-2', desc: 'Confirm dialog: conversations become read-only until re-enrolling.', setup: () => { S.enrolled = ['IELTS', 'AI Agents']; }, view: ST.subjectsView, afterEnter: () => ST.leaveDialog('IELTS') },
    { id: 'subjects-left', group: 'Subject enrollment', ref: '§5.3 · US-2', desc: 'After leaving IELTS: Enroll is offered again.', setup: () => { S.enrolled = ['AI Agents']; }, view: ST.subjectsView },

    /* 5.4 */
    chat('No subject picker; example questions for each enrolled subject.', () => {
      if (!ST.pendingKeepEnrolled && !S.enrolled.length) S.enrolled = ['IELTS', 'AI Agents'];
      ST.pendingKeepEnrolled = false;
      S.thread = ST.pendingThread || ST.newThread({ draft: ST.pendingDraft || '' });
      ST.pendingThread = null; ST.pendingDraft = null;
    }, { id: 'chat-empty' }),
    chat('After the first answer: subject chip with “Change” in the header.', () => thread('c1'), { id: 'chat-subject-detected' }),
    chat('“Change” restarts the conversation under the chosen subject.', () => thread('c1'), { id: 'chat-change-subject', afterEnter: () => { ST.chatEnter(); ST.actions['change-subject'](); } }),
    chat('Tutor asks “Which subject is this about?” with one button per subject.', () => {
      const q = 'How do I get better at planning?';
      S.thread = ST.newThread({ title: q });
      S.thread.messages.push(ST.M({ role: 'user', text: q }), ST.M({ role: 'tutor', kind: 'unsure', question: q }));
    }, { id: 'chat-detection-unsure' }),
    chat('Text appears progressively; Stop replaces Send.', () => {
      const c = ST.conv('c2');
      S.thread = ST.newThread({ convId: 'c2', title: c.title, subject: c.subject, noteId: null, tokens: [0, 0] });
      S.thread.messages.push(ST.M({ role: 'user', text: c.title }), ST.M({ role: 'sys', text: 'Subject set to AI Agents from your question.' }));
    }, { id: 'chat-streaming', afterEnter: () => ST.streamAnswer('react', { startAt: 0.25, speed: 140 }) }),
    chat('Citations on (default): title and page under every answer; archived badge.', () => {
      S.citations = true;
      const t = thread('c2'); ST.addFollowUp(t, "What's the difference between a tool and a skill in an agent?", 'tool_skill');
    }, { id: 'chat-answer-citations' }),
    chat('Citations switched off: the same thread, answers unchanged.', () => {
      S.citations = false;
      const t = thread('c2'); ST.addFollowUp(t, "What's the difference between a tool and a skill in an agent?", 'tool_skill');
    }, { id: 'chat-citations-off' }),
    chat('Thumbs down opens an optional reason form.', () => {
      S.citations = true;
      const t = thread('c2'); ST.addFollowUp(t, "What's the difference between a tool and a skill in an agent?", 'tool_skill');
      const answers = t.messages.filter((m) => m.kind === 'answer');
      answers[0].fb = 'up';
      Object.assign(answers[1], { fb: 'down', reasonOpen: true, reason: "Source doesn't match" });
    }, { id: 'chat-feedback-reason' }),
    chat('Off-subject question in an IELTS thread: a friendly decline, not an error.', () => {
      const t = thread('c1');
      t.messages.push(ST.M({ role: 'user', text: 'What is the ReAct pattern?' }), ST.M({ role: 'tutor', kind: 'decline', subject: 'IELTS', question: 'What is the ReAct pattern?' }));
    }, { id: 'chat-decline' }),
    chat('“Summarize lesson” in progress.', () => { const t = thread('c4'); t.summarizing = true; t.summaryHold = true; }, { id: 'chat-summarize-progress' }),
    chat('Note saved: confirmation with a link; header shows the note and “Update lesson note”.', () => { const t = thread('c1'); t.summaryDone = 'saved'; }, { id: 'chat-summarize-done' }),
    chat('A note exists: “Update lesson note” warns that it overwrites the previous version.', () => thread('c1'), { id: 'chat-update-note-warning', afterEnter: () => { ST.chatEnter(); ST.actions.summarize(); } }),
    chat('Learner left the subject: “Enroll in IELTS again to continue”, input disabled.', () => { thread('c6', { readOnly: 'left' }); }, { id: 'chat-read-only-left-subject' }),
    chat('Archived thread: “Restore to continue”, input disabled.', () => { thread('c8'); }, { id: 'chat-read-only-archived' }),
    chat('Too many messages: countdown, input disabled until it ends.', () => { const t = thread('c3'); t.rateLimit = 24; }, { id: 'chat-rate-limited', afterEnter: () => { ST.chatEnter(); ST.startRateLimit(24); } }),
    chat('The answer failed: Retry.', () => {
      const t = thread('c3');
      t.messages.push(ST.M({ role: 'user', text: 'Can an agent have a skill without any tools?' }), ST.M({ role: 'tutor', kind: 'error' }));
    }, { id: 'chat-error' }),
    chat('Conversation started from a note: “Started from note: title” at the top.', () => {
      if (ST.pendingThread) { S.thread = ST.pendingThread; ST.pendingThread = null; return; }
      S.thread = ST.newThread({ subject: 'IELTS', fromNote: 'n1', title: 'How should I paraphrase the question in my introduction?' });
      ST.addFollowUp(S.thread, 'How should I paraphrase the question in my introduction?', 'ielts_paraphrase');
      S.thread.tokens = [2940, 96];
    }, { id: 'chat-from-note' }),

    /* 5.5 */
    { id: 'conversations-active', group: 'Conversations', ref: '§5.5 · US-13', desc: 'Newest first, filters, Active tab, note indicator on rows.', setup: () => ST.resetList(), view: ST.conversationsView },
    { id: 'conversations-archived', group: 'Conversations', ref: '§5.5 · US-13', desc: 'Archived tab with Restore.', setup: () => ST.resetList({ tab: 'archived' }), view: ST.conversationsView },
    { id: 'conversations-filtered', group: 'Conversations', ref: '§5.5 · US-13', desc: 'Date range and subject combined.', setup: () => ST.resetList({ subject: 'AI Agents', from: '2026-09-25' }), view: ST.conversationsView },
    { id: 'conversations-no-results', group: 'Conversations', ref: '§5.5 · US-13', desc: 'Empty state: no results for these filters.', setup: () => ST.resetList({ subject: 'AI Agents', from: '2026-09-01', to: '2026-09-20' }), view: ST.conversationsView },
    { id: 'conversations-empty', group: 'Conversations', ref: '§5.5 · US-13', desc: 'Empty state: no conversations yet.', setup: () => { ST.resetList(); ST.emptyDemo = true; }, view: ST.conversationsView },
    chat('Opened from the list: full history and the linked lesson note in the header.', () => thread('c1'), { id: 'conversations-open', group: 'Conversations', ref: '§5.5 · US-13' }),

    /* 5.6 */
    { id: 'notes-active', group: 'Notes', ref: '§5.6 · US-7, US-13b', desc: 'Notes list: title, subject, date, link to the source conversation.', setup: () => ST.resetList(), view: ST.notesView },
    { id: 'notes-archived', group: 'Notes', ref: '§5.6 · US-7, US-13b', desc: 'Archived notes with Restore.', setup: () => ST.resetList({ tab: 'archived' }), view: ST.notesView },
    { id: 'notes-empty', group: 'Notes', ref: '§5.6 · US-7, US-13b', desc: 'Empty state: no lesson notes yet.', setup: () => { ST.resetList(); ST.emptyDemo = true; }, view: ST.notesView },
    { id: 'notes-editor', group: 'Notes', ref: '§5.6 · US-7, US-13b', desc: 'Markdown editor and preview side by side; Save, Archive, Discuss this note.', setup: () => ST.openEditor('n1', 'split'), view: ST.editorView },
    { id: 'notes-editor-unsaved', group: 'Notes', ref: '§5.6 · US-7, US-13b', desc: 'Edited note with unsaved changes; Save is enabled.', setup: () => { ST.openEditor('n2', 'split'); ST.ed.body += '\n\n## My example\n\n- Thought: I need today\'s weather.\n- Action: call the weather tool.'; ST.ed.dirty = true; }, view: ST.editorView },
    { id: 'notes-preview', group: 'Notes', ref: '§5.6 · US-7, US-13b', desc: 'Note view in Preview mode.', setup: () => ST.openEditor('n2', 'preview'), view: ST.editorView },
    { id: 'notes-archived-view', group: 'Notes', ref: '§5.6 · US-7, US-13b', desc: 'Archived note: read-only with Restore.', setup: () => ST.openEditor('n4'), view: ST.editorView },

    /* 5.7 / 5.8 */
    { id: 'usage-overview', group: 'Usage & settings', ref: '§5.7–5.8 · US-9', desc: 'Total input/output tokens and a sortable table; no limits.', setup: () => { ST.U = { key: 'last', dir: 'desc' }; }, view: ST.usageView },
    { id: 'settings-default', group: 'Usage & settings', ref: '§5.7–5.8 · US-9', desc: 'Time zone from the browser, link to Subjects, appearance.', view: ST.settingsView },

    /* §6 Release 2 wireframes */
    { id: 'r2-quiz-select', group: 'Release 2 wireframes', ref: '§6 · US-14–16', desc: 'Select 1–10 active notes and generate a quiz.', r2: true, view: ST.r2QuizSelect },
    { id: 'r2-quiz-generating', group: 'Release 2 wireframes', ref: '§6 · US-14–16', desc: 'Quiz generation progress (up to ~15 s).', r2: true, view: ST.r2QuizGenerating },
    { id: 'r2-quiz-take', group: 'Release 2 wireframes', ref: '§6 · US-14–16', desc: 'Multiple-choice questions, four options each.', r2: true, view: ST.r2QuizTake },
    { id: 'r2-quiz-results', group: 'Release 2 wireframes', ref: '§6 · US-14–16', desc: 'Score, explanations, score per topic, retake, flag.', r2: true, view: ST.r2QuizResults },
    { id: 'r2-quizzes-list', group: 'Release 2 wireframes', ref: '§6 · US-14–16', desc: 'Same list pattern for quizzes.', r2: true, view: ST.r2QuizzesList },
    { id: 'r2-reports-list', group: 'Release 2 wireframes', ref: '§6 · US-14–16', desc: 'Daily / weekly reports with Generate now.', r2: true, view: ST.r2ReportsList },
    { id: 'r2-report-view', group: 'Release 2 wireframes', ref: '§6 · US-14–16', desc: 'Report: topics, conversations, quiz results, weak topics, recommendations.', r2: true, view: ST.r2ReportView },
    { id: 'r2-learn-next', group: 'Release 2 wireframes', ref: '§6 · US-14–16', desc: '“What should I learn next?” cards with Start learning.', r2: true, view: ST.r2LearnNext },

    /* §8, §9 */
    { id: 'components', group: 'Components & questions', ref: '§8–9', desc: 'Reusable components and tokens in both themes.', view: ST.componentsView },
    { id: 'brief-questions', group: 'Components & questions', ref: '§8–9', desc: 'Questions and proposed changes to brief v0.2.', view: ST.questionsView }
  ];

  ST.STATES = defs.map((d) => {
    const own = d.setup;
    return Object.assign({}, d, {
      setup: () => {
        S.r2 = !!d.r2;
        ST.emptyDemo = false;
        S.citations = persistedCitations();
        if (own) own();
      }
    });
  });

  ST.boot();
})();
