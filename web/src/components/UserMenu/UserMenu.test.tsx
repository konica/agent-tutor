import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { UserMenu } from "./UserMenu";

describe("UserMenu", () => {
  it("shows the name and initials", () => {
    render(<UserMenu name="Ada Lovelace" />);
    expect(screen.getByRole("button", { name: /Ada Lovelace/ })).toHaveTextContent("AL");
  });

  it("on the rail keeps the name as the accessible name and tooltip", () => {
    render(<UserMenu name="Ada Lovelace" compact />);
    const toggle = screen.getByRole("button", { name: "Ada Lovelace" });
    expect(toggle).toHaveAttribute("data-tip", "Ada Lovelace");
  });

  it("opens and closes the menu", async () => {
    render(<UserMenu name="Ada Lovelace" onSignOut={() => {}} />);
    const toggle = screen.getByRole("button", { name: /Ada Lovelace/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeVisible();
    await userEvent.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("moves focus to Sign out when the menu opens", async () => {
    render(<UserMenu name="Ada Lovelace" onSignOut={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /Ada Lovelace/ }));
    expect(screen.getByRole("button", { name: "Sign out" })).toHaveFocus();
  });

  it("closes on Escape and returns focus to the toggle", async () => {
    render(<UserMenu name="Ada Lovelace" onSignOut={() => {}} />);
    const toggle = screen.getByRole("button", { name: /Ada Lovelace/ });
    await userEvent.click(toggle);
    await userEvent.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
  });

  it("closes when focus leaves the menu", async () => {
    render(
      <>
        <UserMenu name="Ada Lovelace" onSignOut={() => {}} />
        <button type="button">Outside</button>
      </>,
    );
    const toggle = screen.getByRole("button", { name: /Ada Lovelace/ });
    await userEvent.click(toggle);
    await userEvent.tab(); // Sign out -> toggle
    await userEvent.tab(); // toggle -> Outside
    expect(screen.getByRole("button", { name: "Outside" })).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("calls onSignOut", async () => {
    const onSignOut = vi.fn();
    render(<UserMenu name="Ada Lovelace" onSignOut={onSignOut} />);
    await userEvent.click(screen.getByRole("button", { name: /Ada Lovelace/ }));
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(onSignOut).toHaveBeenCalledOnce();
  });

  it("offers no Sign out until one is wired", async () => {
    render(<UserMenu name="Learner" />);
    await userEvent.click(screen.getByRole("button", { name: /Learner/ }));
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });
});
