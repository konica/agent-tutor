import { render } from "@testing-library/react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { describe, expect, it } from "vitest";

import { remarkCitationMarkers } from "./remarkCitationMarkers";

function renderMarkdown(text: string) {
  const { container } = render(<Markdown remarkPlugins={[remarkGfm, remarkCitationMarkers]}>{text}</Markdown>);
  return container;
}

const marks = (root: ParentNode) =>
  [...root.querySelectorAll("span[data-marker]")].map((s) => [s.getAttribute("data-marker"), s.textContent]);

describe("remarkCitationMarkers", () => {
  it("marks a single marker with its brackets and keeps the text", () => {
    const root = renderMarkdown("It weighs tokens [1].");
    expect(marks(root)).toEqual([["1", "[1]"]]);
    expect(root).toHaveTextContent("It weighs tokens [1].");
  });

  it("marks each number of a group or range", () => {
    const root = renderMarkdown("Both [1, 2] and [1–3].");
    expect(marks(root)).toEqual([["1", "1"], ["2", "2"], ["1", "1"], ["3", "3"]]);
    expect(root).toHaveTextContent("Both [1, 2] and [1–3].");
  });

  it("marks markers in emphasis, list items, headings, and table cells", () => {
    const root = renderMarkdown("**Bold [1]**\n\n- item [2]\n\n## Head [3]\n\n| a | b |\n|---|---|\n| cell [4] | x |");
    expect(marks(root).map(([n]) => n)).toEqual(["1", "2", "3", "4"]);
    expect(root.querySelector("strong span[data-marker]")).not.toBeNull();
    expect(root.querySelector("li span[data-marker]")).not.toBeNull();
    expect(root.querySelector("td span[data-marker]")).not.toBeNull();
  });

  it("leaves markers in inline code, fenced code, and link text as text", () => {
    const root = renderMarkdown("Use `x[1]` and [see [2]](https://example.com).\n\n```\nlist[3]\n```");
    expect(marks(root)).toEqual([]);
    expect(root.querySelector("code")).toHaveTextContent("x[1]");
    expect(root.querySelector("a")).toHaveTextContent("see [2]");
    expect(root.querySelector("pre")).toHaveTextContent("list[3]");
  });

  it("keeps a references line without a URL visible, with its marker", () => {
    const root = renderMarkdown("Sources:\n\n[1]: Doc 1, p. 2");
    expect(root).toHaveTextContent("[1]: Doc 1, p. 2");
    expect(marks(root)).toEqual([["1", "[1]"]]);
  });
});
