import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { SidePanel } from "./SidePanel";

function open(onClose = vi.fn(), extra: ReactNode = <p>Body</p>) {
  render(
    <SidePanel labelledBy="t" kicker="Document details" badge={<span>Ready</span>} closeLabel="Close document details" onClose={onClose} footer={<button type="button">Archive</button>}>
      <h2 id="t">My title</h2>
      {extra}
    </SidePanel>,
  );
  return onClose;
}

describe("SidePanel", () => {
  it("is a modal dialog named by the labelling element, with kicker and badge", () => {
    open();
    expect(screen.getByRole("dialog", { name: "My title" })).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("Document details")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("closes from the close button and on Escape", async () => {
    const onClose = open();
    await userEvent.click(screen.getByRole("button", { name: "Close document details" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("starts focus on [data-autofocus] inside the children", () => {
    open(vi.fn(), <input data-autofocus aria-label="title" />);
    expect(screen.getByLabelText("title")).toHaveFocus();
  });

  it("wraps Tab from the last focusable to the first", async () => {
    open();
    screen.getByRole("button", { name: "Archive" }).focus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Close document details" })).toHaveFocus();
  });

  it("returns focus to the opener on unmount", async () => {
    function Host() {
      const [shown, setShown] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setShown(true)}>
            Open
          </button>
          {shown && (
            <SidePanel labelledBy="t" kicker="k" closeLabel="Close" onClose={() => setShown(false)}>
              <h2 id="t">T</h2>
            </SidePanel>
          )}
        </>
      );
    }
    render(<Host />);
    const opener = screen.getByRole("button", { name: "Open" });
    await userEvent.click(opener);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(opener).toHaveFocus();
  });
});
