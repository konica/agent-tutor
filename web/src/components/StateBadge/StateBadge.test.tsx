import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StateBadge, type DocumentState } from "./StateBadge";

describe("StateBadge", () => {
  it.each<[DocumentState, string]>([
    ["uploading", "Uploading"],
    ["processing", "Processing"],
    ["awaiting_subjects", "Choose subjects"],
    ["ready", "Ready"],
    ["failed", "Failed"],
    ["archived", "Archived"],
  ])("shows a text label for every state (%s)", (state, label) => {
    render(<StateBadge state={state} />);
    expect(screen.getByText(label)).toBeVisible();
  });
});
