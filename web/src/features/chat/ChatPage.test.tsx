import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NoDocumentsError, type ChatEvent } from "../../api/chat";
import { sessionExpiry } from "../../auth/authClient";
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

const show = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);
const question = () => screen.getByRole("textbox", { name: /question/i });
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
            { chunk_id: "c1", document_title: "a.pdf", page: 3 },
            { chunk_id: "c2", document_title: "b.pdf", page: null },
          ],
        },
        { type: "done" },
      ),
    );
    show(<ChatPage ask={ask} />);
    await userEvent.type(question(), "What is attention?");
    await userEvent.click(askButton());
    expect(ask).toHaveBeenCalledWith("What is attention?");
    expect(await screen.findByText("It weighs tokens [1].")).toBeInTheDocument();
    expect(screen.getByText("What is attention?")).toBeInTheDocument();
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("a.pdf, p. 3")).toBeInTheDocument();
    expect(screen.getByText("b.pdf, page unavailable")).toBeInTheDocument();
  });

  it("does not ask an empty or blank question", async () => {
    const ask = vi.fn(() => events({ type: "done" }));
    show(<ChatPage ask={ask} />);
    expect(askButton()).toBeDisabled();
    await userEvent.type(question(), "   ");
    expect(askButton()).toBeDisabled();
    await userEvent.type(question(), "{Enter}");
    expect(ask).not.toHaveBeenCalled();
  });

  it("disables the question and the button while answering, marks the answer busy, then allows another question", async () => {
    const control = controlledStream();
    const ask = vi.fn(() => control.stream());
    show(<ChatPage ask={ask} />);
    await userEvent.type(question(), "What is attention?");
    await userEvent.click(askButton());

    control.push({ type: "thread", thread_id: "t1", subjects: [] });
    control.push({ type: "delta", text: "It weighs" });
    const answer = await screen.findByText("It weighs");
    const region = answer.closest("[aria-live]")!;
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveAttribute("aria-busy", "true");
    expect(question()).toBeDisabled();
    expect(askButton()).toBeDisabled();

    control.push({ type: "done" });
    control.push(null);
    await waitFor(() => expect(region).toHaveAttribute("aria-busy", "false"));
    expect(question()).toBeEnabled();
    await userEvent.type(question(), "Another?");
    expect(askButton()).toBeEnabled();
  });

  it("points to the Library when there are no documents", async () => {
    const ask = vi.fn(() => {
      throw new NoDocumentsError("Upload a document first");
    });
    show(<ChatPage ask={ask} />);
    await userEvent.type(question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByText("Upload a document first")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /library/i })).toHaveAttribute("href", "/library");
  });

  it("shows the message of an unavailable error", async () => {
    const ask = vi.fn(() =>
      events(
        { type: "thread", thread_id: "t1", subjects: [] },
        { type: "error", code: "unavailable", message: "The tutor is unavailable. Try again in a moment." },
      ),
    );
    show(<ChatPage ask={ask} />);
    await userEvent.type(question(), "What is attention?");
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
    show(<ChatPage ask={ask} />);
    await userEvent.type(question(), "What is attention?");
    await userEvent.click(askButton());
    await waitFor(() => expect(notify).toHaveBeenCalledOnce());
  });

  it("shows a generic message when the stream ends without done or error, keeping the partial answer", async () => {
    const ask = vi.fn(() =>
      events({ type: "thread", thread_id: "t1", subjects: [] }, { type: "delta", text: "It weighs" }),
    );
    show(<ChatPage ask={ask} />);
    await userEvent.type(question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByText("The tutor couldn't answer right now. Try again in a moment.")).toBeInTheDocument();
    expect(screen.getByText("It weighs")).toBeInTheDocument();
  });

  it("shows a generic message when asking fails", async () => {
    const ask = vi.fn(async function* (): AsyncGenerator<ChatEvent> {
      throw new Error("POST /threads failed (500)");
    });
    show(<ChatPage ask={ask} />);
    await userEvent.type(question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByText("The tutor couldn't answer right now. Try again in a moment.")).toBeInTheDocument();
  });
});
