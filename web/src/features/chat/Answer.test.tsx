import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { ChatCitation } from "../../api/chat";
import { Answer } from "./Answer";

const cite = (n: number, over: Partial<ChatCitation> = {}): ChatCitation => ({
  n,
  chunk_id: `c${n}`,
  document_id: `d${n}`,
  document_title: `Doc ${n}`,
  page: n + 1,
  ...over,
});

function renderAnswer(props: Partial<ComponentProps<typeof Answer>> = {}) {
  const onOpenCitation = vi.fn();
  render(
    <Answer
      text="It weighs tokens [1]."
      citations={[cite(1)]}
      showCitations
      deletedIds={new Set()}
      shownChunkId={null}
      onOpenCitation={onOpenCitation}
      {...props}
    />,
  );
  return onOpenCitation;
}

const paragraph = () => document.querySelector("p")!;
const markers = () => within(paragraph()).queryAllByRole("button");

describe("Answer", () => {
  it("links a marker to its source and keeps the text as written", async () => {
    const onOpen = renderAnswer();
    const marker = within(paragraph()).getByRole("button", { name: "Source 1: Doc 1, p. 2" });
    expect(marker).toHaveTextContent("[1]");
    expect(marker).toHaveAttribute("title", "Source 1: Doc 1, p. 2");
    expect(paragraph()).toHaveTextContent("It weighs tokens [1].");
    await userEvent.click(marker);
    expect(onOpen).toHaveBeenCalledWith(cite(1), marker);
  });

  it("is reachable by keyboard and opens with Enter", async () => {
    const onOpen = renderAnswer();
    await userEvent.tab();
    expect(within(paragraph()).getByRole("button")).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("links each number of a group", () => {
    renderAnswer({ text: "Both [1, 2].", citations: [cite(1), cite(2)] });
    expect(markers().map((m) => m.textContent)).toEqual(["1", "2"]);
    expect(markers().map((m) => m.getAttribute("aria-label"))).toEqual(["Source 1: Doc 1, p. 2", "Source 2: Doc 2, p. 3"]);
    expect(paragraph()).toHaveTextContent("Both [1, 2].");
  });

  it("links the numbers a range shows, with a hyphen or an en dash", () => {
    renderAnswer({ text: "All [1-3] and [1–3].", citations: [cite(1), cite(2), cite(3)] });
    expect(markers().map((m) => m.textContent)).toEqual(["1", "3", "1", "3"]);
  });

  it("keeps a number with no source as text", () => {
    renderAnswer({ text: "See [2] and [7] and x[0] and [1, 7].", citations: [cite(2), cite(1)] });
    expect(markers().map((m) => m.getAttribute("aria-label"))).toEqual(["Source 2: Doc 2, p. 3", "Source 1: Doc 1, p. 2"]);
  });

  it("says page unavailable for a citation without a page", () => {
    renderAnswer({ citations: [cite(1, { page: null })] });
    expect(within(paragraph()).getByRole("button", { name: "Source 1: Doc 1, page unavailable" })).toBeInTheDocument();
  });

  it("shows a deleted document's marker as text with Deleted document", () => {
    renderAnswer({ text: "A [1] B [2].", citations: [cite(1, { deleted: true }), cite(2)], deletedIds: new Set(["d2"]) });
    expect(markers()).toHaveLength(0);
    expect(within(paragraph()).getAllByTitle("Deleted document").map((m) => m.textContent)).toEqual(["[1]", "[2]"]);
  });

  it("opens an archived document's marker, saying it is archived", () => {
    renderAnswer({ citations: [cite(1, { archived: true })] });
    expect(within(paragraph()).getByRole("button", { name: "Source 1: Doc 1, p. 2, archived" })).toBeInTheDocument();
  });

  it("marks the shown passage's markers as current", () => {
    renderAnswer({ text: "A [1] B [2] C [1].", citations: [cite(1), cite(2)], shownChunkId: "c1" });
    expect(markers().map((m) => m.getAttribute("aria-current"))).toEqual(["true", null, "true"]);
  });

  it("keeps markers as text until the citations arrive", () => {
    renderAnswer({ citations: [] });
    expect(markers()).toHaveLength(0);
    expect(paragraph()).toHaveTextContent("It weighs tokens [1].");
  });

  it("keeps markers as text with Show citations off", () => {
    renderAnswer({ showCitations: false });
    expect(markers()).toHaveLength(0);
    expect(screen.queryByRole("list", { name: "Sources" })).not.toBeInTheDocument();
  });

  it("never renders the answer as HTML", () => {
    const text = "<b>bold</b> [1] <img src=x onerror=alert(1)>";
    renderAnswer({ text });
    expect(paragraph().querySelector("b, img")).toBeNull();
    expect(paragraph()).toHaveTextContent(text);
    expect(markers()).toHaveLength(1);
  });
});
