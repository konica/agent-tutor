import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AskRefusedError, NoDocumentsError, type ChatEvent } from "../../api/chat";
import type { DocumentResponse, ThreadDocumentResponse } from "../../api/generated/types.gen";
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

const doc = (state: string) => ({ state }) as DocumentResponse;

// The page loads the learner's documents first; tests that don't care get one ready document.
function renderChat(props: ComponentProps<typeof ChatPage> = {}) {
  return render(
    <MemoryRouter>
      <ChatPage loadDocs={async () => [doc("ready")]} loadUsed={async () => []} {...props} />
    </MemoryRouter>,
  );
}
const question = () => screen.findByRole("textbox", { name: /question/i });
const askButton = () => screen.getByRole("button", { name: /ask/i });

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("ChatPage", () => {
  it("sends the question and renders the streamed answer with citations", async () => {
    const ask = vi.fn(() =>
      events(
        { type: "thread", thread_id: "t1" },
        { type: "delta", text: "It weighs " },
        { type: "delta", text: "tokens [1]." },
        {
          type: "citations",
          citations: [
            { n: 1, chunk_id: "c1", document_id: "d1", document_title: "a.pdf", page: 3 },
            { n: 2, chunk_id: "c2", document_id: "d2", document_title: "b.pdf", page: null },
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
    expect(screen.getByText("Sources")).toBeVisible();
    expect(screen.getByTitle("a.pdf, p. 3")).toBeInTheDocument();
    expect(screen.getByTitle("b.pdf, page unavailable")).toHaveTextContent("page unavailable");
  });

  it("numbers each citation with the marker the answer uses for it", async () => {
    const ask = vi.fn(() =>
      events(
        { type: "thread", thread_id: "t1" },
        { type: "delta", text: "Only the second chunk [2]." },
        { type: "citations", citations: [{ n: 2, chunk_id: "c2", document_id: "d2", document_title: "b.pdf", page: 4 }] },
        { type: "done" },
      ),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    const sources = await screen.findByRole("list", { name: "Sources" });
    const [item] = within(sources).getAllByRole("listitem");
    expect(item).toHaveTextContent(/^\[2\] b\.pdf · p\. 4$/);
    expect(within(sources).queryByText("[1]")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Citations" })).not.toBeInTheDocument();
  });

  it("shows one Sources line whose chip carries the full citation in its title", async () => {
    const title = "ReAct: Synergizing Reasoning and Acting";
    const ask = vi.fn(() =>
      events(
        { type: "thread", thread_id: "t1" },
        { type: "delta", text: "Yes [1]." },
        { type: "citations", citations: [{ n: 1, chunk_id: "c1", document_id: "d1", document_title: title, page: 3 }] },
        { type: "done" },
      ),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "How does ReAct work?");
    await userEvent.click(askButton());
    expect(await screen.findByText("Sources")).toBeVisible();
    expect(screen.getByTitle(`${title}, p. 3`)).toHaveTextContent(title);
    expect(screen.getByRole("heading", { level: 1, name: "How does ReAct work?" })).toHaveAttribute("title", "How does ReAct work?");
  });

  it("shows the keyboard hint under the composer", async () => {
    renderChat();
    await question();
    expect(screen.getByText("Enter to send · Shift + Enter for a new line")).toBeVisible();
  });

  it("shows another refusal's message without pointing to the Library", async () => {
    const ask = vi.fn(() => {
      throw new AskRefusedError("The tutor can't answer that right now");
    });
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByText("The tutor can't answer that right now")).toBeInTheDocument();
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

    control.push({ type: "thread", thread_id: "t1" });
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
        { type: "thread", thread_id: "t1" },
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
        { type: "thread", thread_id: "t1" },
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
      events({ type: "thread", thread_id: "t1" }, { type: "delta", text: "It weighs" }),
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

  it("shows the problem when an error arrives before any thread event", async () => {
    const ask = vi.fn(() =>
      events({ type: "error", code: "unavailable", message: "The tutor is unavailable. Try again in a moment." }),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByText("The tutor is unavailable. Try again in a moment.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "What is attention?" })).toBeInTheDocument();
  });

  it("starts with the new-conversation header and the welcome, without subjects or example questions", async () => {
    renderChat();
    expect(await screen.findByRole("heading", { name: "Ask about your documents" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "New conversation" })).toBeInTheDocument();
    expect(screen.getByText(/There's nothing to choose first: just ask\./)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Your subjects" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Subjects" })).not.toBeInTheDocument();
    expect(screen.queryByText("Subjects appear after your first question.")).not.toBeInTheDocument();
    expect(screen.queryByText(/try asking/i)).not.toBeInTheDocument();
  });

  it("asks for an upload first when the learner has no ready documents", async () => {
    renderChat({ loadDocs: async () => [doc("processing"), doc("awaiting_subjects"), doc("failed")] });
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
    renderChat({ loadDocs: async () => [doc("ready"), doc("processing"), doc("awaiting_subjects"), doc("failed")] });
    expect(await screen.findByText("1 document is still processing and can't be used yet.")).toBeInTheDocument();
  });

  it("shows no hint when nothing is processing", async () => {
    renderChat({ loadDocs: async () => [doc("ready"), doc("awaiting_subjects"), doc("failed")] });
    await question();
    expect(screen.queryByText(/still processing/)).not.toBeInTheDocument();
  });

  it("titles the conversation with the question, with no subject chips, keeping the hint", async () => {
    const ask = vi.fn(() => events({ type: "thread", thread_id: "t1" }, { type: "done" }));
    renderChat({ ask, loadDocs: async () => [doc("ready"), doc("processing")] });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByRole("heading", { level: 1, name: "What is attention?" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Subjects" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Ask about your documents" })).not.toBeInTheDocument();
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

  it("explains when the documents can't be loaded, instead of a blank page or a false upload prompt", async () => {
    renderChat({ loadDocs: () => Promise.reject(new Error("GET /documents failed (500)")) });
    expect(await screen.findByText("Your documents couldn't be loaded. Reload the page to try again.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upload a document first" })).not.toBeInTheDocument();
  });

  it("shows nothing of its own when the session has ended", async () => {
    renderChat({ loadDocs: () => Promise.reject(new SessionExpiredError()) });
    await waitFor(() => expect(screen.queryByText(/couldn't be loaded/)).not.toBeInTheDocument());
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  describe("conversation panel", () => {
    const used = (document_id: string, title: string): ThreadDocumentResponse => ({
      document_id,
      title,
      authors: [],
      year: null,
      archived: false,
      deleted: false,
    });
    const answered = () =>
      events(
        { type: "thread", thread_id: "t1" },
        { type: "delta", text: "It weighs tokens [1]." },
        { type: "citations", citations: [{ n: 1, chunk_id: "c1", document_id: "d1", document_title: "a.pdf", page: 3 }] },
        { type: "done" },
      );
    const panel = () => screen.queryByRole("complementary", { name: "Conversation" });
    const toggle = () => screen.getByRole("button", { name: /panel/ });

    it("says where the documents used will appear before the first question", async () => {
      renderChat();
      await question();
      expect(within(panel()!).getByText("Documents used to answer will appear here.")).toBeInTheDocument();
    });

    it("lists the documents the answer used, in order, once the answer is done", async () => {
      const loadUsed = vi.fn(async () => [used("d2", "Retrieval-Augmented Generation"), used("d1", "ReAct")]);
      renderChat({ ask: vi.fn(answered), loadUsed });
      await userEvent.type(await question(), "What is attention?");
      await userEvent.click(askButton());
      await waitFor(() => expect(loadUsed).toHaveBeenCalledWith("t1"));
      const rows = await within(panel()!).findAllByRole("listitem");
      expect(rows.map((r) => r.textContent)).toEqual(["Retrieval-Augmented Generation", "ReAct"]);
      expect(within(panel()!).getByRole("button", { name: "Summarize lesson" })).toBeDisabled();
    });

    it("does not look up documents used when the answer failed", async () => {
      const loadUsed = vi.fn(async () => []);
      const ask = vi.fn(() =>
        events({ type: "thread", thread_id: "t1" }, { type: "error", code: "unavailable", message: "The tutor is unavailable." }),
      );
      renderChat({ ask, loadUsed });
      await userEvent.type(await question(), "What is attention?");
      await userEvent.click(askButton());
      expect(await screen.findByText("The tutor is unavailable.")).toBeInTheDocument();
      expect(loadUsed).not.toHaveBeenCalled();
    });

    it("keeps the list as it was when the documents used can't be loaded", async () => {
      const loadUsed = vi.fn(() => Promise.reject(new Error("GET /threads/t1/documents failed (500)")));
      renderChat({ ask: vi.fn(answered), loadUsed });
      await userEvent.type(await question(), "What is attention?");
      await userEvent.click(askButton());
      await waitFor(() => expect(loadUsed).toHaveBeenCalled());
      expect(await screen.findByText("It weighs tokens [1].")).toBeInTheDocument();
      expect(within(panel()!).getByText("Documents used to answer will appear here.")).toBeInTheDocument();
    });

    it("clears the documents used when a new question starts a new conversation", async () => {
      const control = controlledStream();
      const ask = vi.fn().mockImplementationOnce(answered).mockImplementationOnce(() => control.stream());
      renderChat({ ask, loadUsed: async () => [used("d1", "ReAct")] });
      await userEvent.type(await question(), "First?");
      await userEvent.click(askButton());
      expect(await within(panel()!).findByText("ReAct")).toBeInTheDocument();
      await userEvent.type(await question(), "Second?");
      await waitFor(() => expect(askButton()).toBeEnabled());
      await userEvent.click(askButton());
      expect(within(panel()!).queryByText("ReAct")).not.toBeInTheDocument();
      control.push(null);
    });

    it("never shows the documents used of an earlier conversation that arrive after a new question", async () => {
      let release!: (documents: ThreadDocumentResponse[]) => void;
      const loadUsed = vi.fn(
        () =>
          new Promise<ThreadDocumentResponse[]>((resolve) => {
            release = resolve;
          }),
      );
      const control = controlledStream();
      const ask = vi.fn().mockImplementationOnce(answered).mockImplementationOnce(() => control.stream());
      renderChat({ ask, loadUsed });
      await userEvent.type(await question(), "First?");
      await userEvent.click(askButton());
      await waitFor(() => expect(loadUsed).toHaveBeenCalledWith("t1"));
      await userEvent.type(await question(), "Second?");
      await waitFor(() => expect(askButton()).toBeEnabled());
      await userEvent.click(askButton());
      await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));

      await act(async () => release([used("d1", "ReAct")]));
      expect(within(panel()!).queryByText("ReAct")).not.toBeInTheDocument();
      expect(within(panel()!).getByText("Documents used to answer will appear here.")).toBeInTheDocument();
      control.push(null);
    });

    it("offers a disabled Archive conversation once the conversation exists", async () => {
      const control = controlledStream();
      renderChat({ ask: vi.fn(() => control.stream()) });
      await question();
      expect(within(panel()!).queryByRole("button", { name: "Archive conversation" })).not.toBeInTheDocument();
      await userEvent.type(await question(), "What is attention?");
      await userEvent.click(askButton());
      control.push({ type: "thread", thread_id: "t1" });
      // The thread exists before its answer is done.
      expect(await within(panel()!).findByRole("button", { name: "Archive conversation" })).toBeDisabled();
      control.push({ type: "done" });
      control.push(null);
    });

    it("hides and shows the panel with the toggle, by mouse or keyboard, and remembers the choice", async () => {
      const { unmount } = renderChat();
      await question();
      expect(toggle()).toHaveAttribute("aria-expanded", "true");
      expect(toggle()).toHaveAccessibleName("Hide panel");
      expect(toggle()).toHaveAttribute("aria-controls", "conversation-panel");
      expect(panel()).toHaveAttribute("id", "conversation-panel");

      await userEvent.click(toggle());
      expect(toggle()).toHaveAttribute("aria-expanded", "false");
      expect(toggle()).toHaveAccessibleName("Show panel");
      expect(panel()).not.toBeInTheDocument();

      toggle().focus();
      await userEvent.keyboard("{Enter}");
      expect(toggle()).toHaveAttribute("aria-expanded", "true");
      expect(panel()).toBeInTheDocument();
      await userEvent.keyboard(" ");
      expect(toggle()).toHaveAttribute("aria-expanded", "false");

      unmount();
      renderChat();
      await question();
      expect(toggle()).toHaveAttribute("aria-expanded", "false");
      expect(panel()).not.toBeInTheDocument();
    });

    it("hides the citations when Show citations is off", async () => {
      renderChat({ ask: vi.fn(answered) });
      await userEvent.type(await question(), "What is attention?");
      await userEvent.click(askButton());
      expect(await screen.findByRole("list", { name: "Sources" })).toBeInTheDocument();
      await userEvent.click(screen.getByRole("switch", { name: "Show citations" }));
      expect(screen.queryByRole("list", { name: "Sources" })).not.toBeInTheDocument();
      expect(screen.getByText("It weighs tokens [1].")).toBeInTheDocument();
    });
  });
});
