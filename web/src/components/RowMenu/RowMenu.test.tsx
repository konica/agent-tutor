import { Archive, Trash2 } from "lucide-react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RowMenu } from "./RowMenu";

const setup = () => {
  const onArchive = vi.fn();
  const onDelete = vi.fn();
  render(
    <>
      <RowMenu
        label="More actions for Notes"
        items={[
          { label: "Archive", icon: Archive, onSelect: onArchive },
          { label: "Delete", icon: Trash2, onSelect: onDelete, danger: true },
        ]}
      />
      <button type="button">Elsewhere</button>
    </>,
  );
  return { onArchive, onDelete, button: screen.getByRole("button", { name: "More actions for Notes" }) };
};

describe("RowMenu", () => {
  it("renders a closed More button with menu semantics", () => {
    const { button } = setup();
    expect(button).toHaveAttribute("aria-haspopup", "menu");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("does not open while disabled", async () => {
    render(<RowMenu label="More actions for Notes" items={[{ label: "Archive", icon: Archive, onSelect: vi.fn() }]} disabled />);
    const button = screen.getByRole("button", { name: "More actions for Notes" });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("opens the menu and focuses the first item", async () => {
    const { button } = setup();
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toBeVisible();
    expect(screen.getAllByRole("menuitem")).toHaveLength(2);
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveFocus();
  });

  it("puts a separator before the danger item, outside the arrow-key order", async () => {
    const { button } = setup();
    await userEvent.click(button);
    const items = screen.getAllByRole("menuitem");
    const separator = screen.getByRole("separator");
    expect(items[0]!.compareDocumentPosition(separator) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(separator.compareDocumentPosition(items[1]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(separator).not.toHaveAttribute("tabindex");
  });

  it("has no separator before the first item or without a danger item", async () => {
    render(<RowMenu label="More" items={[{ label: "Archive", icon: Archive, onSelect: vi.fn() }]} />);
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.queryByRole("separator")).toBeNull();
  });

  it("moves between items with the arrow keys", async () => {
    const { button } = setup();
    await userEvent.click(button);
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
  });

  it("closes on Escape and returns focus to the button", async () => {
    const { button } = setup();
    await userEvent.click(button);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button).toHaveFocus();
  });

  it("closes then calls onSelect once when an item is chosen", async () => {
    const { button, onArchive, onDelete } = setup();
    await userEvent.click(button);
    await userEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    expect(screen.queryByRole("menu")).toBeNull();
    expect(onArchive).toHaveBeenCalledTimes(1);
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("closes when focus leaves the menu", async () => {
    const { button } = setup();
    await userEvent.click(button);
    await userEvent.click(screen.getByRole("button", { name: "Elsewhere" }));
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
