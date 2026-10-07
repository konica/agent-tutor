import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AskRefusedError, NoDocumentsError, type ChatEvent } from "../../api/chat";
import type { DocumentResponse } from "../../api/generated/types.gen";
import { SessionExpiredError, sessionExpiry } from "../../auth/authClient";
import { ChatPage } from "./ChatPage";

async function* events(...list: ChatEvent[]) {
  for (const e of list) yield e;
}

// A stream the test releases step by step, to look at the page mid-answer.
function controlledStream() {
  const queue: ((value: ChatEvent | null) => void)[] = [];
  const pending: Promise<ChatEvent | null>[] = [];
  const next = () => {
    pending.push(new Promise((resolve) => queue.push(resolve)));
  };
  next();
  let read = 0;
  async function* stream() {
    for (;;) {
      const event = await pending[read++]!;
      if (event === null) return;
      yield event;
    }
  }
  return {
    stream,
    push(event: ChatEvent | null) {
      next();
      queue.shift()!(event);
    },
  };
}

const SUBJECTS = [
  { subject_id: "s1", name: "LLMs" },
  { subject_id: "s2", name: "AI Agents" },
];
const doc = (state: string) => ({ state }) as DocumentResponse;

// The page loads its subjects and documents first; tests that don't care get ready subjects and no processing documents.
function renderChat(props: ComponentProps<typeof ChatPage> = {}) {
  return render(
    <MemoryRouter>
      <ChatPage loadSubjects={async () => SUBJECTS} loadDocs={async () => []} {...props} />
    </MemoryRouter>,
  );
}
const question = () => screen.findByRole("textbox", { name: /question/i });
const askButton = () => screen.getByRole("button", { name: /ask/i });

afterEach(() => vi.restoreAllMocks());

describe("ChatPage", () => {
  it("sends the question and renders the streamed answer with citations", async () => {
    const ask = vi.fn(() =>
      events(
        { type: "thread", thread_id: "t1", subjects: [{ subject_id: "s1", name: "General" }] },
        { type: "delta", text: "It weighs " },
        { type: "delta", text: "tokens [1]." },
        {
          type: "citations",
          citations: [
            { n: 1, chunk_id: "c1", document_title: "a.pdf", page: 3 },
            { n: 2, chunk_id: "c2", document_title: "b.pdf", page: null },
          ],
        },
        { type: "done" },
      ),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(ask).toHaveBeenCalledWith("What is attention?");
    expect(await screen.findByText("It weighs tokens [1].")).toBeInTheDocument();
    // The question is the header title and also the learner's bubble in the conversation.
    expect(screen.getByRole("heading", { level: 1, name: "What is attention?" })).toBeInTheDocument();
    expect(screen.getByText("You asked:").parentElement).toHaveTextContent("You asked: What is attention?");
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("a.pdf, p. 3")).toBeInTheDocument();
    expect(screen.getByText("b.pdf, page unavailable")).toBeInTheDocument();
  });

  it("numbers each citation with the marker the answer uses for it", async () => {
    const ask = vi.fn(() =>
      events(
        { type: "thread", thread_id: "t1", subjects: [] },
        { type: "delta", text: "Only the second chunk [2]." },
        { type: "citations", citations: [{ n: 2, chunk_id: "c2", document_title: "b.pdf", page: 4 }] },
        { type: "done" },
      ),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    const citations = await screen.findByRole("region", { name: "Citations" });
    const [item] = within(citations).getAllByRole("listitem");
    expect(item).toHaveTextContent(/^\[2\] b\.pdf, p\. 4$/);
    expect(within(citations).queryByText("[1]")).not.toBeInTheDocument();
  });

  it("shows another refusal's message without pointing to the Library", async () => {
    const ask = vi.fn(() => {
      throw new AskRefusedError("Subject detection isn't available yet");
    });
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByText("Subject detection isn't available yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /library/i })).not.toBeInTheDocument();
  });

  it("does not ask an empty or blank question", async () => {
    const ask = vi.fn(() => events({ type: "done" }));
    renderChat({ ask });
    await question();
    expect(askButton()).toBeDisabled();
    await userEvent.type(await question(), "   ");
    expect(askButton()).toBeDisabled();
    await userEvent.type(await question(), "{Enter}");
    expect(ask).not.toHaveBeenCalled();
  });

  it("disables the question and the button while answering, marks the answer busy, then allows another question", async () => {
    const control = controlledStream();
    const ask = vi.fn(() => control.stream());
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());

    control.push({ type: "thread", thread_id: "t1", subjects: [] });
    control.push({ type: "delta", text: "It weighs" });
    const answer = await screen.findByText("It weighs");
    const region = answer.closest("[aria-live]")!;
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveAttribute("aria-busy", "true");
    expect(await question()).toBeDisabled();
    expect(askButton()).toBeDisabled();

    control.push({ type: "done" });
    control.push(null);
    await waitFor(() => expect(region).toHaveAttribute("aria-busy", "false"));
    expect(await question()).toBeEnabled();
    await userEvent.type(await question(), "Another?");
    expect(askButton()).toBeEnabled();
  });

  it("shows the message of an unavailable error", async () => {
    const ask = vi.fn(() =>
      events(
        { type: "thread", thread_id: "t1", subjects: [] },
        { type: "error", code: "unavailable", message: "The tutor is unavailable. Try again in a moment." },
      ),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByText("The tutor is unavailable. Try again in a moment.")).toBeInTheDocument();
  });

  it("reports an ended session when the stream says unauthenticated", async () => {
    const notify = vi.spyOn(sessionExpiry, "notify").mockImplementation(() => {});
    const ask = vi.fn(() =>
      events(
        { type: "thread", thread_id: "t1", subjects: [] },
        { type: "error", code: "unauthenticated", message: "Please sign in again." },
      ),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    await waitFor(() => expect(notify).toHaveBeenCalledOnce());
  });

  it("shows a generic message when the stream ends without done or error, keeping the partial answer", async () => {
    const ask = vi.fn(() =>
      events({ type: "thread", thread_id: "t1", subjects: [] }, { type: "delta", text: "It weighs" }),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByText("The tutor couldn't answer right now. Try again in a moment.")).toBeInTheDocument();
    expect(screen.getByText("It weighs")).toBeInTheDocument();
  });

  it("shows a generic message when asking fails", async () => {
    const ask = vi.fn(async function* (): AsyncGenerator<ChatEvent> {
      throw new Error("POST /threads failed (500)");
    });
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByText("The tutor couldn't answer right now. Try again in a moment.")).toBeInTheDocument();
  });

  it("shows the thread's subjects as chips under the question in the header", async () => {
    const ask = vi.fn(() =>
      events(
        {
          type: "thread",
          thread_id: "t1",
          subjects: [
            { subject_id: "s1", name: "LLMs" },
            { subject_id: "s2", name: "AI Agents" },
          ],
        },
        { type: "delta", text: "Answer." },
        { type: "citations", citations: [] },
        { type: "done" },
      ),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "How does chain-of-thought help?");
    await userEvent.click(askButton());
    const heading = await screen.findByRole("heading", { level: 1, name: "How does chain-of-thought help?" });
    const list = within(heading.closest("header")!).getByRole("list", { name: "Subjects" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["LLMs", "AI Agents"]);
    expect(await screen.findByText("Answer.")).toBeInTheDocument();
  });

  it("shows the problem with no subjects when an error arrives before any thread event", async () => {
    const ask = vi.fn(() =>
      events({ type: "error", code: "unavailable", message: "The tutor is unavailable. Try again in a moment." }),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByText("The tutor is unavailable. Try again in a moment.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "What is attention?" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Subjects" })).toBeNull();
  });

  it("starts with the new-conversation header, the welcome and the learner's subjects, without example questions", async () => {
    renderChat();
    const list = await screen.findByRole("list", { name: "Your subjects" });
    expect(screen.getByRole("heading", { level: 1, name: "New conversation" })).toBeInTheDocument();
    expect(screen.getByText("Subjects appear after your first question.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ask about your documents" })).toBeInTheDocument();
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["LLMs", "AI Agents"]);
    expect(screen.queryByText(/try asking/i)).not.toBeInTheDocument();
  });

  it("asks for an upload first when the learner has no subjects", async () => {
    renderChat({ loadSubjects: async () => [] });
    expect(await screen.findByRole("heading", { name: "Upload a document first" })).toBeInTheDocument();
    expect(screen.getByText(/The tutor answers only from your documents\. Add a PDF to your Library/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload" })).toHaveAttribute("href", "/library");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "New conversation" })).not.toBeInTheDocument();
  });

  it("says how many documents are still processing", async () => {
    renderChat({ loadDocs: async () => [doc("processing"), doc("processing"), doc("ready")] });
    expect(await screen.findByText("2 documents are still processing and can't be used yet.")).toBeInTheDocument();
  });

  it("uses the singular for one processing document", async () => {
    renderChat({ loadDocs: async () => [doc("processing"), doc("ready")] });
    expect(await screen.findByText("1 document is still processing and can't be used yet.")).toBeInTheDocument();
  });

  it("shows no hint when nothing is processing", async () => {
    renderChat({ loadDocs: async () => [doc("ready"), doc("awaiting_subjects"), doc("failed")] });
    await question();
    expect(screen.queryByText(/still processing/)).not.toBeInTheDocument();
  });

  it("titles the conversation with the question and shows the thread's subjects, keeping the hint", async () => {
    const ask = vi.fn(() =>
      events({ type: "thread", thread_id: "t1", subjects: [{ subject_id: "s2", name: "AI Agents" }] }, { type: "done" }),
    );
    renderChat({ ask, loadDocs: async () => [doc("processing")] });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByRole("heading", { level: 1, name: "What is attention?" })).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Subjects" });
    expect(within(list).getByText("AI Agents")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Ask about your documents" })).not.toBeInTheDocument();
    expect(screen.queryByText("Subjects appear after your first question.")).not.toBeInTheDocument();
    expect(screen.getByText("1 document is still processing and can't be used yet.")).toBeInTheDocument();
  });

  it("switches to the upload prompt when the ask finds no documents", async () => {
    const ask = vi.fn(() => {
      throw new NoDocumentsError("Upload a document first");
    });
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByRole("heading", { name: "Upload a document first" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload" })).toHaveAttribute("href", "/library");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("explains when the subjects can't be loaded, instead of a blank page or a false upload prompt", async () => {
    renderChat({ loadSubjects: () => Promise.reject(new Error("GET /me/subjects failed (500)")) });
    expect(await screen.findByText("Your subjects couldn't be loaded. Reload the page to try again.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upload a document first" })).not.toBeInTheDocument();
  });

  it("still lets the learner ask when only the document count can't be loaded", async () => {
    renderChat({ loadDocs: () => Promise.reject(new Error("boom")) });
    expect(await question()).toBeEnabled();
    expect(screen.queryByText(/still processing/)).not.toBeInTheDocument();
  });

  it("shows nothing of its own when the session has ended", async () => {
    renderChat({ loadSubjects: () => Promise.reject(new SessionExpiredError()) });
    await waitFor(() => expect(screen.queryByText(/couldn't be loaded/)).not.toBeInTheDocument());
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
