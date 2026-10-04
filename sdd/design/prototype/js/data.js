/* Smart Tutor — sample data for round 3 (brief v0.4, §9). Dates relative to 3 Oct 2026. */
window.ST = window.ST || {};

ST.TODAY = '2026-10-03';
ST.BRIEF = 'v0.4';
/* D8: one time zone for everyone in Release 1. */
ST.TZ = { short: 'GMT+7', long: 'GMT+7 (Ho Chi Minh City)' };
ST.USER = { name: 'Mai Nguyen', first: 'Mai', email: 'mai.nguyen@example.com', initials: 'MN', tz: 'Asia/Ho_Chi_Minh' };

/* Shared subject catalog. `mine` is Mai's personal name for a subject (only she sees it). */
ST.CATALOG = [
  { id: 'llm', shared: 'Large Language Models', mine: 'LLMs', docs: 0 },
  { id: 'agents', shared: 'AI Agents', mine: null },
  { id: 'rag', shared: 'Retrieval-Augmented Generation', mine: null },
  { id: 'rl', shared: 'Reinforcement Learning', mine: null },
  { id: 'tool', shared: 'Tool Use', mine: null, isNew: true },
  { id: 'c-nlp', shared: 'Natural Language Processing', mine: null },
  { id: 'c-ir', shared: 'Information Retrieval', mine: null },
  { id: 'c-prompt', shared: 'Prompt Engineering', mine: null },
  { id: 'c-eval', shared: 'LLM Evaluation', mine: null },
  { id: 'c-kg', shared: 'Knowledge Graphs', mine: null },
  { id: 'c-ml', shared: 'Machine Learning', mine: null },
  { id: 'c-transformers', shared: 'Transformers', mine: null },
  { id: 'c-mas', shared: 'Multi-Agent Systems', mine: null }
];

/* Documents (§9). state: uploading | processing | choose | ready | failed. */
ST.DOCS = [
  { id: 'd1', title: 'Attention Is All You Need', extracted: 'Attention Is All You Need', authors: 'Vaswani et al.', year: 2017, doi: '10.48550/arXiv.1706.03762', file: 'attention-is-all-you-need.pdf', pages: 15, size: '2.2 MB', uploaded: '2026-09-12T09:30', state: 'ready', subjects: ['llm'], archived: false, tokens: [41200, 1850],
    summary: 'Introduces the Transformer, a sequence model built entirely on attention, without recurrence or convolution. It reaches state-of-the-art translation quality while training much faster in parallel.' },
  { id: 'd2', title: 'Chain-of-Thought Prompting Elicits Reasoning in Large Language Models', extracted: 'Chain-of-Thought Prompting Elicits Reasoning in Large Language Models', authors: 'Wei et al.', year: 2022, doi: '10.48550/arXiv.2201.11903', file: '2201.11903v6.pdf', pages: 43, size: '1.9 MB', uploaded: '2026-09-14T15:02', state: 'ready', subjects: ['llm', 'agents'], archived: false, tokens: [96400, 2210],
    summary: 'Shows that prompting large models with a few worked examples that spell out intermediate reasoning steps improves arithmetic, commonsense and symbolic reasoning. The effect appears only in sufficiently large models.' },
  { id: 'd3', title: 'ReAct: Synergizing Reasoning and Acting in Language Models', extracted: 'ReAct: Synergizing Reasoning and Acting in Language Models', authors: 'Yao et al.', year: 2022, doi: '10.48550/arXiv.2210.03629', file: 'react-yao-2022.pdf', pages: 33, size: '3.1 MB', uploaded: '2026-09-20T10:11', state: 'ready', subjects: ['agents'], archived: false, tokens: [0, 0], dedup: true,
    summary: 'Proposes prompting language models to interleave reasoning traces with task actions such as search calls. Reasoning helps plan and track actions, while actions gather outside information that keeps reasoning grounded.' },
  { id: 'd4', title: 'Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks', extracted: 'Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks', authors: 'Lewis et al.', year: 2020, doi: '10.48550/arXiv.2005.11401', file: 'lewis-rag-2020.pdf', pages: 19, size: '0.9 MB', uploaded: '2026-09-22T08:44', state: 'ready', subjects: ['rag'], archived: false, tokens: [48800, 1990],
    summary: 'Combines a pretrained sequence-to-sequence model with a dense retriever over Wikipedia. Generating from retrieved passages improves factual question answering and produces more specific, less hallucinated text.' },
  { id: 'd5', title: 'Toolformer: Language Models Can Teach Themselves to Use Tools', extracted: 'Toolformer: Language Models Can Teach Themselves to Use Tools', authors: 'Schick et al.', year: 2023, doi: '10.48550/arXiv.2302.04761', file: 'toolformer.pdf', pages: 24, size: '1.4 MB', uploaded: '2026-10-03T10:52', state: 'choose', subjects: [], archived: false, tokens: [6100, 420],
    suggestions: [{ id: 'agents', origin: 'yours' }, { id: 'llm', origin: 'yours' }, { id: 'tool', origin: 'new' }],
    summary: 'Teaches a language model to decide when to call external tools such as a calculator, search engine or calendar, using self-supervised examples. Tool use improves zero-shot results without hurting core language modelling.' },
  { id: 'd6', title: 'Agentic Design Patterns', extracted: 'Agentic Design Patterns', authors: 'Antonio Gulli', year: null, book: true, doi: null, file: 'agentic-design-patterns.pdf', pages: 424, size: '18.6 MB', uploaded: '2026-10-03T10:41', state: 'processing', subjects: [], archived: false, tokens: [7300, 380],
    summary: 'A practical book of reusable patterns for building agents, from prompt chaining and routing to tool use, planning, memory and multi-agent collaboration. Each pattern pairs an explanation with code examples.' },
  { id: 'd7', title: 'lecture-03-scan.pdf', extracted: null, authors: null, year: null, doi: null, file: 'lecture-03-scan.pdf', pages: 28, size: '11.4 MB', uploaded: '2026-10-02T21:15', state: 'failed', failReason: 'No text layer (scanned PDFs are not supported yet)', scanned: true, attempts: 1, subjects: [], archived: false, tokens: [0, 0], summary: null },
  { id: 'd8', title: 'Proximal Policy Optimization Algorithms', extracted: 'Proximal Policy Optimization Algorithms', authors: 'Schulman et al.', year: 2017, doi: '10.48550/arXiv.1707.06347', file: 'ppo-schulman-2017.pdf', pages: 12, size: '0.7 MB', uploaded: '2026-09-25T13:20', state: 'ready', subjects: ['rl'], archived: false, tokens: [27900, 1720],
    summary: 'Introduces PPO, a policy-gradient method that optimises a clipped surrogate objective so each update stays close to the previous policy. It is simpler than trust-region methods and performs as well or better.' },
  { id: 'd9', title: 'Language Models are Few-Shot Learners', extracted: 'Language Models are Few-Shot Learners', authors: 'Brown et al.', year: 2020, doi: '10.48550/arXiv.2005.14165', file: 'gpt3-brown-2020.pdf', pages: 75, size: '6.6 MB', uploaded: '2026-08-30T17:05', state: 'ready', subjects: ['llm'], archived: true, tokens: [158300, 2340],
    summary: 'Describes GPT-3, a 175-billion-parameter language model that performs many tasks from a few examples in the prompt, without fine-tuning. It also discusses limitations and broader impacts.' }
];

/* J1 sample upload: three PDFs dropped on an empty Library. */
ST.J1_FILES = [
  { file: 'attention-is-all-you-need.pdf', size: '2.2 MB', from: 'd1', suggestions: [{ id: 'llm', origin: 'shared' }, { id: 'c-transformers', origin: 'shared' }, { id: 'c-nlp', origin: 'shared' }] },
  { file: 'react-yao-2022.pdf', size: '3.1 MB', from: 'd3', suggestions: [{ id: 'agents', origin: 'shared' }, { id: 'llm', origin: 'shared' }, { id: 'c-prompt', origin: 'shared' }] },
  { file: 'lewis-rag-2020.pdf', size: '0.9 MB', from: 'd4', suggestions: [{ id: 'rag', origin: 'shared' }, { id: 'c-ir', origin: 'shared' }, { id: 'llm', origin: 'shared' }] }
];

/* Tutor answers. cites: [{doc, page}] — page null means "page unavailable". */
ST.ANSWERS = {
  react: {
    text: 'ReAct prompts a language model to alternate between **reasoning traces** and **actions**. A thought plans the next step or updates what the model knows; an action, such as a search call, fetches new information; the observation that comes back feeds the next thought.\n\nThe two halves support each other: reasoning decides which action is worth taking, and actions bring in outside facts so the reasoning isn\'t built only on what the model remembers.',
    quote: { doc: 'd3', page: 3, text: 'reasoning traces help the model induce, track, and update action plans as well as handle exceptions, while actions allow it to interface with external sources' },
    cites: [{ doc: 'd3', page: 3 }, { doc: 'd3', page: 5 }]
  },
  rag_loop: {
    text: 'Retrieval reduces hallucination by grounding each step in passages the model actually read. In a ReAct loop, the action step can be a retrieval call: the model searches, reads the returned passage as an observation, and reasons from that evidence instead of from memory alone.\n\nRAG makes this explicit by conditioning generation on retrieved documents, which the authors found produced more specific and more factual answers.',
    cites: [{ doc: 'd4', page: 2 }, { doc: 'd3', page: 6 }]
  },
  attention: {
    text: 'Self-attention lets every token in a sequence look at every other token and decide how much each one matters. Each token is projected into a **query**, a **key** and a **value**; the query is compared with all keys, the scores are normalised with a softmax, and the output is the weighted sum of the values.\n\nRunning several of these in parallel — multi-head attention — lets the model track different kinds of relationships at once.',
    quote: { doc: 'd1', page: 3, text: 'An attention function can be described as mapping a query and a set of key-value pairs to an output, where the query, keys, values, and output are all vectors.' },
    cites: [{ doc: 'd1', page: 3 }, { doc: 'd1', page: 4 }]
  },
  ppo: {
    text: 'PPO limits how far one update can move the policy. It takes the ratio between the new and old probability of each action and **clips** that ratio to a small range around 1, typically 0.8 to 1.2.\n\nThe objective uses the smaller of the clipped and unclipped terms, so the update gains nothing from pushing the policy further than the clip allows. This keeps training stable without the second-order maths of trust-region methods.',
    cites: [{ doc: 'd8', page: 3 }, { doc: 'd8', page: null }]
  },
  cot: {
    text: 'Chain-of-thought prompting adds worked examples that spell out intermediate reasoning steps before the final answer. The model then imitates that format and reasons step by step on new problems.\n\nThe authors found the gains appear only in large models, and are largest on multi-step arithmetic and symbolic tasks.',
    cites: [{ doc: 'd2', page: 2 }, { doc: 'd2', page: 7 }]
  },
  rag_dense: {
    text: 'RAG uses a dense retriever because it is trained together with the generator: the query encoder learns which passages actually help produce the right answer. A fixed keyword method like BM25 can\'t adapt in that way.\n\nThe paper reports that the learned retriever improved results on most tasks, though BM25 remained competitive on fact verification.',
    cites: [{ doc: 'd4', page: 4 }, { doc: 'd4', page: 7 }]
  },
  generic_agents: {
    text: 'Your AI Agents documents describe agents as a loop of planning, acting with tools, and observing results. The ReAct paper shows that writing out the reasoning between actions makes this loop easier to follow and correct.',
    cites: [{ doc: 'd3', page: 2 }]
  },
  generic_llm: {
    text: 'Your LLMs documents cover how Transformer language models process text with attention, and how prompting techniques such as chain-of-thought change the way they reason.',
    cites: [{ doc: 'd1', page: 2 }, { doc: 'd2', page: 1 }]
  },
  generic_rag: {
    text: 'Your Retrieval-Augmented Generation documents describe pairing a retriever with a generator, so answers are produced from passages fetched at question time rather than from model memory alone.',
    cites: [{ doc: 'd4', page: 1 }]
  },
  generic_rl: {
    text: 'Your Reinforcement Learning documents focus on policy-gradient training, where PPO keeps each policy update small and stable.',
    cites: [{ doc: 'd8', page: 1 }]
  },
  long_docs: {
    text: 'For long inputs, your documents point to two different strategies. The Transformer\'s self-attention compares every token with every other one, so cost grows with the square of the input length. RAG avoids feeding everything in at once: it retrieves only the few passages relevant to the question.',
    cites: [{ doc: 'd1', page: 6 }, { doc: 'd4', page: 3 }]
  }
};

/* Conversations. subjects: up to 3 subject ids. */
ST.CONVERSATIONS = [
  { id: 'cv1', title: 'How does ReAct combine reasoning and acting?', subjects: ['agents', 'rag', 'llm'], last: '2026-10-03T09:48', noteId: 'n1', archived: false, tokens: [12480, 3215] },
  { id: 'cv2', title: 'What does chain-of-thought prompting change about how a model answers?', subjects: ['llm', 'agents'], last: '2026-10-02T16:20', noteId: 'n2', archived: false, tokens: [9870, 2140], answer: 'cot' },
  { id: 'cv3', title: 'How does self-attention scale with sequence length?', subjects: ['llm'], last: '2026-09-30T11:05', noteId: null, archived: false, tokens: [6230, 1480], answer: 'long_docs' },
  { id: 'cv4', title: 'Why does RAG use a dense retriever instead of BM25?', subjects: ['rag'], last: '2026-09-28T19:40', noteId: 'n3', archived: false, tokens: [8110, 1902], answer: 'rag_dense' },
  { id: 'cv5', title: 'What problem does the PPO clipped objective solve?', subjects: ['rl'], last: '2026-09-25T14:12', noteId: null, archived: false, tokens: [5340, 1296], answer: 'ppo' },
  { id: 'cv6', title: 'What does a Transformer encoder block contain?', subjects: ['llm'], last: '2026-09-12T10:30', noteId: 'n4', archived: true, tokens: [4420, 1150], answer: 'attention' }
];

ST.NOTES = [
  { id: 'n1', title: 'ReAct: reasoning and acting', subjects: ['agents', 'rag', 'llm'], date: '2026-10-03T09:55', convId: 'cv1', archived: false, edited: false,
    body: '# ReAct: reasoning and acting\n\n## The loop\n\n1. **Thought** — plan the next step or update what the model knows.\n2. **Action** — call a tool, such as search.\n3. **Observation** — read the result and feed it into the next thought.\n\n## Why retrieval helps\n\n- Actions can be retrieval calls, so each step is grounded in a real passage.\n- Grounding reduces hallucination compared with reasoning from memory alone.\n\n## Self-attention, briefly\n\n- Each token becomes a query, a key and a value.\n- Multi-head attention tracks several kinds of relationship at once.\n\n*Sources: ReAct, p. 3; Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks, p. 2; Attention Is All You Need, p. 3*' },
  { id: 'n2', title: 'Chain-of-thought prompting', subjects: ['llm', 'agents'], date: '2026-10-02T16:31', convId: 'cv2', archived: false, edited: true, editedAt: '2026-10-02T21:10',
    body: '# Chain-of-thought prompting\n\nWorked examples that show **intermediate steps** make large models reason step by step.\n\n- Gains appear only in large models.\n- Biggest on multi-step arithmetic and symbolic tasks.\n\n## My notes\n\n- Try this on the agent planner prompts for chapter 3 of my thesis.\n\n*Sources: Chain-of-Thought Prompting…, p. 2*' },
  { id: 'n3', title: 'Dense retrieval in RAG', subjects: ['rag'], date: '2026-09-28T19:52', convId: 'cv4', archived: false, edited: false,
    body: '# Dense retrieval in RAG\n\n- The query encoder is trained with the generator.\n- BM25 stays competitive on fact verification.\n\n*Sources: Retrieval-Augmented Generation…, p. 4*' },
  { id: 'n4', title: 'Transformer encoder block', subjects: ['llm'], date: '2026-09-12T10:41', convId: 'cv6', archived: true, edited: false,
    body: '# Transformer encoder block\n\n- Multi-head self-attention\n- Position-wise feed-forward network\n- Residual connections and layer normalisation\n\n*Sources: Attention Is All You Need, p. 3*' }
];

ST.BACKGROUND = [
  { label: 'Lesson notes', detail: '4 notes generated or updated', tokens: [18420, 3960] },
  { label: 'Learning records', detail: 'Topics and progress kept for later recommendations', tokens: [9240, 1110] }
];

/* Release 3 wireframe data */
ST.QUIZ = [
  { q: 'In ReAct, what follows an action?', opts: ['A new user prompt', 'An observation', 'The final answer', 'A retrieval index rebuild'], a: 1, pick: 1, topic: 'AI Agents' },
  { q: 'What does self-attention compare each query with?', opts: ['Only the previous token', 'All keys in the sequence', 'A fixed vocabulary', 'The output layer'], a: 1, pick: 1, topic: 'LLMs' },
  { q: 'Why does RAG train its retriever with the generator?', opts: ['To compress documents', 'To learn which passages help the answer', 'To remove BM25', 'To speed up decoding'], a: 1, pick: 2, topic: 'Retrieval-Augmented Generation' },
  { q: 'What does PPO clip?', opts: ['The reward', 'The learning rate', 'The probability ratio between new and old policy', 'The value loss only'], a: 2, pick: 0, topic: 'Reinforcement Learning' },
  { q: 'When do chain-of-thought gains appear?', opts: ['In all model sizes', 'Mainly in large models', 'Only with retrieval', 'Only in fine-tuned models'], a: 1, pick: 1, topic: 'LLMs' }
];
