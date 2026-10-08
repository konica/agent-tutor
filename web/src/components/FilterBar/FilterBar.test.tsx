import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilterBar, FilterField } from "./FilterBar";

function setup(props: { count?: number | null; active?: boolean } = {}) {
  const onClear = vi.fn();
  render(
    <FilterBar label="Filter notes" noun="note" count={props.count === undefined ? 2 : props.count} active={props.active ?? false} onClear={onClear}>
      <FilterField id="f-topic" label="Topic">
        <select id="f-topic" />
      </FilterField>
    </FilterBar>,
  );
  return { onClear };
}

describe("FilterBar", () => {
  it("is a labelled search landmark holding its labelled fields", () => {
    setup();
    expect(screen.getByRole("search", { name: "Filter notes" })).toBeVisible();
    expect(screen.getByLabelText("Topic")).toBeVisible();
  });

  it("counts results with the noun, singular for one", () => {
    setup({ count: 1 });
    expect(screen.getByText("1 note")).toBeVisible();
  });

  it("pluralizes the noun", () => {
    setup({ count: 3 });
    expect(screen.getByText("3 notes")).toBeVisible();
  });

  it("shows Clear filters only while active and calls onClear", async () => {
    const { onClear } = setup({ active: true });
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(onClear).toHaveBeenCalled();
  });

  it("hides Clear filters when nothing is filtered", () => {
    setup();
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
  });
});
