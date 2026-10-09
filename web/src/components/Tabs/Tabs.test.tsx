import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Tabs } from "./Tabs";

const tabs = [
  { value: "active", label: "Active", count: 3 },
  { value: "archived", label: "Archived" },
  { value: "other", label: "Other" },
];

describe("Tabs", () => {
  it("renders a labelled tablist with the selected tab marked", () => {
    render(<Tabs label="Library view" tabs={tabs} value="active" onChange={() => {}} />);
    expect(screen.getByRole("tablist", { name: "Library view" })).toBeVisible();
    expect(screen.getByRole("tab", { name: /Active/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Archived" })).toHaveAttribute("aria-selected", "false");
  });

  it("shows the count and uses roving tabindex", () => {
    render(<Tabs label="Library view" tabs={tabs} value="active" onChange={() => {}} />);
    expect(screen.getByRole("tab", { name: /Active/ })).toHaveTextContent("3");
    expect(screen.getByRole("tab", { name: /Active/ })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Archived" })).toHaveAttribute("tabindex", "-1");
  });

  it("selects a tab on click", async () => {
    const onChange = vi.fn();
    render(<Tabs label="Library view" tabs={tabs} value="active" onChange={onChange} />);
    await userEvent.click(screen.getByRole("tab", { name: "Archived" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith("archived");
  });

  it("moves focus and selection with arrows, Home, and End", async () => {
    const onChange = vi.fn();
    render(<Tabs label="Library view" tabs={tabs} value="active" onChange={onChange} />);
    screen.getByRole("tab", { name: /Active/ }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("archived");
    expect(screen.getByRole("tab", { name: "Archived" })).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(onChange).toHaveBeenLastCalledWith("other");
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("active");
    await userEvent.keyboard("{ArrowLeft}");
    expect(onChange).toHaveBeenLastCalledWith("other");
    await userEvent.keyboard("{Home}");
    expect(onChange).toHaveBeenLastCalledWith("active");
    expect(screen.getByRole("tab", { name: /Active/ })).toHaveFocus();
  });
});
