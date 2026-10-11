import { act, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import type { Rating } from "../../api/chat";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnswerRating } from "./AnswerRating";

const helpful = () => screen.getByRole("button", { name: "Helpful" });
const notHelpful = () => screen.getByRole("button", { name: "Not helpful" });
// Stands in for the page: it keeps the rating a save returns, but only for the newest request, as ChatPage does.
function Page({ save }: { save: (rating: Rating) => Promise<void> }) {
  const [rating, setRating] = useState<Rating | null>(null);
  const requests = useRef(0);
  return (
    <AnswerRating
      rating={rating}
      onRate={async (next) => {
        const request = ++requests.current;
        await save(next);
        if (request === requests.current) setRating(next);
      }}
    />
  );
}
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
    expect(screen.getByText("Thanks — glad it helped.")).toBeInTheDocument();
  });

  it("shows a saved down rating pressed with a thanks", () => {
    render(<AnswerRating rating="down" onRate={async () => {}} />);
    expect(notHelpful()).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Thanks — your feedback helps improve answers.")).toBeInTheDocument();
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

  it("keeps the note out of the live regions and reports the outcome to onAnnounce", async () => {
    const onAnnounce = vi.fn();
    render(<AnswerRating rating={null} onRate={async () => {}} onAnnounce={onAnnounce} />);

    await userEvent.click(helpful());

    expect(onAnnounce).toHaveBeenCalledWith("Thanks — glad it helped.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("announces the failure", async () => {
    const onAnnounce = vi.fn();
    render(<AnswerRating rating={null} onRate={async () => Promise.reject(new Error("boom"))} onAnnounce={onAnnounce} />);

    await userEvent.click(helpful());

    expect(await screen.findByText(FAILED)).toBeInTheDocument();
    expect(onAnnounce).toHaveBeenCalledWith(FAILED);
  });

  it("shows no failure and keeps the second rating when the first click fails after the second succeeded", async () => {
    let failFirst: (e: Error) => void = () => {};
    const onRate = vi
      .fn()
      .mockImplementationOnce(() => new Promise<void>((_, reject) => (failFirst = reject)))
      .mockResolvedValueOnce(undefined);
    const onAnnounce = vi.fn();
    render(<AnswerRating rating={null} onRate={onRate} onAnnounce={onAnnounce} />);

    await userEvent.click(helpful());
    await userEvent.click(notHelpful());
    await act(async () => failFirst(new Error("late")));

    expect(screen.queryByText(FAILED)).not.toBeInTheDocument();
    expect(onAnnounce).toHaveBeenCalledTimes(1);
    expect(onAnnounce).toHaveBeenCalledWith("Thanks — your feedback helps improve answers.");
  });

  it("keeps Not helpful pressed when the replies arrive out of order", async () => {
    const replies: (() => void)[] = [];
    const onRate = vi.fn(() => new Promise<void>((resolve) => replies.push(resolve)));
    render(<Page save={onRate} />);

    await userEvent.click(helpful());
    await userEvent.click(notHelpful());
    await act(async () => replies[1]!());
    await act(async () => replies[0]!());

    expect(notHelpful()).toHaveAttribute("aria-pressed", "true");
    expect(helpful()).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Thanks — your feedback helps improve answers.")).toBeInTheDocument();
  });
});
