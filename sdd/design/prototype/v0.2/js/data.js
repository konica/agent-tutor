/* Smart Tutor — sample data for the round 1 prototype (brief v0.2, §7).
   All dates are relative to the brief date, 2 Oct 2026. */
window.ST = window.ST || {};

ST.TODAY = '2026-10-02';
ST.BRIEF = 'v0.2';

ST.SUBJECTS = [
  {
    id: 'IELTS', name: 'IELTS', icon: 'pen',
    desc: 'Academic and General Training preparation: Writing Tasks 1 and 2, Speaking, Reading and Listening strategies.',
    docs: 14, examples: [
      'How do I structure an IELTS Task 2 essay?',
      'How should I paraphrase the question in my introduction?',
      'What is the difference between Speaking Part 2 and Part 3?'
    ]
  },
  {
    id: 'AI Agents', name: 'AI Agents', icon: 'cpu',
    desc: 'How LLM agents plan, use tools and work with people: patterns, architectures and evaluation.',
    docs: 9, examples: [
      'What is the ReAct pattern?',
      "What's the difference between a tool and a skill in an agent?",
      'When should an agent ask a human for approval?'
    ]
  }
];

ST.USER = { name: 'Mai Nguyen', email: 'mai.nguyen@example.com', initials: 'MN' };

/* Canned tutor answers. Text uses **bold** and *italic*; paragraphs split on a blank line. */
ST.ANSWERS = {
  ielts_task2: {
    subject: 'IELTS',
    text: 'A strong Task 2 essay usually has four paragraphs.\n\n**Introduction (2–3 sentences).** Paraphrase the question, then give a clear position that answers it directly.\n\n**Body paragraphs 1 and 2.** Open each with a topic sentence that states one main idea. Support it with an explanation and a specific example, then link back to the question.\n\n**Conclusion (1–2 sentences).** Restate your position in new words. Don\'t add new ideas here.\n\nAim for 260–290 words and spend about five minutes planning before you write.',
    cites: [{ doc: 'IELTS Writing Guide', page: 18 }, { doc: 'IELTS Writing Guide', page: 21 }]
  },
  ielts_para: {
    subject: 'IELTS',
    text: 'Keep each body paragraph to one main idea, developed in four or five sentences: a topic sentence, an explanation, a specific example, and a link back to the question.\n\nExaminers reward clear progression more than length, so a focused 90-word paragraph scores better than a 150-word one that drifts.',
    cites: [{ doc: 'IELTS Writing Guide', page: 24 }]
  },
  ielts_paraphrase: {
    subject: 'IELTS',
    text: 'Paraphrase the question by changing both the words and the sentence structure, not just swapping synonyms.\n\nA reliable approach: change the word class (*decide* → *decision*), reorder the clauses, and replace general nouns with more precise ones. Then add your position in the next sentence.',
    cites: [{ doc: 'IELTS Writing Guide', page: 16 }]
  },
  ielts_generic: {
    subject: 'IELTS',
    text: 'The IELTS material suggests planning before you answer: note your main idea, two supporting points, and one example for each.\n\nIn the Speaking test, Part 2 asks you to talk for up to two minutes on a cue card, while Part 3 is a discussion of more abstract questions linked to the same topic.',
    cites: [{ doc: 'IELTS Speaking Handbook', page: 9 }]
  },
  react: {
    subject: 'AI Agents',
    text: 'ReAct is an agent pattern that interleaves **reasoning** and **acting**. At each step the model writes a short thought about what to do next, takes an action such as calling a tool, then reads the observation that comes back.\n\nThe loop repeats — thought, action, observation — until the agent has enough information to answer. Because the reasoning is written out, it is easier to see why the agent chose each tool and to spot where it went wrong.',
    cites: [{ doc: 'Agentic Design Patterns', page: 42 }, { doc: 'Agent Architectures Primer (2024 edition)', page: 7, archived: true }]
  },
  tool_skill: {
    subject: 'AI Agents',
    text: 'A **tool** is a single capability the agent can call, such as a search function or a calculator. It takes inputs and returns a result, with no judgement of its own.\n\nA **skill** is a packaged way of doing a task. It bundles instructions, and often several tool calls, into a reusable procedure the agent can follow.\n\nIn short: tools are the actions; skills describe when and how to combine them.',
    cites: [{ doc: 'Agentic Design Patterns', page: 58 }, { doc: 'Agentic Design Patterns', page: 61 }]
  },
  agents_generic: {
    subject: 'AI Agents',
    text: 'Agents usually ask a person for help when an action can\'t be undone, when their confidence is low, or when a policy requires approval.\n\nThe pattern is often called *human in the loop*: the agent pauses, explains the action it wants to take, and waits for a decision before it continues.',
    cites: [{ doc: 'Agentic Design Patterns', page: 117 }]
  },
  study_plan: {
    subject: null,
    text: '',
    cites: []
  }
};

ST.EXCERPTS = {
  'IELTS Writing Guide': 'Task 2 responses are assessed on Task Response, Coherence and Cohesion, Lexical Resource, and Grammatical Range and Accuracy. A clear position, maintained throughout, is central to Task Response…',
  'IELTS Speaking Handbook': 'In Part 2 the candidate is given one minute to prepare and should speak for one to two minutes. Part 3 develops the topic into a two-way discussion…',
  'Agentic Design Patterns': 'The ReAct loop alternates between a reasoning trace and an action. Each observation is appended to the context, allowing the model to revise its plan before the next step…',
  'Agent Architectures Primer (2024 edition)': 'Early agent frameworks combined chain-of-thought prompting with tool calls, an approach later formalised as ReAct…'
};

/* Conversations (newest first after sort). tokens: [in, out] */
ST.CONVERSATIONS = [
  { id: 'c1', title: 'How do I structure an IELTS Task 2 essay?', subject: 'IELTS', last: '2026-10-02T10:14', noteId: 'n1', archived: false, tokens: [12480, 3215], answer: 'ielts_task2' },
  { id: 'c2', title: 'What is the ReAct pattern?', subject: 'AI Agents', last: '2026-10-01T16:40', noteId: 'n2', archived: false, tokens: [18904, 4672], answer: 'react' },
  { id: 'c3', title: "What's the difference between a tool and a skill in an agent?", subject: 'AI Agents', last: '2026-09-30T09:05', noteId: null, archived: false, tokens: [6120, 1388], answer: 'tool_skill' },
  { id: 'c4', title: 'How should I paraphrase the question in my introduction?', subject: 'IELTS', last: '2026-09-28T19:22', noteId: null, archived: false, tokens: [8350, 2040], answer: 'ielts_paraphrase' },
  { id: 'c5', title: 'When should an agent ask a human for approval?', subject: 'AI Agents', last: '2026-09-25T14:10', noteId: 'n3', archived: false, tokens: [15230, 3902], answer: 'agents_generic' },
  { id: 'c6', title: 'What is the difference between Speaking Part 2 and Part 3?', subject: 'IELTS', last: '2026-09-21T08:47', noteId: null, archived: false, tokens: [4980, 1210], answer: 'ielts_generic' },
  { id: 'c7', title: 'How long should each body paragraph be?', subject: 'IELTS', last: '2026-09-14T20:31', noteId: null, archived: false, tokens: [7744, 1856], answer: 'ielts_para' },
  { id: 'c8', title: 'Is a planner agent the same as a router?', subject: 'AI Agents', last: '2026-09-10T11:02', noteId: null, archived: true, tokens: [5410, 1322], answer: 'agents_generic' },
  { id: 'c9', title: 'Linking words for Task 1 graph descriptions', subject: 'IELTS', last: '2026-09-03T18:15', noteId: 'n4', archived: true, tokens: [9120, 2475], answer: 'ielts_para' }
];

ST.NOTES = [
  {
    id: 'n1', title: 'Structuring a Task 2 essay', subject: 'IELTS', date: '2026-10-02T10:20', convId: 'c1', archived: false,
    body: '# Structuring a Task 2 essay\n\n## The four-paragraph plan\n\n- **Introduction** — paraphrase the question, then state a clear position.\n- **Body 1 and 2** — one main idea each: topic sentence, explanation, example, link back.\n- **Conclusion** — restate the position in new words. No new ideas.\n\n## Timing\n\n- Plan for about 5 minutes.\n- Aim for 260–290 words.\n\n## Remember\n\n> Examiners reward a clear position held throughout the essay.\n\n*Sources: IELTS Writing Guide, p. 18; IELTS Writing Guide, p. 21*'
  },
  {
    id: 'n2', title: 'The ReAct pattern', subject: 'AI Agents', date: '2026-10-01T16:52', convId: 'c2', archived: false,
    body: '# The ReAct pattern\n\nReAct interleaves **reasoning** and **acting**.\n\n## The loop\n\n1. Thought — decide what to do next.\n2. Action — call a tool.\n3. Observation — read the result.\n\nRepeat until there is enough information to answer.\n\n## Why it helps\n\n- The reasoning trace explains each tool choice.\n- Mistakes are easier to spot and debug.\n\n*Sources: Agentic Design Patterns, p. 42*'
  },
  {
    id: 'n3', title: 'Human-in-the-loop approvals', subject: 'AI Agents', date: '2026-09-25T14:30', convId: 'c5', archived: false,
    body: '# Human-in-the-loop approvals\n\nAsk a person before acting when:\n\n- the action can\'t be undone,\n- confidence is low, or\n- a policy requires approval.\n\n*Sources: Agentic Design Patterns, p. 117*'
  },
  {
    id: 'n4', title: 'Linking words for Task 1', subject: 'IELTS', date: '2026-09-03T18:30', convId: 'c9', archived: true,
    body: '# Linking words for Task 1\n\n- **Contrast:** whereas, by contrast, however\n- **Addition:** in addition, similarly\n- **Sequence:** subsequently, following this\n\n*Sources: IELTS Writing Guide, p. 9*'
  }
];

/* Release 2 wireframe data */
ST.QUIZ = [
  { q: 'In a Task 2 essay, where should you state your position?', opts: ['Only in the conclusion', 'In the introduction, and keep it throughout', 'In the first body paragraph', 'It is optional'], a: 1, pick: 1, topic: 'Task 2 structure', why: 'A clear position from the introduction onward supports Task Response.' },
  { q: 'How many main ideas should one body paragraph develop?', opts: ['One', 'Two', 'Three', 'As many as possible'], a: 0, pick: 0, topic: 'Task 2 structure', why: 'One developed idea per paragraph keeps progression clear.' },
  { q: 'What is the recommended Task 2 length range?', opts: ['150–180 words', '200–230 words', '260–290 words', '350+ words'], a: 2, pick: 1, topic: 'Task 2 structure', why: 'The guide recommends 260–290 words to stay above 250 without rushing.' },
  { q: 'Which best describes paraphrasing the question?', opts: ['Copying it exactly', 'Swapping one word', 'Changing words and structure', 'Skipping it'], a: 2, pick: 2, topic: 'Paraphrasing', why: 'Change both vocabulary and sentence structure.' },
  { q: 'In ReAct, what follows an action?', opts: ['A thought', 'An observation', 'The final answer', 'A new user prompt'], a: 1, pick: 1, topic: 'ReAct', why: 'Each action returns an observation that informs the next thought.' },
  { q: 'What does a skill add on top of a tool?', opts: ['Faster execution', 'A packaged procedure for when and how to use tools', 'A different model', 'Nothing'], a: 1, pick: 3, topic: 'Tools and skills', why: 'Skills bundle instructions and tool calls into a reusable procedure.' }
];
