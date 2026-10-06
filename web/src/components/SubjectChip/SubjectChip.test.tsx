import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SubjectChip, subjectHue } from "./SubjectChip";

describe("SubjectChip", () => {
  it("renders a plain chip with the name", () => {
    render(<SubjectChip name="LLMs" hueKey="s1" />);
    expect(screen.getByText("LLMs")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the origin after the name", () => {
    render(<SubjectChip name="LLMs" hueKey="s1" origin="Your subject" onToggle={() => {}} />);
    expect(screen.getByRole("button")).toHaveTextContent("LLMs· Your subject");
  });

  it("is a toggle button with aria-pressed that calls onToggle", () => {
    const onToggle = vi.fn();
    render(<SubjectChip name="LLMs" hueKey="s1" pressed onToggle={onToggle} />);
    const button = screen.getByRole("button", { name: /LLMs/ });
    expect(button).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("does not call onToggle when disabled", () => {
    const onToggle = vi.fn();
    render(<SubjectChip name="LLMs" hueKey="s1" disabled onToggle={onToggle} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("gives the same hue to the same key and always a known hue", () => {
    expect(subjectHue("abc")).toBe(subjectHue("abc"));
    expect(["llm", "agents", "rag", "rl", "tool", "other"]).toContain(subjectHue("zzz"));
  });
});
