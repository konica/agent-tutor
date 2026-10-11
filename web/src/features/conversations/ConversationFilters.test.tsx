import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SubjectResponse } from "../../api/generated/types.gen";
import type { ConversationFilters as Filters } from "../../api/conversations";
import { ConversationFilters } from "./ConversationFilters";

const subjects = [{ subject_id: "s1", name: "Biology" }, { subject_id: "s2", name: "Physics" }] as SubjectResponse[];

function setup(filters: Filters = {}, count: number | null = 3) {
  const onChange = vi.fn();
  const onClear = vi.fn();
  render(<ConversationFilters filters={filters} onChange={onChange} subjects={subjects} count={count} onClear={onClear} />);
  return { onChange, onClear };
}

describe("ConversationFilters", () => {
  it("reports typed title searches", async () => {
    const { onChange } = setup();
    await userEvent.type(screen.getByRole("searchbox", { name: "Search titles" }), "r");
    expect(onChange).toHaveBeenLastCalledWith({ q: "r" });
  });

  it("limits the search to a title's 120 characters", () => {
    setup();
    expect(screen.getByRole("searchbox", { name: "Search titles" })).toHaveAttribute("maxlength", "120");
  });

  it("keeps a typed blank search so the box shows it", async () => {
    const { onChange } = setup();
    await userEvent.type(screen.getByRole("searchbox", { name: "Search titles" }), " ");
    expect(onChange).toHaveBeenLastCalledWith({ q: " " });
  });

  it("chooses a subject by name", async () => {
    const { onChange } = setup();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Subject" }), "Physics");
    expect(onChange).toHaveBeenLastCalledWith({ subject_id: "s2" });
  });

  it("drops the subject for All subjects", async () => {
    const { onChange } = setup({ subject_id: "s2" });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Subject" }), "All subjects");
    expect(onChange).toHaveBeenLastCalledWith({});
  });

  it("sets the first active day from the Date popover", async () => {
    const { onChange } = setup();
    await userEvent.click(screen.getByRole("button", { name: "Date" }));
    await userEvent.type(screen.getByLabelText("From"), "2026-10-01");
    expect(onChange).toHaveBeenLastCalledWith({ active_from: "2026-10-01" });
  });

  it("hides Clear filters until a filter is set", () => {
    setup();
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });

  it("clears the filters", async () => {
    const { onClear } = setup({ q: "rag" });
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(onClear).toHaveBeenCalled();
  });

  it("counts conversations", () => {
    setup({}, 1);
    expect(screen.getByText("1 conversation")).toBeInTheDocument();
  });
});
