import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DocumentResponse, SubjectSuggestions } from "../../api/documents";
import { SubjectPicker } from "./SubjectPicker";

const doc: DocumentResponse = { document_id: "d1", title: "Toolformer", state: "awaiting_subjects", failure_reason: null, created_at: new Date().toISOString(), subjects: [], attempt: 1, max_attempts: 3, can_retry: false, authors: [], year: null, archived: false };
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
const matches = [
  { subject_id: "s-rag", name: "Retrieval-Augmented Generation", origin: "yours" as const },
  { subject_id: "s-ir", name: "Information Retrieval", origin: "shared" as const },
];
const saved: DocumentResponse = { ...doc, state: "ready", subjects: [{ subject_id: "s-agents", name: "AI Agents" }] };

function setup(over: Partial<Parameters<typeof SubjectPicker>[0]> = {}) {
  const props = {
    document: doc,
    load: vi.fn(async () => suggestions),
    save: vi.fn(async () => saved),
    search: vi.fn(async (_query: string) => matches),
    onClose: vi.fn(),
    onSaved: vi.fn(),
    ...over,
  };
  render(<SubjectPicker {...props} />);
  return props;
}

const chip = (name: RegExp) => screen.findByRole("button", { name });
const input = () => screen.getByRole("combobox", { name: "Add your own" });

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
    const resolved: DocumentResponse = { ...saved, subjects: [{ subject_id: "s-agents", name: "AI Agents" }, { subject_id: "s-existing", name: "Tools" }] };
    const props = setup({ save: vi.fn(async () => resolved) });
    await userEvent.click(await chip(/Tool Use/));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(props.save).toHaveBeenCalledWith("d1", { subject_ids: ["s-agents"], new_names: ["Tool Use"] });
    expect(await screen.findByText("Subjects saved.")).toBeVisible();
    expect(screen.getByText("Tools")).toBeVisible(); // the server's name, not the suggestion's
    expect(screen.queryByText("Tool Use")).not.toBeInTheDocument();
    expect(screen.getByText("is ready to use.", { exact: false })).toHaveTextContent("Toolformer is ready to use.");
    expect(props.onSaved).toHaveBeenCalledTimes(1);
    expect(props.onSaved).toHaveBeenCalledWith(resolved);
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

  describe("in a step-through", () => {
    it("shows its place in a step-through", async () => {
      setup({ step: { index: 0, total: 3 }, onSkip: vi.fn() });
      await chip(/AI Agents/);
      expect(screen.getByText("Document 1 of 3")).toBeVisible();
      expect(screen.getByText("1 of 3")).toBeVisible();
      expect(screen.getByRole("button", { name: "Skip" })).toBeVisible();
      expect(screen.getByRole("button", { name: "Save and next" })).toBeVisible();
      expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    });

    it("says Save on the last step", async () => {
      setup({ step: { index: 2, total: 3 }, onSkip: vi.fn() });
      await chip(/AI Agents/);
      expect(screen.getByRole("button", { name: "Save" })).toBeVisible();
      expect(screen.queryByRole("button", { name: "Save and next" })).toBeNull();
    });

    it("calls onSaved without a saved screen in a step-through", async () => {
      const props = setup({ step: { index: 0, total: 3 }, onSkip: vi.fn() });
      await userEvent.click(await screen.findByRole("button", { name: "Save and next" }));
      await waitFor(() => expect(props.onSaved).toHaveBeenCalledWith(saved));
      expect(screen.queryByText("Subjects saved.")).toBeNull();
    });

    it("Skip calls onSkip", async () => {
      const props = setup({ step: { index: 0, total: 3 }, onSkip: vi.fn() });
      await userEvent.click(await screen.findByRole("button", { name: "Skip" }));
      expect(props.onSkip).toHaveBeenCalledTimes(1);
    });

    it("disables Skip while a save is pending", async () => {
      const save = vi.fn(() => new Promise<DocumentResponse>(() => {}));
      setup({ step: { index: 0, total: 3 }, onSkip: vi.fn(), save });
      await userEvent.click(await screen.findByRole("button", { name: "Save and next" }));
      expect(screen.getByRole("button", { name: "Skip" })).toBeDisabled();
    });

    it("stays on the document when a save fails in a step-through", async () => {
      const props = setup({ step: { index: 0, total: 3 }, onSkip: vi.fn(), save: vi.fn(async () => { throw new Error(""); }) });
      await userEvent.click(await screen.findByRole("button", { name: "Save and next" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save subjects");
      expect(props.onSaved).not.toHaveBeenCalled();
    });
  });

  it("shows only the generic message when the error has no server detail", async () => {
    setup({ save: vi.fn(async () => { throw new Error(""); }) });
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Couldn't save subjects. Try again.");
  });

  it("disables Save while saving", async () => {
    let finish!: (d: DocumentResponse) => void;
    const save = vi.fn(() => new Promise<DocumentResponse>((r) => (finish = r)));
    setup({ save });
    await chip(/AI Agents/);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
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

  it("searches the catalog as the learner types and adds a picked subject", async () => {
    const props = setup();
    await chip(/AI Agents/);
    await userEvent.type(input(), "retriev");
    const list = await screen.findByRole("listbox");
    const options = within(list).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      expect.stringContaining("Your subject"),
      expect.stringContaining("Shared subject"),
      expect.stringContaining('Create "retriev"'),
    ]);
    expect(props.search).toHaveBeenLastCalledWith("retriev");
    await userEvent.click(options[1]!);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(input()).toHaveValue("");
    expect(screen.getByRole("button", { name: /Information Retrieval/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("2 of 3 selected")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(props.save).toHaveBeenCalledWith("d1", { subject_ids: ["s-agents", "s-ir"], new_names: [] });
  });

  it("adds a typed name with Add and sends it as a new name", async () => {
    const props = setup({ search: vi.fn(async () => []) });
    await chip(/AI Agents/);
    await userEvent.type(input(), "  Tool Calling ");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByRole("button", { name: /Tool Calling/ })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(props.save).toHaveBeenCalledWith("d1", { subject_ids: ["s-agents"], new_names: ["Tool Calling"] });
  });

  it("selects an existing chip instead of adding a duplicate", async () => {
    setup({ search: vi.fn(async () => []) });
    await userEvent.click(await chip(/AI Agents/)); // deselect
    await userEvent.type(input(), "ai  AGENTS{Enter}");
    expect(screen.getAllByRole("button", { name: /AI Agents/ })).toHaveLength(1);
    expect(screen.getByRole("button", { name: /AI Agents/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("picks the active option with the keyboard and closes the list on Escape without closing the dialog", async () => {
    const props = setup();
    await chip(/AI Agents/);
    await userEvent.type(input(), "retriev");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(props.onClose).not.toHaveBeenCalled();
    await userEvent.keyboard("{ArrowDown}");
    await screen.findByRole("listbox");
    expect(input()).toHaveAttribute("aria-activedescendant", expect.stringMatching(/.+/));
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: /Retrieval-Augmented Generation/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("drops the highlighted option when the text changes, so Enter adds the typed name", async () => {
    setup();
    await chip(/AI Agents/);
    await userEvent.type(input(), "retriev");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{ArrowDown}");
    expect(input()).toHaveAttribute("aria-activedescendant", "picker-option-0");
    await userEvent.type(input(), " fusion");
    expect(input()).not.toHaveAttribute("aria-activedescendant");
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: /retriev fusion/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: /Retrieval-Augmented Generation/ })).not.toBeInTheDocument();
  });

  it("saves a typed name that wasn't added yet", async () => {
    const props = setup({ search: vi.fn(async () => []) });
    await chip(/AI Agents/);
    await userEvent.type(input(), "Tool Calling");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(props.save).toHaveBeenCalledWith("d1", { subject_ids: ["s-agents"], new_names: ["Tool Calling"] });
  });

  it("saves a typed catalog match by its id", async () => {
    const props = setup();
    await chip(/AI Agents/);
    await userEvent.type(input(), "information retrieval");
    await screen.findByRole("listbox");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(props.save).toHaveBeenCalledWith("d1", { subject_ids: ["s-agents", "s-ir"], new_names: [] });
  });

  it("doesn't send a typed name twice when it equals a selected chip", async () => {
    const props = setup({ search: vi.fn(async () => []) });
    await userEvent.click(await chip(/Tool Use/));
    await userEvent.type(input(), "tool  USE");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(props.save).toHaveBeenCalledWith("d1", { subject_ids: ["s-agents"], new_names: ["Tool Use"] });
  });

  it("blocks Save when typed text would be a fourth subject", async () => {
    const props = setup({ search: vi.fn(async () => []) });
    await chip(/AI Agents/);
    await userEvent.type(input(), "Tool Calling");
    await userEvent.click(screen.getByRole("button", { name: /LLMs/ }));
    await userEvent.click(screen.getByRole("button", { name: /Tool Use/ }));
    expect(input()).toBeDisabled();
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    expect(save).toHaveAccessibleDescription("You've chosen 3 subjects, the maximum. Remove one to add another.");
    await userEvent.click(save);
    expect(props.save).not.toHaveBeenCalled();
  });

  it("saves three chosen subjects with an empty field", async () => {
    const props = setup({ search: vi.fn(async () => []) });
    await userEvent.click(await chip(/LLMs/));
    await userEvent.click(screen.getByRole("button", { name: /Tool Use/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(props.save).toHaveBeenCalledWith("d1", { subject_ids: ["s-agents", "s-llm"], new_names: ["Tool Use"] });
  });

  it("doesn't reopen the list after the input loses focus", async () => {
    const props = setup();
    await chip(/AI Agents/);
    await userEvent.type(input(), "retriev");
    await userEvent.tab();
    await waitFor(() => expect(props.search).toHaveBeenCalledWith("retriev"));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("ignores a slower, older search response", async () => {
    let resolveOld: (m: typeof matches) => void = () => {};
    const search = vi.fn((q: string) =>
      q === "re" ? new Promise<typeof matches>((r) => { resolveOld = r; }) : Promise.resolve([matches[1]!]),
    );
    setup({ search });
    await chip(/AI Agents/);
    await userEvent.type(input(), "re");
    await waitFor(() => expect(search).toHaveBeenCalledWith("re"));
    await userEvent.type(input(), "triev");
    await screen.findByRole("option", { name: /Information Retrieval/ });
    resolveOld(matches);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole("option", { name: /Retrieval-Augmented/ })).not.toBeInTheDocument();
  });

  it("blocks a name over 60 characters with a counter and an error", async () => {
    const props = setup();
    await chip(/AI Agents/);
    await userEvent.type(input(), "x".repeat(61));
    expect(screen.getByText("61/60")).toBeVisible();
    expect(input()).toHaveAttribute("aria-invalid", "true");
    expect(input()).toHaveAccessibleDescription(expect.stringContaining("Subject names can be up to 60 characters."));
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(props.search).not.toHaveBeenCalledWith("x".repeat(61));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("shows the counter and the visibility hint", async () => {
    setup();
    await chip(/AI Agents/);
    await userEvent.type(input(), "retriev");
    expect(screen.getByText("7/60")).toBeVisible();
    expect(screen.getByText("Subject names are visible to everyone. Don't include personal information.")).toBeVisible();
  });

  it("cannot add a fourth subject", async () => {
    setup({ search: vi.fn(async () => []) });
    await userEvent.click(await chip(/LLMs/));
    await userEvent.click(await chip(/Tool Use/));
    expect(input()).toBeDisabled();
  });
});
