import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LandingPage } from "./LandingPage";

function renderLanding() {
  const signIn = vi.fn(async () => {});
  render(<LandingPage signIn={signIn} />);
  return signIn;
}

describe("LandingPage", () => {
  it("shows the brief §9 copy", () => {
    renderLanding();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Ask your own documents. Get answers you can check.");
    expect(screen.getByText("Upload your PDFs. Smart Tutor answers only from them and shows the title and page for every answer.")).toBeInTheDocument();
    expect(screen.getByText("Pilot · laptop browsers only.")).toBeInTheDocument();

    const steps = within(screen.getByRole("list", { name: "How it works" })).getAllByRole("listitem");
    expect(steps.map((li) => li.textContent)).toEqual(["01Upload your PDFs", "02Ask a question", "03Check the page it came from"]);

    const trust = within(screen.getByRole("list", { name: "What you can rely on" })).getAllByRole("listitem");
    expect(trust.map((li) => li.textContent)).toEqual([
      "Only your documents: the tutor never answers from anything else.",
      "Private to you: no one else sees your documents, conversations, or notes.",
      "Every answer cites the document title and page.",
      "A pilot for laptop browsers.",
    ]);
    expect(screen.getByRole("heading", { level: 2, name: "Ask your own documents." })).toBeInTheDocument();
  });

  it("has no terms of use link and no image", () => {
    renderLanding();
    expect(screen.queryByRole("link", { name: /terms/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("opens Keycloak registration from both Create an account buttons, returning to the Library", async () => {
    const signIn = renderLanding();
    const buttons = screen.getAllByRole("button", { name: "Create an account" });
    expect(buttons).toHaveLength(2);
    for (const button of buttons) await userEvent.click(button);
    expect(signIn).toHaveBeenCalledTimes(2);
    expect(signIn).toHaveBeenNthCalledWith(1, { register: true, redirectTo: "/library" });
    expect(signIn).toHaveBeenNthCalledWith(2, { register: true, redirectTo: "/library" });
  });

  it("opens Keycloak login from the header, hero, and closing Sign in, returning to the Library", async () => {
    const signIn = renderLanding();
    const buttons = screen.getAllByRole("button", { name: "Sign in" });
    expect(buttons).toHaveLength(3);
    for (const button of buttons) await userEvent.click(button);
    expect(signIn).toHaveBeenCalledTimes(3);
    for (const call of signIn.mock.calls) expect(call).toEqual([{ redirectTo: "/library" }]);
  });

  it("does not open Keycloak until a button is chosen", () => {
    expect(renderLanding()).not.toHaveBeenCalled();
  });

  it("reaches every button by keyboard in reading order", async () => {
    renderLanding();
    const names: string[] = [];
    for (let i = 0; i < 5; i++) {
      await userEvent.tab();
      names.push(document.activeElement?.textContent ?? "");
    }
    expect(names).toEqual(["Sign in", "Create an account", "Sign in", "Create an account", "Sign in"]);
  });

  it("titles the page Smart Tutor", () => {
    document.title = "Library · Smart Tutor";
    renderLanding();
    expect(document.title).toBe("Smart Tutor");
  });
});
