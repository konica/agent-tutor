import { afterEach, describe, expect, it } from "vitest";

import styles from "./ChatPage.module.css";

afterEach(() => document.body.replaceChildren());

describe("ChatPage layout", () => {
  // .visually-hidden is position: absolute. In an unpositioned scroller its containing block is the shell's <main>, so a
  // hidden "You asked:" far down the conversation stretched <main> and the page grew a second scrollbar (split view).
  it("makes the messages scroller the containing block for its visually hidden text", () => {
    const messages = document.createElement("div");
    messages.className = styles.messages!;
    document.body.append(messages);

    const style = getComputedStyle(messages);
    expect(style.overflowY).toBe("auto");
    expect(style.position).toBe("relative");
  });
});
