import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DocumentResponse, SubjectSuggestions } from "../../api/documents";
import { SubjectPicker } from "./SubjectPicker";

const doc: DocumentResponse = { document_id: "d1", title: "Toolformer", state: "awaiting_subjects", failure_reason: null, created_at: new Date().toISOString(), subjects: [] };
const suggestions: SubjectSuggestions = {
  document_id: "d1",
  title: "Toolformer",
  summary: "Teaches a language model to call tools.",
  suggestions: [
    { subject_id: "s-agents", name: "AI Agents", origin: "yours" },
    { subject_id: "s-llm", name: "LLMs", origin: "shared" },
    { subject_id: null, name: "Tool Use", origin: "new" },
  ],
};
const saved: DocumentResponse = { ...doc, state: "ready", subjects: [{ subject_id: "s-agents", name: "AI Agents" }] };

function setup(over: Partial<Parameters<typeof SubjectPicker>[0]> = {}) {
  const props = {
    document: doc,
    load: vi.fn(async () => suggestions),
    save: vi.fn(async () => saved),
    onClose: vi.fn(),
    onSaved: vi.fn(),
    ...over,
  };
  render(<SubjectPicker {...props} />);
  return props;
}

const chip = (name: RegExp) => screen.findByRole("button", { name });

describe("SubjectPicker", () => {
  it("shows the document, its summary and three chips with the first selected", async () => {
    setup();
    expect(screen.getByRole("dialog", { name: "Choose subjects" })).toBeVisible();
    expect(screen.getByText("Processing finished")).toBeVisible();
    expect(await screen.findByText("Teaches a language model to call tools.")).toBeVisible();
    expect(screen.getByText("Toolformer")).toBeVisible();
    expect(await chip(/AI Agents/)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /LLMs/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: /Tool Use/ })).toHaveTextContent("New");
    expect(screen.getByRole("button", { name: /LLMs/ })).toHaveTextContent("Shared subject");
    expect(screen.getByRole("button", { name: /AI Agents/ })).toHaveTextContent("Your subject");
    expect(screen.getByRole("group", { name: "Suggested subjects" })).toBeVisible();
    expect(screen.getByText("1 of 3 selected")).toBeVisible();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("disables Save with nothing selected and says why", async () => {
    setup();
    await userEvent.click(await chip(/AI Agents/));
    expect(screen.getByText("0 of 3 selected")).toBeVisible();
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    expect(save).toHaveAccessibleDescription("Choose at least one subject to save.");
  });

  it("stops at three subjects and disables the rest", async () => {
    const four: SubjectSuggestions = { ...suggestions, suggestions: [...suggestions.suggestions, { subject_id: "s-rl", name: "RL", origin: "shared" }] };
    setup({ load: vi.fn(async () => four) });
    await userEvent.click(await chip(/LLMs/));
    await userEvent.click(screen.getByRole("button", { name: /Tool Use/ }));
    expect(screen.getByText("3 of 3 selected · the maximum")).toBeVisible();
    expect(screen.getByText("You've chosen 3 subjects, the maximum. Remove one to add another.")).toBeVisible();
    expect(screen.getByRole("button", { name: /RL/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /LLMs/ })).toBeEnabled();
  });

  it("saves ids and new names, then confirms and closes on Done", async () => {
    const props = setup();
    await userEvent.click(await chip(/Tool Use/));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(props.save).toHaveBeenCalledWith("d1", { subject_ids: ["s-agents"], new_names: ["Tool Use"] });
    expect(await screen.findByText("Subjects saved.")).toBeVisible();
    expect(screen.getByText("is ready to use.", { exact: false })).toHaveTextContent("Toolformer is ready to use.");
    expect(props.onSaved).toHaveBeenCalledTimes(1);
    expect(props.onSaved).toHaveBeenCalledWith(saved);
    const done = screen.getByRole("button", { name: "Done" });
    expect(done).toHaveFocus();
    await userEvent.click(done);
    expect(props.onClose).toHaveBeenCalled();
  });

  it("keeps the picker open with the selection when saving fails", async () => {
    const save = vi.fn(async () => {
      throw new Error("Choose at most three subjects");
    });
    const props = setup({ save });
    await userEvent.click(await chip(/LLMs/));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Couldn't save subjects. Try again./)).toBeVisible();
    expect(screen.getByText(/Choose at most three subjects/)).toBeVisible();
    expect(screen.getByRole("button", { name: /LLMs/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    expect(props.onSaved).not.toHaveBeenCalled();
  });

  it("disables Save while saving", async () => {
    let finish!: (d: DocumentResponse) => void;
    const save = vi.fn(() => new Promise<DocumentResponse>((r) => (finish = r)));
    setup({ save });
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    finish(saved);
    expect(await screen.findByText("Subjects saved.")).toBeVisible();
  });

  it("offers a retry when the suggestions don't load", async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error("boom")).mockResolvedValue(suggestions);
    setup({ load });
    expect(screen.getByText("Loading suggestions…")).toBeVisible();
    expect(await screen.findByText("Couldn't load suggestions. Try again.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await chip(/AI Agents/)).toBeVisible();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("cancels", async () => {
    const props = setup();
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(props.onClose).toHaveBeenCalled();
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Save" })).toBeVisible();
  });
});
