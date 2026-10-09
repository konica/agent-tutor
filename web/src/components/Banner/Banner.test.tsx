import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Banner } from "./Banner";

describe("Banner", () => {
  it("renders an inline one-row banner", () => {
    const { container } = render(
      <Banner variant="info" inline>
        Two documents are processing.
      </Banner>,
    );
    expect(screen.getByText("Two documents are processing.")).toBeVisible();
    expect((container.firstChild as HTMLElement).className).toMatch(/inline/);
  });

  it("renders the title", () => {
    render(
      <Banner variant="success" title="Saved">
        Ready
      </Banner>,
    );
    expect(screen.getByText("Saved")).toBeVisible();
  });
});
