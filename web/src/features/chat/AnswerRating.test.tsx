import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnswerRating } from "./AnswerRating";

const helpful = () => screen.getByRole("button", { name: "Helpful" });
const notHelpful = () => screen.getByRole("button", { name: "Not helpful" });
const FAILED = "Your rating couldn't be saved. Try again.";

describe("AnswerRating", () => {
  it("offers Helpful and Not helpful, neither pressed before a rating", () => {
    render(<AnswerRating rating={null} onRate={async () => {}} />);
    expect(helpful()).toHaveAttribute("aria-pressed", "false");
    expect(notHelpful()).toHaveAttribute("aria-pressed", "false");
  });

  it("shows a saved up rating pressed with a thanks", () => {
    render(<AnswerRating rating="up" onRate={async () => {}} />);
    expect(helpful()).toHaveAttribute("aria-pressed", "true");
    expect(notHelpful()).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("status")).toHaveTextContent("Thanks — glad it helped.");
  });

  it("shows a saved down rating pressed with a thanks", () => {
    render(<AnswerRating rating="down" onRate={async () => {}} />);
    expect(notHelpful()).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Thanks — your feedback helps improve answers.");
  });

  it("presses the button at once while the rating is being saved", async () => {
    const onRate = vi.fn(() => new Promise<void>(() => {}));
    render(<AnswerRating rating={null} onRate={onRate} />);

    await userEvent.click(notHelpful());

    expect(onRate).toHaveBeenCalledWith("down");
    expect(notHelpful()).toHaveAttribute("aria-pressed", "true");
  });

  it("goes back to the saved rating and says so when saving fails; a later success clears it", async () => {
    const onRate = vi.fn().mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(undefined);
    render(<AnswerRating rating="up" onRate={onRate} />);

    await userEvent.click(notHelpful());
    expect(await screen.findByText(FAILED)).toBeInTheDocument();
    expect(helpful()).toHaveAttribute("aria-pressed", "true");
    expect(notHelpful()).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(notHelpful());
    expect(screen.queryByText(FAILED)).not.toBeInTheDocument();
  });

  it("does nothing when the pressed button is clicked again", async () => {
    const onRate = vi.fn(async () => {});
    render(<AnswerRating rating="up" onRate={onRate} />);

    await userEvent.click(helpful());

    expect(onRate).not.toHaveBeenCalled();
  });
});
