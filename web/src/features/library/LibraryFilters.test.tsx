import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LibraryFilters } from "./LibraryFilters";
import uploadedStyles from "./UploadedFilter.module.css";

const subjects = [
  { subject_id: "s1", name: "AI Agents" },
  { subject_id: "s2", name: "LLMs" },
];

function setup(filters = {}, count: number | null = 3, needsSubjects = 0) {
  const onChange = vi.fn();
  const onClear = vi.fn();
  render(<LibraryFilters filters={filters} onChange={onChange} subjects={subjects} count={count} needsSubjects={needsSubjects} onClear={onClear} />);
  return { onChange, onClear };
}

const openUploaded = () => userEvent.click(screen.getByRole("button", { name: /^Uploaded/ }));

describe("LibraryFilters", () => {
  it("is a labelled search landmark with a labelled control each", () => {
    setup();
    expect(screen.getByRole("search", { name: "Filter documents" })).toBeVisible();
    expect(screen.getByLabelText("Subject")).toBeVisible();
    expect(screen.getByRole("button", { name: "Uploaded" })).toBeVisible();
    expect(screen.getByLabelText("State")).toBeVisible();
  });

  it("hides the State filter and the needs-subjects chip when showState is false", () => {
    render(<LibraryFilters filters={{}} onChange={vi.fn()} subjects={subjects} count={1} needsSubjects={2} onClear={vi.fn()} showState={false} />);
    expect(screen.getByLabelText("Subject")).toBeVisible();
    expect(screen.queryByLabelText("State")).toBeNull();
    expect(screen.queryByRole("button", { name: /need subjects/ })).toBeNull();
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
    await openUploaded();
    await userEvent.type(screen.getByLabelText("From"), "2026-10-01");
    expect(onChange).toHaveBeenLastCalledWith({ uploaded_from: "2026-10-01" });
  });

  it("drops a key when its control goes back to All", async () => {
    const { onChange } = setup({ subject_ids: ["s1"], state: "ready" });
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "All subjects");
    expect(onChange).toHaveBeenLastCalledWith({ state: "ready" });
  });

  it("ties the date inputs to each other", async () => {
    setup({ uploaded_from: "2026-10-01", uploaded_to: "2026-10-07" });
    await openUploaded();
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

  it("filters by the needs-subjects chip and clears it on a second press", async () => {
    const { onChange } = setup({}, 3, 2);
    await userEvent.click(screen.getByRole("button", { name: "2 need subjects" }));
    expect(onChange).toHaveBeenLastCalledWith({ state: "awaiting_subjects" });
  });

  it("shows the chip pressed while the state filter is on, and pressing it again clears the filter", async () => {
    const { onChange } = setup({ state: "awaiting_subjects" }, 3, 1);
    const chip = screen.getByRole("button", { name: "1 needs subjects" });
    expect(chip).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(chip);
    expect(onChange).toHaveBeenLastCalledWith({});
  });

  it("reads Needs subjects, with no number, while pressed and none is left", () => {
    setup({ state: "awaiting_subjects" }, 0, 0);
    expect(screen.getByRole("button", { name: "Needs subjects" })).toHaveAttribute("aria-pressed", "true");
  });

  it("hides the chip when nothing needs subjects", () => {
    setup({ state: "ready" }, 3, 0);
    expect(screen.queryByRole("button", { name: /needs? subjects/ })).toBeNull();
  });

  it("keeps every filter labelled though the labels are hidden", () => {
    setup();
    expect(screen.getByLabelText("Subject")).toBeInTheDocument();
    expect(screen.getByLabelText("State")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Uploaded" })).toHaveAttribute("aria-expanded", "false");
  });
});

describe("UploadedFilter", () => {
  it("opens a From/To group with focus on From", async () => {
    setup();
    await openUploaded();
    expect(screen.getByRole("group", { name: "Upload dates" })).toBeVisible();
    expect(screen.getByLabelText("From")).toHaveFocus();
    expect(screen.getByLabelText("To")).toBeVisible();
  });

  it("closes on Escape and returns focus to the button", async () => {
    setup();
    await openUploaded();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("group", { name: "Upload dates" })).toBeNull();
    expect(screen.getByRole("button", { name: "Uploaded" })).toHaveFocus();
  });

  it("closes when focus leaves it", async () => {
    setup();
    await openUploaded();
    await userEvent.tab({ shift: true });
    await userEvent.tab({ shift: true });
    expect(screen.queryByRole("group", { name: "Upload dates" })).toBeNull();
  });

  it("names the range on the button and marks it active", () => {
    setup({ uploaded_from: "2026-09-01" });
    const button = screen.getByRole("button", { name: "Uploaded: from 2026-09-01" });
    expect(button).toHaveClass(uploadedStyles.on);
  });

  it("is not marked active without a range", () => {
    setup();
    expect(screen.getByRole("button", { name: "Uploaded" })).not.toHaveClass(uploadedStyles.on);
  });
});
