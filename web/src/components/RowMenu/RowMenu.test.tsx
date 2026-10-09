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

  it("opens the menu and focuses the first item", async () => {
    const { button } = setup();
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toBeVisible();
    expect(screen.getAllByRole("menuitem")).toHaveLength(2);
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveFocus();
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
