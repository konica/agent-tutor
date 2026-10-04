import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StateBadge, type DocumentState } from "./StateBadge";

describe("StateBadge", () => {
  it.each<[DocumentState, string]>([
    ["processing", "Processing"],
    ["ready", "Ready"],
    ["failed", "Failed"],
  ])("shows a text label for every state (%s)", (state, label) => {
    render(<StateBadge state={state} />);
    expect(screen.getByText(label)).toBeVisible();
  });
});
