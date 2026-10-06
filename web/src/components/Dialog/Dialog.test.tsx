import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Dialog } from "./Dialog";

function open(onClose = vi.fn()) {
  render(
    <Dialog title="Choose subjects" kicker="Processing finished" onClose={onClose} footer={<button type="button">Save</button>}>
      <p>Body</p>
    </Dialog>,
  );
  return onClose;
}

describe("Dialog", () => {
  it("is a modal dialog labelled by its title", () => {
    open();
    const dialog = screen.getByRole("dialog", { name: "Choose subjects" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("Processing finished")).toBeInTheDocument();
  });

  it("closes on Escape and on the close button", () => {
    const onClose = open();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("moves focus inside on open and restores it on unmount", () => {
    const trigger = document.createElement("button");
    document.body.append(trigger);
    trigger.focus();
    const { unmount } = render(
      <Dialog title="T" onClose={() => {}} footer={null}>
        <input data-autofocus aria-label="name" />
      </Dialog>,
    );
    expect(screen.getByLabelText("name")).toHaveFocus();
    unmount();
    expect(trigger).toHaveFocus();
    trigger.remove();
  });

  it("wraps Tab from the last focusable element to the first", () => {
    open();
    const first = screen.getByRole("button", { name: "Close" });
    const last = screen.getByRole("button", { name: "Save" });
    last.focus();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Tab" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });
});
