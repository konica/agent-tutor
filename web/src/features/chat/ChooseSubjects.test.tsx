import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChooseSubjects } from "./ChooseSubjects";

const SUBJECTS = [
  { subject_id: "s1", name: "LLMs" },
  { subject_id: "s2", name: "AI Agents" },
  { subject_id: "s3", name: "Retrieval-Augmented Generation" },
  { subject_id: "s4", name: "Reinforcement Learning" },
];

function renderPicker(props: Partial<{ busy: boolean; onContinue: (ids: string[]) => void }> = {}) {
  const onContinue = props.onContinue ?? vi.fn();
  render(<ChooseSubjects subjects={SUBJECTS} busy={props.busy ?? false} onContinue={onContinue} />);
  return { onContinue };
}
const group = () => screen.getByRole("group", { name: "Which subjects is this about?" });
const chip = (name: string) => within(group()).getByRole("button", { name });
const continueButton = () => screen.getByRole("button", { name: "Continue" });

describe("ChooseSubjects", () => {
  it("offers one toggle per subject under the question and the hint, with Continue disabled", () => {
    renderPicker();
    expect(screen.getByText("Smart Tutor")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Which subjects is this about?" })).toBeInTheDocument();
    expect(group()).toHaveAccessibleDescription("Pick 1 to 3. I'll answer your question right after.");
    const toggles = within(group()).getAllByRole("button");
    expect(toggles.map((b) => b.textContent)).toEqual(SUBJECTS.map((s) => s.name));
    for (const toggle of toggles) expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(continueButton()).toBeDisabled();
  });

  it("enables Continue after one pick and allows at most three", async () => {
    renderPicker();
    await userEvent.click(chip("LLMs"));
    expect(chip("LLMs")).toHaveAttribute("aria-pressed", "true");
    expect(continueButton()).toBeEnabled();

    await userEvent.click(chip("AI Agents"));
    await userEvent.click(chip("Retrieval-Augmented Generation"));
    expect(chip("Reinforcement Learning")).toBeDisabled();
    expect(chip("LLMs")).toBeEnabled();

    await userEvent.click(chip("AI Agents"));
    expect(chip("AI Agents")).toHaveAttribute("aria-pressed", "false");
    expect(chip("Reinforcement Learning")).toBeEnabled();
  });

  it("works from the keyboard and continues with the ids in the order they were picked", async () => {
    const { onContinue } = renderPicker();
    await userEvent.tab();
    expect(chip("LLMs")).toHaveFocus();
    await userEvent.tab();
    await userEvent.keyboard("{Enter}"); // AI Agents
    await userEvent.tab({ shift: true });
    await userEvent.keyboard(" "); // LLMs
    expect(chip("AI Agents")).toHaveAttribute("aria-pressed", "true");
    expect(chip("LLMs")).toHaveAttribute("aria-pressed", "true");
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();
    expect(continueButton()).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(onContinue).toHaveBeenCalledWith(["s2", "s1"]);
  });

  it("disables every control while busy", async () => {
    renderPicker({ busy: true });
    for (const toggle of within(group()).getAllByRole("button")) expect(toggle).toBeDisabled();
    expect(continueButton()).toBeDisabled();
  });
});
