import { render, screen } from "@testing-library/react";
import { Archive } from "lucide-react";
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

  it("renders the given icon instead of the variant's", () => {
    const { container } = render(<Banner variant="info" icon={Archive} title="t" />);
    expect(container.querySelector("svg")).toHaveClass("lucide-archive");
  });

  it("renders the neutral variant", () => {
    const { container } = render(<Banner variant="neutral" title="Archived" />);
    expect(screen.getByText("Archived")).toBeVisible();
    expect((container.firstChild as HTMLElement).className).toMatch(/neutral/);
    expect(container.querySelector("svg")).toHaveClass("lucide-info");
  });
});
