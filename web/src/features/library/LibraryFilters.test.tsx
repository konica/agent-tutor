import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LibraryFilters } from "./LibraryFilters";

const subjects = [
  { subject_id: "s1", name: "AI Agents" },
  { subject_id: "s2", name: "LLMs" },
];

function setup(filters = {}, count: number | null = 3) {
  const onChange = vi.fn();
  const onClear = vi.fn();
  render(<LibraryFilters filters={filters} onChange={onChange} subjects={subjects} count={count} onClear={onClear} />);
  return { onChange, onClear };
}

describe("LibraryFilters", () => {
  it("is a labelled search landmark with a labelled control each", () => {
    setup();
    expect(screen.getByRole("search", { name: "Filter documents" })).toBeVisible();
    expect(screen.getByLabelText("Subject")).toBeVisible();
    expect(screen.getByLabelText("From")).toBeVisible();
    expect(screen.getByLabelText("To")).toBeVisible();
    expect(screen.getByLabelText("State")).toBeVisible();
  });

  it("offers all subjects first, then the learner's subjects", () => {
    setup();
    const options = [...(screen.getByLabelText("Subject") as HTMLSelectElement).options].map((o) => o.text);
    expect(options).toEqual(["All subjects", "AI Agents", "LLMs"]);
  });

  it("offers the document states by their badge labels", () => {
    setup();
    const options = [...(screen.getByLabelText("State") as HTMLSelectElement).options].map((o) => o.text);
    expect(options).toEqual(["All states", "Processing", "Choose subjects", "Ready", "Failed"]);
  });

  it("reports a chosen subject, state and dates", async () => {
    const { onChange } = setup();
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "s2");
    expect(onChange).toHaveBeenLastCalledWith({ subject_ids: ["s2"] });
    await userEvent.selectOptions(screen.getByLabelText("State"), "awaiting_subjects");
    expect(onChange).toHaveBeenLastCalledWith({ state: "awaiting_subjects" });
    await userEvent.type(screen.getByLabelText("From"), "2026-10-01");
    expect(onChange).toHaveBeenLastCalledWith({ uploaded_from: "2026-10-01" });
  });

  it("drops a key when its control goes back to All", async () => {
    const { onChange } = setup({ subject_ids: ["s1"], state: "ready" });
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "All subjects");
    expect(onChange).toHaveBeenLastCalledWith({ state: "ready" });
  });

  it("ties the date inputs to each other", () => {
    setup({ uploaded_from: "2026-10-01", uploaded_to: "2026-10-07" });
    expect(screen.getByLabelText("From")).toHaveAttribute("max", "2026-10-07");
    expect(screen.getByLabelText("To")).toHaveAttribute("min", "2026-10-01");
  });

  it("counts documents", () => {
    setup({}, 3);
    expect(screen.getByText("3 documents")).toBeVisible();
  });

  it("uses the singular for one document", () => {
    setup({}, 1);
    expect(screen.getByText("1 document")).toBeVisible();
  });

  it("shows Clear filters only while a filter is set", async () => {
    const first = setup();
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
    expect(first.onClear).not.toHaveBeenCalled();
  });

  it("clears through the button", async () => {
    const { onClear } = setup({ state: "ready" });
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(onClear).toHaveBeenCalledOnce();
  });
});
