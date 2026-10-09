import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("puts the count, the info button and the actions on the title's row", () => {
    render(<PageHeader title="Library" count="8 documents" description="Your documents." actions={<button type="button">Upload</button>} />);
    expect(screen.getByRole("heading", { level: 1, name: "Library" })).toBeVisible();
    expect(screen.getByText("8 documents")).toBeVisible();
    const info = screen.getByRole("button", { name: "About Library" });
    expect(info).toHaveAttribute("data-tip", "Your documents.");
    expect(info).toHaveAccessibleDescription("Your documents.");
    expect(screen.getByRole("button", { name: "Upload" })).toBeVisible();
  });

  it("keeps a long title on one line with the full text on hover", () => {
    const long = "How does ReAct combine reasoning and acting when the observation contradicts the plan?";
    render(<PageHeader title={long} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveAttribute("title", long);
  });

  it("shows no info button without a description", () => {
    render(<PageHeader title="Chat" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
