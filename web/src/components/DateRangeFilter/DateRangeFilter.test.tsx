import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import styles from "./DateRangeFilter.module.css";
import { DateRangeFilter } from "./DateRangeFilter";

function setup(props: { from?: string; to?: string } = {}) {
  const onChange = vi.fn();
  render(<DateRangeFilter label="Uploaded" groupLabel="Upload dates" onChange={onChange} {...props} />);
  return { onChange };
}

const open = () => userEvent.click(screen.getByRole("button", { name: /^Uploaded/ }));

describe("DateRangeFilter", () => {
  it("opens a From/To group with focus on From", async () => {
    setup();
    await open();
    expect(screen.getByRole("group", { name: "Upload dates" })).toBeVisible();
    expect(screen.getByLabelText("From")).toHaveFocus();
    expect(screen.getByLabelText("To")).toBeVisible();
  });

  it("closes on Escape and returns focus to the button", async () => {
    setup();
    await open();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("group", { name: "Upload dates" })).toBeNull();
    expect(screen.getByRole("button", { name: "Uploaded" })).toHaveFocus();
  });

  it("closes when focus leaves it", async () => {
    setup();
    await open();
    await userEvent.tab({ shift: true });
    await userEvent.tab({ shift: true });
    expect(screen.queryByRole("group", { name: "Upload dates" })).toBeNull();
  });

  it("names the range on the button and marks it active", () => {
    setup({ from: "2026-09-01" });
    expect(screen.getByRole("button", { name: "Uploaded: from 2026-09-01" })).toHaveClass(styles.on);
  });

  it("is not marked active without a range", () => {
    setup();
    expect(screen.getByRole("button", { name: "Uploaded" })).not.toHaveClass(styles.on);
  });

  it("reports only the changed key", async () => {
    const { onChange } = setup();
    await open();
    await userEvent.type(screen.getByLabelText("From"), "2026-10-01");
    expect(onChange).toHaveBeenLastCalledWith({ from: "2026-10-01" });
  });

  it("shows any label and group name it is given", async () => {
    const onChange = vi.fn();
    render(<DateRangeFilter label="Date" groupLabel="Last activity" from="2026-10-01" onChange={onChange} />);
    const button = screen.getByRole("button", { name: "Date: from 2026-10-01" });
    expect(button).toHaveTextContent("Date");
    await userEvent.click(button);
    expect(screen.getByRole("group", { name: "Last activity" })).toBeVisible();
    await userEvent.type(screen.getByLabelText("To"), "2026-10-05");
    expect(onChange).toHaveBeenLastCalledWith({ to: "2026-10-05" });
  });
});
