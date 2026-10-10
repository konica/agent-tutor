import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AskRefusedError, ConversationNotFoundError, NoDocumentsError, type ChatEvent } from "../../api/chat";
import type { DocumentResponse, ThreadDocumentResponse, ThreadResponse, TurnResponse } from "../../api/generated/types.gen";
import { SessionExpiredError, sessionExpiry } from "../../auth/authClient";
import { fakeViewerDeps } from "../viewer/testFakes";
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

function Location() {
  const location = useLocation();
  // Not an <output>: its implicit status role would clash with the page's status region.
  return <p data-testid="location">{location.pathname + location.search}</p>;
}

// The page loads the learner's documents first; tests that don't care get one ready document. The page sits on its
// route, so it sees the conversation's id; the location and a Chat link sit beside it.
function renderChat(props: ComponentProps<typeof ChatPage> = {}, entry = "/chat") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/chat/:threadId?" element={<ChatPage loadDocs={async () => [doc("ready")]} loadUsed={async () => []} {...props} />} />
      </Routes>
      <Location />
      <Link to="/chat">Chat</Link>
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
    expect(ask).toHaveBeenCalledWith("What is attention?", undefined);
    expect(await screen.findByText("It weighs tokens [1].")).toBeInTheDocument();
    // The question is the header title and also the learner's bubble in the conversation.
    expect(screen.getByRole("heading", { level: 1 })).toContainElement(screen.getByRole("button", { name: "What is attention?. Edit title" }));
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
    expect(screen.getByRole("button", { name: "How does ReAct work?. Edit title" })).toHaveAttribute("title", "How does ReAct work?");
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
    expect(await screen.findByRole("button", { name: "What is attention?. Edit title" })).toBeInTheDocument();
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
      added_by: "answer",
      used: true,
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

    it("shows a deleted document's citation as Deleted document, without its title or page", async () => {
      const ask = vi.fn(() =>
        events(
          { type: "thread", thread_id: "t1" },
          { type: "delta", text: "A [1] and B [2]." },
          {
            type: "citations",
            citations: [
              { n: 1, chunk_id: "c1", document_id: "d1", document_title: "a.pdf", page: 3 },
              { n: 2, chunk_id: "c2", document_id: "d2", document_title: "b.pdf", page: 7 },
            ],
          },
          { type: "done" },
        ),
      );
      const loadUsed = vi.fn(async () => [used("d1", "a.pdf"), { ...used("d2", "b.pdf"), deleted: true }]);
      renderChat({ ask, loadUsed });
      await userEvent.type(await question(), "What?");
      await userEvent.click(askButton());
      const sources = await screen.findByRole("list", { name: "Sources" });
      await waitFor(() => expect(within(sources).getByText("Deleted document")).toBeInTheDocument());
      const [first, second] = within(sources).getAllByRole("listitem");
      expect(first).toHaveTextContent("[1] a.pdf · p. 3");
      expect(second).toHaveTextContent("[2] Deleted document");
      expect(second).not.toHaveTextContent("b.pdf");
      expect(second).not.toHaveTextContent("p. 7");
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

    it("says the documents used couldn't be loaded, until the next question", async () => {
      const loadUsed = vi.fn(() => Promise.reject(new Error("GET /threads/t1/documents failed (500)")));
      const control = controlledStream();
      const ask = vi.fn().mockImplementationOnce(answered).mockImplementationOnce(() => control.stream());
      renderChat({ ask, loadUsed });
      await userEvent.type(await question(), "What is attention?");
      await userEvent.click(askButton());
      expect(await screen.findByText("It weighs tokens [1].")).toBeInTheDocument();
      expect(await within(panel()!).findByText("Couldn't load the documents used.")).toBeInTheDocument();
      expect(within(panel()!).queryByText("Documents used to answer will appear here.")).not.toBeInTheDocument();

      await userEvent.type(await question(), "Second?");
      await waitFor(() => expect(askButton()).toBeEnabled());
      await userEvent.click(askButton());
      expect(within(panel()!).queryByText("Couldn't load the documents used.")).not.toBeInTheDocument();
      expect(within(panel()!).getByText("Documents used to answer will appear here.")).toBeInTheDocument();
      control.push(null);
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

    describe("adding and removing documents", () => {
      const readyDoc = (document_id: string, title: string) =>
        ({ document_id, title, state: "ready", authors: [], year: null }) as unknown as DocumentResponse;
      const status = () => screen.getByRole("status");

      async function answer(props: ComponentProps<typeof ChatPage>) {
        renderChat({ ask: vi.fn(answered), loadUsed: vi.fn(async () => [used("d1", "a.pdf")]), ...props });
        await userEvent.type(await question(), "What is attention?");
        await userEvent.click(askButton());
        expect(await within(panel()!).findByText("a.pdf")).toBeInTheDocument();
      }

      it("waits for the conversation before offering Add documents", async () => {
        renderChat();
        await question();
        expect(within(panel()!).queryByRole("button", { name: "Add documents" })).not.toBeInTheDocument();
      });

      it("adds the checked documents, marks them Added, closes the picker, and returns focus", async () => {
        const loadReady = vi.fn(async () => [readyDoc("d1", "a.pdf"), readyDoc("d2", "ReAct")]);
        const addDocs = vi.fn(async () => [used("d1", "a.pdf"), { ...used("d2", "ReAct"), added_by: "learner" as const, used: false }]);
        await answer({ loadReady, addDocs });
        const add = within(panel()!).getByRole("button", { name: "Add documents" });
        await userEvent.click(add);
        const dialog = await screen.findByRole("dialog", { name: "Add documents" });
        await userEvent.click(await within(dialog).findByRole("checkbox", { name: /^ReAct/ }));
        await userEvent.click(within(dialog).getByRole("button", { name: "Add 1 document" }));
        expect(addDocs).toHaveBeenCalledWith("t1", ["d2"]);
        await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
        expect(within(panel()!).getAllByRole("listitem").map((r) => r.textContent)).toEqual(["a.pdf", "ReActAdded"]);
        expect(within(panel()!).getByRole("button", { name: "Add documents" })).toHaveFocus();
        expect(status()).toHaveTextContent("1 document added to this conversation.");
      });

      it("keeps the picker open with an error when adding fails", async () => {
        const addDocs = vi.fn(() => Promise.reject(new Error("POST /threads/t1/documents failed (500)")));
        await answer({ loadReady: vi.fn(async () => [readyDoc("d2", "ReAct")]), addDocs });
        await userEvent.click(within(panel()!).getByRole("button", { name: "Add documents" }));
        const dialog = await screen.findByRole("dialog", { name: "Add documents" });
        await userEvent.click(await within(dialog).findByRole("checkbox", { name: /^ReAct/ }));
        await userEvent.click(within(dialog).getByRole("button", { name: "Add 1 document" }));
        expect(await within(dialog).findByRole("alert")).toHaveTextContent("Couldn't add the documents. Try again.");
        expect(within(dialog).getByRole("checkbox", { name: /^ReAct/ })).toBeChecked();
        expect(within(panel()!).getAllByRole("listitem").map((r) => r.textContent)).toEqual(["a.pdf"]);
      });

      it("removes a row and keeps the answer's citations", async () => {
        const removeDoc = vi.fn(async () => {});
        await answer({ removeDoc });
        await userEvent.click(within(panel()!).getByRole("button", { name: "Remove a.pdf from this conversation" }));
        expect(removeDoc).toHaveBeenCalledWith("t1", "d1");
        expect(within(panel()!).queryByText("a.pdf")).not.toBeInTheDocument();
        expect(within(panel()!).getByText("Documents used to answer will appear here.")).toBeInTheDocument();
        expect(screen.getByTitle("a.pdf, p. 3")).toBeInTheDocument();
        expect(status()).toHaveTextContent("a.pdf removed from this conversation.");
      });

      it("reloads the list when removing fails, so the row comes back", async () => {
        const loadUsed = vi.fn(async () => [used("d1", "a.pdf")]);
        const removeDoc = vi.fn(() => Promise.reject(new Error("DELETE failed (500)")));
        await answer({ loadUsed, removeDoc });
        await userEvent.click(within(panel()!).getByRole("button", { name: "Remove a.pdf from this conversation" }));
        await waitFor(() => expect(loadUsed).toHaveBeenCalledTimes(2));
        expect(await within(panel()!).findByText("a.pdf")).toBeInTheDocument();
      });
    });

    describe("limiting the search", () => {
      const scopeSwitch = () => within(panel()!).getByRole("switch", { name: "Only search these documents" });
      const status = () => screen.getByRole("status");
      const declined = () =>
        events({ type: "thread", thread_id: "t1" }, { type: "decline", code: "limited", message: "These documents don't cover this." }, { type: "done" });

      // Answers a first question (a new thread t1 that used a.pdf), then turns the limit on.
      async function limit(props: ComponentProps<typeof ChatPage> = {}) {
        const setScope = vi.fn(async (_threadId: string, scope: "library" | "listed") => scope);
        const askIn = vi.fn(answered);
        const ask = vi.fn(answered);
        renderChat({ ask, askIn, setScope, loadUsed: vi.fn(async () => [used("d1", "a.pdf")]), ...props });
        await userEvent.type(await question(), "What is attention?");
        await userEvent.click(askButton());
        expect(await within(panel()!).findByText("a.pdf")).toBeInTheDocument();
        await userEvent.click(scopeSwitch());
        return { ask, askIn, setScope };
      }

      it("disables the switch before the first answer", async () => {
        renderChat();
        await question();
        expect(scopeSwitch()).toBeDisabled();
        expect(scopeSwitch()).toHaveAttribute("aria-checked", "false");
      });

      it("limits the conversation, shows Searching 1 document, and asks within the conversation", async () => {
        const { ask, askIn, setScope } = await limit();
        expect(setScope).toHaveBeenCalledWith("t1", "listed");
        expect(scopeSwitch()).toHaveAttribute("aria-checked", "true");
        expect(status()).toHaveTextContent("Only searching 1 document.");
        const form = screen.getByRole("textbox", { name: /question/i }).closest("form")!;
        expect(within(form).getByText("Searching 1 document")).toBeInTheDocument();
        expect(within(form).getByRole("button", { name: "Change" })).toBeInTheDocument();

        await userEvent.type(await question(), "And RAG?");
        await userEvent.click(askButton());
        await waitFor(() => expect(askIn).toHaveBeenCalledWith("t1", "And RAG?"));
        expect(ask).toHaveBeenCalledTimes(1);
        // The answer is a second turn under the first.
        await waitFor(() => expect(screen.getAllByText("It weighs tokens [1].")).toHaveLength(2));
        // The same conversation: its title and its documents stay.
        expect(screen.getByRole("button", { name: "What is attention?. Edit title" })).toBeInTheDocument();
        expect(within(panel()!).getByText("a.pdf")).toBeInTheDocument();
        expect(scopeSwitch()).toHaveAttribute("aria-checked", "true");
      });

      it("turns the limit off again and says so", async () => {
        const { setScope } = await limit();
        await userEvent.click(scopeSwitch());
        expect(setScope).toHaveBeenLastCalledWith("t1", "library");
        expect(scopeSwitch()).toHaveAttribute("aria-checked", "false");
        expect(status()).toHaveTextContent("Searching all your documents.");
        expect(screen.queryByText("Searching 1 document")).not.toBeInTheDocument();
      });

      it("keeps the switch as it was and says why when saving the scope fails", async () => {
        const setScope = vi.fn(() => Promise.reject(new Error("Add documents to limit the search.")));
        await limit({ setScope });
        expect(scopeSwitch()).toHaveAttribute("aria-checked", "false");
        await waitFor(() => expect(status()).toHaveTextContent("Add documents to limit the search."));
        expect(screen.queryByText("Searching 1 document")).not.toBeInTheDocument();
      });

      it("Change opens a closed panel and focuses the switch", async () => {
        await limit();
        await userEvent.click(toggle());
        expect(panel()).not.toBeInTheDocument();
        await userEvent.click(screen.getByRole("button", { name: "Change" }));
        expect(panel()).toBeInTheDocument();
        expect(scopeSwitch()).toHaveFocus();
      });

      it("Change focuses the switch when the panel is already open", async () => {
        await limit();
        await userEvent.click(screen.getByRole("button", { name: "Change" }));
        expect(scopeSwitch()).toHaveFocus();
      });

      // Beside a document (US-4b) the panel is hidden; Change shows it for this split only, like the header toggle.
      it("Change beside a document shows the panel without saving the choice, and focuses the switch", async () => {
        await limit({ viewerDeps: fakeViewerDeps() });
        await userEvent.click(within(panel()!).getByRole("button", { name: "a.pdf" }));
        expect(await screen.findByRole("region", { name: "ReAct" }, { timeout: 3000 })).toBeInTheDocument();
        expect(panel()).not.toBeInTheDocument();
        const setItem = vi.spyOn(Storage.prototype, "setItem");
        await userEvent.click(screen.getByRole("button", { name: "Change" }));
        expect(panel()).toBeInTheDocument();
        expect(scopeSwitch()).toHaveFocus();
        expect(screen.getByRole("region", { name: "ReAct" })).toBeInTheDocument();
        expect(setItem).not.toHaveBeenCalledWith("smart-tutor.chat-panel-open", expect.anything());
        setItem.mockRestore();
      });

      it("keeps the document open beside a question asked within the limited conversation", async () => {
        const { askIn } = await limit({ viewerDeps: fakeViewerDeps() });
        await userEvent.click(within(panel()!).getByRole("button", { name: "a.pdf" }));
        expect(await screen.findByRole("region", { name: "ReAct" }, { timeout: 3000 })).toBeInTheDocument();
        await userEvent.type(await question(), "And RAG?");
        await userEvent.click(askButton());
        await waitFor(() => expect(askIn).toHaveBeenCalledWith("t1", "And RAG?"));
        expect(screen.getByRole("region", { name: "ReAct" })).toBeInTheDocument();
      });

      it("shows the limited decline with its way out, and no Sources", async () => {
        await limit({ askIn: vi.fn(declined) });
        await userEvent.type(await question(), "How does PPO clip?");
        await userEvent.click(askButton());
        expect(await screen.findByText("These documents don't cover this.")).toBeInTheDocument();
        expect(screen.getByText("This conversation only searches 1 document.")).toBeInTheDocument();
        const card = screen.getByText("These documents don't cover this.").parentElement!;
        expect(within(card).getByRole("button", { name: "Add documents" })).toBeEnabled();
        expect(within(card).getByRole("button", { name: "Search all my documents" })).toBeEnabled();
        // The first turn keeps its Sources; the decline's turn has none.
        expect(within(card.parentElement!).queryByText("Sources")).not.toBeInTheDocument();
      });

      it("Add documents in the decline opens the picker", async () => {
        await limit({ askIn: vi.fn(declined), loadReady: vi.fn(async () => []) });
        await userEvent.type(await question(), "How does PPO clip?");
        await userEvent.click(askButton());
        const card = (await screen.findByText("These documents don't cover this.")).parentElement!;
        await userEvent.click(within(card).getByRole("button", { name: "Add documents" }));
        expect(await screen.findByRole("dialog", { name: "Add documents" })).toBeInTheDocument();
      });

      it("Search all my documents turns the limit off and asks the same question again in the conversation", async () => {
        const askIn = vi.fn().mockImplementationOnce(declined).mockImplementationOnce(answered);
        const { ask, setScope } = await limit({ askIn });
        await userEvent.type(await question(), "How does PPO clip?");
        await userEvent.click(askButton());
        await userEvent.click(await screen.findByRole("button", { name: "Search all my documents" }));
        expect(setScope).toHaveBeenLastCalledWith("t1", "library");
        await waitFor(() => expect(askIn).toHaveBeenLastCalledWith("t1", "How does PPO clip?"));
        expect(askIn).toHaveBeenCalledTimes(2);
        expect(ask).toHaveBeenCalledTimes(1);
        // The answer is a new turn under the decline, which keeps its message but no longer offers its way out.
        await waitFor(() => expect(screen.getAllByText("It weighs tokens [1].")).toHaveLength(2));
        expect(screen.getByText("These documents don't cover this.")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Search all my documents" })).not.toBeInTheDocument();
        expect(scopeSwitch()).toHaveAttribute("aria-checked", "false");
        expect(screen.queryByText("Searching 1 document")).not.toBeInTheDocument();
      });

      it("shows why and asks nothing when Search all my documents can't turn the limit off", async () => {
        const askIn = vi.fn(declined);
        const setScope = vi
          .fn()
          .mockImplementationOnce(async () => "listed")
          .mockImplementationOnce(() => Promise.reject(new Error("The search scope couldn't be changed.")));
        await limit({ askIn, setScope });
        await userEvent.type(await question(), "How does PPO clip?");
        await userEvent.click(askButton());
        await userEvent.click(await screen.findByRole("button", { name: "Search all my documents" }));
        expect(await screen.findByText("The search scope couldn't be changed.")).toBeInTheDocument();
        expect(askIn).toHaveBeenCalledTimes(1);
        expect(scopeSwitch()).toHaveAttribute("aria-checked", "true");
      });

      it("turns the limit off when the last listed document is removed", async () => {
        await limit({ removeDoc: vi.fn(async () => {}) });
        await userEvent.click(within(panel()!).getByRole("button", { name: "Remove a.pdf from this conversation" }));
        expect(scopeSwitch()).toHaveAttribute("aria-checked", "false");
        expect(scopeSwitch()).toBeDisabled();
        expect(screen.queryByText("Searching 1 document")).not.toBeInTheDocument();
      });

      it("keeps the limit when removing the last listed document fails", async () => {
        await limit({ removeDoc: vi.fn(() => Promise.reject(new Error("DELETE failed (500)"))) });
        await userEvent.click(within(panel()!).getByRole("button", { name: "Remove a.pdf from this conversation" }));
        expect(await within(panel()!).findByText("a.pdf")).toBeInTheDocument();
        expect(scopeSwitch()).toHaveAttribute("aria-checked", "true");
        expect(screen.getByText("Searching 1 document")).toBeInTheDocument();
      });

      it("starts a new conversation for a question while the limit is off", async () => {
        const askIn = vi.fn(answered);
        const ask = vi.fn(answered);
        renderChat({ ask, askIn, loadUsed: vi.fn(async () => [used("d1", "a.pdf")]) });
        await userEvent.type(await question(), "First?");
        await userEvent.click(askButton());
        expect(await within(panel()!).findByText("a.pdf")).toBeInTheDocument();
        await userEvent.type(await question(), "Second?");
        await userEvent.click(askButton());
        await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
        expect(ask).toHaveBeenLastCalledWith("Second?", undefined);
        expect(askIn).not.toHaveBeenCalled();
      });
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

  describe("document viewer", () => {
    const used = (document_id: string, title: string): ThreadDocumentResponse => ({
      document_id,
      title,
      authors: [],
      year: null,
      archived: false,
      deleted: false,
      added_by: "answer",
      used: true,
    });
    const answered = () =>
      events({ type: "thread", thread_id: "t1" }, { type: "delta", text: "It weighs tokens [1]." }, { type: "done" });
    const panel = () => screen.queryByRole("complementary", { name: "Conversation" });
    const pane = (name: string) => screen.queryByRole("region", { name });
    const row = (name: string) => within(panel()!).findByRole("button", { name });

    // Asks one question and waits for the documents used to fill the panel.
    async function answer(props: ComponentProps<typeof ChatPage> = {}) {
      const ask = vi.fn().mockImplementation(answered);
      renderChat({ ask, viewerDeps: fakeViewerDeps(), loadUsed: async () => [used("d1", "ReAct"), used("d2", "PPO")], ...props });
      await userEvent.type(await question(), "How does ReAct work?");
      await userEvent.click(askButton());
      await row("ReAct");
    }

    async function openReAct() {
      await userEvent.click(await row("ReAct"));
      // The viewer loads its file link and PDF first; give it room when the suite runs under load.
      expect(await screen.findByText("p. 1 / 3", {}, { timeout: 3000 })).toBeInTheDocument();
    }

    it("opens a used document beside the conversation with its title focused, hiding the panel", async () => {
      await answer();
      await openReAct();
      expect(pane("ReAct")).toBeInTheDocument();
      expect(within(pane("ReAct")!).getByRole("heading", { level: 2, name: "ReAct" })).toHaveFocus();
      expect(panel()).not.toBeInTheDocument();
      expect(screen.getByText("It weighs tokens [1].")).toBeInTheDocument();
    });

    it("swaps the document in place when another row is opened", async () => {
      await answer();
      await openReAct();
      await userEvent.click(screen.getByRole("button", { name: "Show panel" }));
      await userEvent.click(await row("PPO"));
      expect(await screen.findByRole("region", { name: "PPO" })).toBeInTheDocument();
      expect(pane("ReAct")).not.toBeInTheDocument();
      expect(within(panel()!).getByRole("button", { name: "PPO" })).toHaveAttribute("aria-current", "true");
    });

    it("Close removes the pane, brings the panel back, and returns focus to the row", async () => {
      await answer();
      await openReAct();
      await userEvent.click(within(pane("ReAct")!).getByRole("button", { name: "Close" }));
      expect(pane("ReAct")).not.toBeInTheDocument();
      expect(panel()).toBeInTheDocument();
      await waitFor(() => expect(within(panel()!).getByRole("button", { name: "ReAct" })).toHaveFocus());
    });

    it("Escape in the pane does the same", async () => {
      await answer();
      await openReAct();
      fireEvent.keyDown(within(pane("ReAct")!).getByRole("heading", { level: 2, name: "ReAct" }), { key: "Escape" });
      expect(pane("ReAct")).not.toBeInTheDocument();
      expect(panel()).toBeInTheDocument();
      await waitFor(() => expect(within(panel()!).getByRole("button", { name: "ReAct" })).toHaveFocus());
    });

    it("shows the panel during the split without changing the saved choice", async () => {
      await answer();
      await openReAct();
      const setItem = vi.spyOn(Storage.prototype, "setItem");
      await userEvent.click(screen.getByRole("button", { name: "Show panel" }));
      expect(panel()).toBeInTheDocument();
      expect(pane("ReAct")).toBeInTheDocument();
      expect(setItem).not.toHaveBeenCalledWith("smart-tutor.chat-panel-open", expect.anything());
      setItem.mockRestore();
    });

    it("closes the document when a new question is asked", async () => {
      await answer();
      await openReAct();
      await userEvent.type(await question(), "Second?");
      await waitFor(() => expect(askButton()).toBeEnabled());
      await userEvent.click(askButton());
      await waitFor(() => expect(pane("ReAct")).not.toBeInTheDocument());
      // The learner is asking: focus is not pulled back into the panel.
      expect(panel()).toBeInTheDocument();
      expect(panel()).not.toContainElement(document.activeElement as HTMLElement);
    });

    it("closes the pane when the open document is removed, focus moving to the next row's remove button", async () => {
      const removeDoc = vi.fn(async () => {});
      await answer({ removeDoc });
      await openReAct();
      await userEvent.click(screen.getByRole("button", { name: "Show panel" }));
      await userEvent.click(within(panel()!).getByRole("button", { name: "Remove ReAct from this conversation" }));
      expect(removeDoc).toHaveBeenCalledWith("t1", "d1");
      await waitFor(() => expect(pane("ReAct")).not.toBeInTheDocument());
      expect(panel()).toBeInTheDocument();
      expect(within(panel()!).queryByRole("button", { name: "ReAct" })).not.toBeInTheDocument();
      await waitFor(() =>
        expect(within(panel()!).getByRole("button", { name: "Remove PPO from this conversation" })).toHaveFocus(),
      );
    });

    it("keeps the pane open when another document is removed", async () => {
      await answer({ removeDoc: vi.fn(async () => {}) });
      await openReAct();
      await userEvent.click(screen.getByRole("button", { name: "Show panel" }));
      await userEvent.click(within(panel()!).getByRole("button", { name: "Remove PPO from this conversation" }));
      expect(pane("ReAct")).toBeInTheDocument();
      expect(within(panel()!).getByRole("button", { name: "ReAct" })).toHaveAttribute("aria-current", "true");
    });

    describe("Sources chips", () => {
      const cited = (c3Page: number | null = 1) =>
        events(
          { type: "thread", thread_id: "t1" },
          { type: "delta", text: "It weighs tokens [1][2][3]." },
          {
            type: "citations",
            citations: [
              { n: 1, chunk_id: "c1", document_id: "d1", document_title: "ReAct", page: 2 },
              { n: 2, chunk_id: "c2", document_id: "d1", document_title: "ReAct", page: 3 },
              { n: 3, chunk_id: "c3", document_id: "d2", document_title: "PPO", page: c3Page },
            ],
          },
          { type: "done" },
        );
      const chip = (name: RegExp) => screen.findByRole("button", { name });
      const reactP2 = () => chip(/^ReAct, p\. 2\. (Open|Shown)/);
      const reactP3 = () => chip(/^ReAct, p\. 3\. (Open|Shown)/);

      async function cite(props: ComponentProps<typeof ChatPage> = {}) {
        const viewerDeps = fakeViewerDeps();
        await answer({ ask: vi.fn().mockImplementation(() => cited()), viewerDeps, ...props });
        return viewerDeps;
      }

      it("opens the document beside the conversation at its page", async () => {
        const deps = await cite();
        const first = await chip(/ReAct, p\. 2\. Open beside the conversation/);
        await userEvent.click(first);
        expect(await screen.findByText("p. 2 / 3", {}, { timeout: 3000 })).toBeInTheDocument();
        expect(pane("ReAct")).toBeInTheDocument();
        expect(deps.loadChunk).toHaveBeenCalledWith("c1");
        expect(first).toHaveAccessibleName(/Shown beside the conversation$/);
        expect(first).toHaveAttribute("aria-current", "true");
      });

      it("swaps the document in place when a chip of another document is clicked", async () => {
        await cite();
        const react = await reactP2();
        await userEvent.click(react);
        await screen.findByText("p. 2 / 3", {}, { timeout: 3000 });
        const ppo = await chip(/^PPO, p\. 1\./);
        await userEvent.click(ppo);
        expect(await screen.findByRole("region", { name: "PPO" })).toBeInTheDocument();
        expect(pane("ReAct")).not.toBeInTheDocument();
        expect(react).not.toHaveAttribute("aria-current");
        expect(ppo).toHaveAttribute("aria-current", "true");
      });

      it("keeps the PDF loaded when a second chip of the same document is clicked", async () => {
        const deps = await cite();
        await userEvent.click(await reactP2());
        await screen.findByText("p. 2 / 3", {}, { timeout: 3000 });
        deps.loadChunk.mockImplementation(async (id: string) => ({ chunkId: id, documentId: "d1", page: 3, startIndex: 0, text: "More." }));
        await userEvent.click(await reactP3());
        expect(await screen.findByText("p. 3 / 3", {}, { timeout: 3000 })).toBeInTheDocument();
        expect(deps.loadPdfDoc).toHaveBeenCalledTimes(1);
      });

      it("returns focus to the chip when the pane closes", async () => {
        await cite();
        const react = await reactP2();
        await userEvent.click(react);
        await screen.findByText("p. 2 / 3", {}, { timeout: 3000 });
        fireEvent.keyDown(within(pane("ReAct")!).getByRole("heading", { level: 2, name: "ReAct" }), { key: "Escape" });
        expect(pane("ReAct")).not.toBeInTheDocument();
        await waitFor(() => expect(react).toHaveFocus());

        await userEvent.click(react);
        await screen.findByText("p. 2 / 3", {}, { timeout: 3000 });
        await userEvent.click(within(pane("ReAct")!).getByRole("button", { name: "Close" }));
        await waitFor(() => expect(react).toHaveFocus());
      });

      it("shows a deleted document's chip as text, not a button", async () => {
        await cite({ loadUsed: async () => [used("d1", "ReAct"), { ...used("d2", "PPO"), deleted: true }] });
        await chip(/^ReAct, p\. 2\./);
        const sources = within(screen.getByRole("list", { name: "Sources" }));
        expect(sources.queryByRole("button", { name: /PPO/ })).not.toBeInTheDocument();
        expect(sources.getByText(/Deleted document/)).toBeInTheDocument();
      });

      it("opens the document at page 1 for a citation without a page", async () => {
        const deps = await cite({ ask: vi.fn().mockImplementation(() => cited(null)) });
        await userEvent.click(await chip(/^PPO, page unavailable\. Open/));
        expect(await screen.findByText("p. 1 / 3", {}, { timeout: 3000 })).toBeInTheDocument();
        expect(deps.loadChunk).not.toHaveBeenCalled();
      });

      it("clears the chip highlight when a panel row is opened", async () => {
        await cite();
        await userEvent.click(await reactP2());
        await screen.findByText("p. 2 / 3", {}, { timeout: 3000 });
        await userEvent.click(screen.getByRole("button", { name: "Show panel" }));
        await userEvent.click(await row("ReAct"));
        await waitFor(() => expect(pane("ReAct")).toBeInTheDocument());
        const sources = within(screen.getByRole("list", { name: "Sources" }));
        for (const c of sources.getAllByRole("button")) expect(c).not.toHaveAttribute("aria-current");
      });
    });
  });

  describe("title", () => {
    const started = () => events({ type: "thread", thread_id: "t1" }, { type: "done" });
    const titleButton = () => screen.findByRole("button", { name: "What is attention?. Edit title" });
    const field = () => screen.getByRole("textbox", { name: "Conversation title" });

    async function startConversation(rename: (threadId: string, title: string) => Promise<string>) {
      renderChat({ ask: vi.fn(started), rename });
      await userEvent.type(await question(), "What is attention?");
      await userEvent.click(askButton());
      return titleButton();
    }

    it("can't be edited before the conversation exists", async () => {
      renderChat();
      await question();
      expect(screen.getByRole("heading", { level: 1, name: "New conversation" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Edit title/ })).not.toBeInTheDocument();
    });

    it("opens with the title selected, and Enter saves the trimmed title and returns focus", async () => {
      const rename = vi.fn(async (_id: string, title: string) => title);
      await userEvent.click(await startConversation(rename));
      const input = field() as HTMLInputElement;
      expect(input).toHaveFocus();
      expect(input).toHaveValue("What is attention?");
      expect([input.selectionStart, input.selectionEnd]).toEqual([0, "What is attention?".length]);
      expect(input).toHaveAttribute("maxlength", "120");

      await userEvent.paste("  Attention basics ");
      await userEvent.keyboard("{Enter}");

      const renamed = await screen.findByRole("button", { name: "Attention basics. Edit title" });
      expect(renamed).toHaveFocus();
      expect(rename).toHaveBeenCalledTimes(1);
      expect(rename).toHaveBeenCalledWith("t1", "Attention basics");
      expect(screen.queryByRole("textbox", { name: "Conversation title" })).not.toBeInTheDocument();
    });

    it("Esc cancels and restores the old title", async () => {
      const rename = vi.fn(async (_id: string, title: string) => title);
      await userEvent.click(await startConversation(rename));
      await userEvent.paste("Something else");
      await userEvent.keyboard("{Escape}");
      expect(rename).not.toHaveBeenCalled();
      expect(await titleButton()).toHaveFocus();
    });

    it("clicking away saves", async () => {
      const rename = vi.fn(async (_id: string, title: string) => title);
      await userEvent.click(await startConversation(rename));
      await userEvent.clear(field());
      await userEvent.paste("Attention basics");
      await userEvent.click(await question());
      expect(rename).toHaveBeenCalledWith("t1", "Attention basics");
      expect(await screen.findByRole("button", { name: "Attention basics. Edit title" })).not.toHaveFocus();
    });

    it("shows Enter a title under an empty field, saves nothing, and clicking away cancels", async () => {
      const rename = vi.fn(async (_id: string, title: string) => title);
      await userEvent.click(await startConversation(rename));
      await userEvent.clear(field());
      expect(screen.getByRole("alert")).toHaveTextContent("Enter a title");
      expect(field()).toHaveAttribute("aria-invalid", "true");
      expect(field()).toHaveAccessibleDescription("Enter a title");
      await userEvent.type(field(), "   {Enter}");
      expect(field()).toBeInTheDocument();
      await userEvent.click(await question());
      expect(rename).not.toHaveBeenCalled();
      expect(await titleButton()).toBeInTheDocument();
    });

    it("keeps the field open with the server's message when the title is refused", async () => {
      const rename = vi.fn(async () => {
        throw new Error("An archived conversation can't be renamed. Restore it first.");
      });
      await userEvent.click(await startConversation(rename));
      await userEvent.type(field(), " again{Enter}");
      expect(await screen.findByRole("alert")).toHaveTextContent("An archived conversation can't be renamed.");
      expect(field()).toHaveValue("What is attention? again");
      await userEvent.keyboard("{Escape}");
      expect(await titleButton()).toBeInTheDocument();
    });

    it("saves nothing when the title is unchanged", async () => {
      const rename = vi.fn(async (_id: string, title: string) => title);
      await userEvent.click(await startConversation(rename));
      await userEvent.keyboard("{Enter}");
      expect(rename).not.toHaveBeenCalled();
      expect(await titleButton()).toHaveFocus();
    });

    it("works by keyboard alone, next to the panel toggle", async () => {
      const rename = vi.fn(async (_id: string, title: string) => title);
      const button = await startConversation(rename);
      const toggle = screen.getByRole("button", { name: "Hide panel" });
      expect(toggle).toHaveAttribute("aria-expanded", "true");
      toggle.focus();
      await userEvent.keyboard("{Enter}");
      expect(screen.getByRole("button", { name: "Show panel" })).toHaveAttribute("aria-expanded", "false");
      await userEvent.tab();
      expect(button).toHaveFocus();
      await userEvent.keyboard("{Enter}");
      // The title opens selected, so typing replaces it.
      await userEvent.keyboard("Renamed{Enter}");
      expect(rename).toHaveBeenCalledWith("t1", "Renamed");
      expect(await screen.findByRole("button", { name: "Renamed. Edit title" })).toHaveFocus();
    });

    it("goes back to the question when a new question starts a new conversation", async () => {
      const ask = vi.fn(started);
      renderChat({ ask, rename: async (_id, title) => title });
      await userEvent.type(await question(), "What is attention?");
      await userEvent.click(askButton());
      await userEvent.click(await titleButton());
      await userEvent.paste("Attention basics");
      await userEvent.keyboard("{Enter}");
      await screen.findByRole("button", { name: "Attention basics. Edit title" });
      await userEvent.click(await question());
      await userEvent.paste("What is a transformer?");
      await userEvent.click(askButton());
      expect(await screen.findByRole("button", { name: "What is a transformer?. Edit title" })).toBeInTheDocument();
    });
  });

  describe("starting from a document", () => {
    const TITLE = "ReAct: Synergizing Reasoning and Acting";
    const NOTICE = `Started from ${TITLE}. It's listed in Documents; answers still use all your documents.`;
    const library = (overrides: Partial<DocumentResponse> = {}) =>
      ({ document_id: "d1", title: TITLE, state: "ready", archived: false, authors: ["Yao"], year: 2023, ...overrides }) as DocumentResponse;
    const panel = () => screen.queryByRole("complementary", { name: "Conversation" });
    const notice = () => screen.queryByText((_, el) => el?.tagName === "P" && el.textContent === NOTICE);
    const startChat = (props: ComponentProps<typeof ChatPage> = {}, docs = [library()]) =>
      renderChat({ loadDocs: async () => docs, ...props }, "/chat?document=d1");
    const answered = () => events({ type: "thread", thread_id: "t1" }, { type: "delta", text: "Yes." }, { type: "done" });

    it("lists the document as Added, says where the conversation started, and focuses the composer", async () => {
      startChat();
      await question();
      const rows = await within(panel()!).findAllByRole("listitem");
      expect(rows.map((r) => r.textContent)).toEqual([`${TITLE}Added`]);
      expect(notice()).toBeInTheDocument();
      expect(notice()!.querySelector("em")).toHaveTextContent(TITLE);
      await waitFor(() => expect(screen.getByRole("textbox", { name: /question/i })).toHaveFocus());
    });

    it("sends the document with the first question only, and drops the notice once asked", async () => {
      const control = controlledStream();
      const ask = vi.fn().mockImplementationOnce(answered).mockImplementationOnce(() => control.stream());
      startChat({ ask });
      await userEvent.type(await question(), "q");
      await userEvent.click(askButton());
      expect(ask).toHaveBeenNthCalledWith(1, "q", "d1");
      expect(await screen.findByText("Yes.")).toBeInTheDocument();
      expect(notice()).not.toBeInTheDocument();
      await userEvent.type(await question(), "q2");
      await waitFor(() => expect(askButton()).toBeEnabled());
      await userEvent.click(askButton());
      expect(ask).toHaveBeenNthCalledWith(2, "q2", undefined);
      expect(within(panel()!).queryByText(TITLE)).not.toBeInTheDocument();
      control.push(null);
    });

    it("drops the document and the notice when its row is removed before asking", async () => {
      const ask = vi.fn(answered);
      const removeDoc = vi.fn(async () => {});
      startChat({ ask, removeDoc });
      await question();
      await userEvent.click(await within(panel()!).findByRole("button", { name: `Remove ${TITLE} from this conversation` }));
      expect(removeDoc).not.toHaveBeenCalled();
      expect(within(panel()!).getByText("Documents used to answer will appear here.")).toBeInTheDocument();
      expect(notice()).not.toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent(`${TITLE} removed from this conversation.`);
      await userEvent.type(await question(), "q");
      await userEvent.click(askButton());
      expect(ask).toHaveBeenCalledWith("q", undefined);
    });

    it.each([
      ["an archived document", [library({ archived: true })]],
      ["a processing document", [library({ state: "processing" }), library({ document_id: "d2" })]],
      ["an unknown document", [library({ document_id: "d2" })]],
    ])("ignores %s", async (_, docs) => {
      const ask = vi.fn(answered);
      startChat({ ask }, docs);
      await question();
      expect(notice()).not.toBeInTheDocument();
      expect(within(panel()!).getByText("Documents used to answer will appear here.")).toBeInTheDocument();
      await userEvent.type(await question(), "q");
      await userEvent.click(askButton());
      expect(ask).toHaveBeenCalledWith("q", undefined);
    });

    it("shows a refusal of the document as a problem line", async () => {
      const ask = vi.fn(() => {
        throw new AskRefusedError("Document not found");
      });
      startChat({ ask });
      await userEvent.type(await question(), "q");
      await userEvent.click(askButton());
      expect(await screen.findByText("Document not found")).toBeInTheDocument();
    });

    it("opens the panel when it was left closed", async () => {
      localStorage.setItem("smart-tutor.chat-panel-open", "false");
      startChat();
      expect(await within((await screen.findByRole("complementary", { name: "Conversation" }))).findByText(TITLE)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Hide panel" })).toHaveAttribute("aria-expanded", "true");
      // The page's open is not the learner's choice: the saved "closed" stays, and closing the panel keeps it.
      expect(localStorage.getItem("smart-tutor.chat-panel-open")).toBe("false");
      await userEvent.click(screen.getByRole("button", { name: "Hide panel" }));
      expect(panel()).not.toBeInTheDocument();
      expect(localStorage.getItem("smart-tutor.chat-panel-open")).toBe("false");
    });

    it("closes the panel in one click when it was already open, saving the choice", async () => {
      startChat();
      await question();
      expect(await within(panel()!).findByText(TITLE)).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Hide panel" }));
      expect(panel()).not.toBeInTheDocument();
      expect(localStorage.getItem("smart-tutor.chat-panel-open")).toBe("false");
    });

    const startChatAt = (props: ComponentProps<typeof ChatPage>) => renderChat({ loadDocs: async () => [library()], ...props }, "/chat?document=d1");

    it("takes the document param out of the URL once the first question uses it, without resetting the page", async () => {
      const control = controlledStream();
      const loadDocs = vi.fn(async () => [library()]);
      startChatAt({ ask: vi.fn(() => control.stream()), loadDocs });
      expect(screen.getByTestId("location")).toHaveTextContent("/chat?document=d1");
      await userEvent.type(await question(), "q");
      await userEvent.click(askButton());
      expect(screen.getByTestId("location").textContent).toBe("/chat");
      control.push({ type: "thread", thread_id: "t1" });
      control.push({ type: "delta", text: "Partly." });
      expect(await screen.findByText("Partly.")).toBeInTheDocument();
      expect(loadDocs).toHaveBeenCalledTimes(1);
      control.push({ type: "done" });
      control.push(null);
    });

    it("takes the document param out of the URL when its row is removed", async () => {
      startChatAt({ ask: vi.fn(answered) });
      await question();
      await userEvent.click(await within(panel()!).findByRole("button", { name: `Remove ${TITLE} from this conversation` }));
      expect(screen.getByTestId("location").textContent).toBe("/chat");
      expect(notice()).not.toBeInTheDocument();
    });
  });

  describe("a conversation at its URL", () => {
    const turn = (over: Partial<TurnResponse> = {}): TurnResponse => ({
      question: "What is attention?",
      answer: "It weighs tokens [1].",
      citations: [{ n: 1, chunk_id: "c1", document_id: "d1", document_title: "a.pdf", page: 3, archived: false, deleted: false }],
      decline: null,
      created_at: "2026-10-10T09:00:00Z",
      ...over,
    });
    const cited = (over: Partial<TurnResponse["citations"][number]>) => turn({ citations: [{ ...turn().citations[0]!, ...over }] });
    const conversation = (turns: TurnResponse[], over: Partial<ThreadResponse> = {}) =>
      vi.fn(async () => ({ thread: { thread_id: "t1", title: "Attention basics", search_scope: "library" as const, ...over }, turns }));
    const usedDoc: ThreadDocumentResponse = { document_id: "d1", title: "a.pdf", authors: [], year: null, archived: false, deleted: false, added_by: "answer", used: true };
    const panel = () => screen.queryByRole("complementary", { name: "Conversation" });
    const location = () => screen.getByTestId("location").textContent;
    const asked = () => screen.getAllByText("You asked:").map((label) => label.parentElement!.textContent);

    it("opens a conversation at its URL with its title, history, documents used, and scope", async () => {
      const loadConversation = conversation(
        [turn(), turn({ question: "And in RAG?", answer: "", citations: [], decline: { code: "limited", message: "These documents don't cover this." } })],
        { search_scope: "listed" },
      );
      renderChat({ loadConversation, loadUsed: async () => [usedDoc] }, "/chat/t1");
      expect(await screen.findByRole("button", { name: "Attention basics. Edit title" })).toBeInTheDocument();
      expect(loadConversation).toHaveBeenCalledWith("t1");
      expect(asked()).toEqual(["You asked: What is attention?", "You asked: And in RAG?"]);
      expect(screen.getByText("It weighs tokens [1].")).toBeInTheDocument();
      expect(screen.getByText("These documents don't cover this.")).toBeInTheDocument();
      const sources = screen.getAllByRole("list", { name: "Sources" });
      expect(sources).toHaveLength(1);
      expect(within(sources[0]!).getByRole("listitem")).toHaveTextContent("[1] a.pdf · p. 3");
      expect(await within(panel()!).findByText("a.pdf")).toBeInTheDocument();
      const form = screen.getByRole("textbox", { name: /question/i }).closest("form")!;
      expect(within(form).getByText("Searching 1 document")).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Ask about your documents" })).not.toBeInTheDocument();
    });

    it("a history citation opens the document beside the conversation at its page", async () => {
      const deps = fakeViewerDeps();
      renderChat({ loadConversation: conversation([cited({ document_title: "ReAct", page: 2 })]), viewerDeps: deps }, "/chat/t1");
      const chip = await screen.findByRole("button", { name: /^ReAct, p\. 2\. Open beside the conversation/ });
      await userEvent.click(chip);
      expect(await screen.findByText("p. 2 / 3", {}, { timeout: 3000 })).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "ReAct" })).toBeInTheDocument();
      expect(deps.loadChunk).toHaveBeenCalledWith("c1");
      expect(chip).toHaveAccessibleName(/Shown beside the conversation$/);
      expect(chip).toHaveAttribute("aria-current", "true");
    });

    it("a deleted document's history citation reads Deleted document with no link", async () => {
      renderChat({ loadConversation: conversation([cited({ document_title: "Deleted document", deleted: true })]) }, "/chat/t1");
      const sources = await screen.findByRole("list", { name: "Sources" });
      expect(within(sources).getByRole("listitem")).toHaveTextContent("[1] Deleted document");
      expect(within(sources).queryByRole("button")).not.toBeInTheDocument();
    });

    it("an archived document's history citation says Archived and still opens", async () => {
      renderChat(
        { loadConversation: conversation([cited({ document_title: "ReAct", page: 2, archived: true })]), viewerDeps: fakeViewerDeps() },
        "/chat/t1",
      );
      const chip = await screen.findByRole("button", { name: "ReAct, p. 2, archived. Open beside the conversation" });
      expect(within(chip).getByText("Archived")).toBeInTheDocument();
      await userEvent.click(chip);
      expect(await screen.findByText("p. 2 / 3", {}, { timeout: 3000 })).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "ReAct" })).toBeInTheDocument();
    });

    it("an unknown conversation shows Conversation not found with a way back to Chat", async () => {
      const loadConversation = vi.fn(async () => {
        throw new ConversationNotFoundError();
      });
      renderChat({ loadConversation }, "/chat/nope");
      expect(await screen.findByRole("heading", { name: "Conversation not found" })).toBeInTheDocument();
      expect(screen.getByText("This conversation doesn't exist, or it isn't yours.")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Back to Chat" })).toHaveAttribute("href", "/chat");
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    });

    it("a conversation that can't be loaded says so", async () => {
      const loadConversation = vi.fn(async () => {
        throw new Error("boom");
      });
      renderChat({ loadConversation }, "/chat/t1");
      expect(await screen.findByText("This conversation couldn't be loaded. Reload the page to try again.")).toBeInTheDocument();
    });

    it("a new conversation moves to its URL when its thread is created, and keeps streaming", async () => {
      const control = controlledStream();
      const loadConversation = vi.fn();
      renderChat({ ask: vi.fn(() => control.stream()), loadConversation });
      await userEvent.type(await question(), "What is attention?");
      await userEvent.click(askButton());
      control.push({ type: "thread", thread_id: "t1" });
      await waitFor(() => expect(location()).toBe("/chat/t1"));
      control.push({ type: "delta", text: "It weighs" });
      expect(await screen.findByText("It weighs")).toBeInTheDocument();
      control.push({ type: "done" });
      control.push(null);
      await waitFor(() => expect(screen.getByRole("textbox", { name: /question/i })).toBeEnabled());
      expect(loadConversation).not.toHaveBeenCalled();
    });

    it("an unlimited question in a reopened conversation starts a new conversation at a new URL", async () => {
      const ask = vi.fn(() => events({ type: "thread", thread_id: "t2" }, { type: "delta", text: "Next answer." }, { type: "done" }));
      const askIn = vi.fn();
      renderChat({ loadConversation: conversation([turn()]), ask, askIn }, "/chat/t1");
      expect(await screen.findByText("It weighs tokens [1].")).toBeInTheDocument();
      await userEvent.type(await question(), "Next?");
      await userEvent.click(askButton());
      expect(await screen.findByText("Next answer.")).toBeInTheDocument();
      await waitFor(() => expect(location()).toBe("/chat/t2"));
      expect(screen.queryByText("It weighs tokens [1].")).not.toBeInTheDocument();
      expect(asked()).toEqual(["You asked: Next?"]);
      expect(ask).toHaveBeenCalledWith("Next?", undefined);
      expect(askIn).not.toHaveBeenCalled();
    });

    it("a question in a limited conversation adds a turn under the history", async () => {
      const askIn = vi.fn(() => events({ type: "thread", thread_id: "t1" }, { type: "delta", text: "More." }, { type: "done" }));
      renderChat({ loadConversation: conversation([turn()], { search_scope: "listed" }), loadUsed: async () => [usedDoc], askIn }, "/chat/t1");
      expect(await screen.findByText("Searching 1 document")).toBeInTheDocument();
      await userEvent.type(await question(), "More?");
      await userEvent.click(askButton());
      expect(await screen.findByText("More.")).toBeInTheDocument();
      expect(asked()).toEqual(["You asked: What is attention?", "You asked: More?"]);
      expect(screen.getByText("It weighs tokens [1].")).toBeInTheDocument();
      expect(location()).toBe("/chat/t1");
      expect(askIn).toHaveBeenCalledWith("t1", "More?");
    });

    it("the Chat link starts a new conversation", async () => {
      renderChat({ loadConversation: conversation([turn()]) }, "/chat/t1");
      expect(await screen.findByText("It weighs tokens [1].")).toBeInTheDocument();
      await userEvent.click(screen.getByRole("link", { name: "Chat" }));
      expect(await screen.findByRole("heading", { name: "Ask about your documents" })).toBeInTheDocument();
      expect(screen.queryByText("It weighs tokens [1].")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { level: 1, name: "New conversation" })).toBeInTheDocument();
    });

    it("leaving for another conversation mid-answer drops the old stream's events", async () => {
      const control = controlledStream();
      renderChat({ ask: vi.fn(() => control.stream()) });
      await userEvent.type(await question(), "What is attention?");
      await userEvent.click(askButton());
      control.push({ type: "thread", thread_id: "t1" });
      await waitFor(() => expect(location()).toBe("/chat/t1"));
      await userEvent.click(screen.getByRole("link", { name: "Chat" }));
      expect(await screen.findByRole("heading", { name: "Ask about your documents" })).toBeInTheDocument();
      control.push({ type: "delta", text: "Late." });
      await act(async () => {});
      expect(screen.queryByText("Late.")).not.toBeInTheDocument();
      control.push(null);
    });

    it("a reopened conversation shows its history even with no ready documents", async () => {
      renderChat({ loadConversation: conversation([turn()]), loadDocs: async () => [] }, "/chat/t1");
      expect(await screen.findByText("It weighs tokens [1].")).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Upload a document first" })).not.toBeInTheDocument();
    });

    it("the same passage cited in two turns highlights only the clicked chip", async () => {
      renderChat({ loadConversation: conversation([turn(), turn({ question: "Again?" })]), viewerDeps: fakeViewerDeps() }, "/chat/t1");
      const chips = await screen.findAllByRole("button", { name: /^a\.pdf, p\. 3\. Open/ });
      expect(chips).toHaveLength(2);
      await userEvent.click(chips[1]!);
      expect(await screen.findByRole("region", { name: "ReAct" }, { timeout: 3000 })).toBeInTheDocument();
      expect(chips[1]).toHaveAttribute("aria-current", "true");
      expect(chips[0]).not.toHaveAttribute("aria-current");
    });
  });
});
