import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type AuthClient, SessionExpiredError, sessionExpiry } from "./authClient";
import { SessionProvider, useSession } from "./SessionProvider";

function fakeAuth(): AuthClient {
  return {
    init: vi.fn(async () => {}),
    getToken: vi.fn(async () => "t"),
    signIn: vi.fn(async () => {}),
    signOut: vi.fn(async () => {}),
  };
}

function Who() {
  const { name, signOut } = useSession();
  return (
    <button type="button" onClick={signOut}>
      {name}
    </button>
  );
}

function renderSession(auth: AuthClient, loadMe: () => Promise<{ name: string }>) {
  render(
    <SessionProvider auth={auth} loadMe={loadMe}>
      <Who />
    </SessionProvider>,
  );
}

describe("SessionProvider", () => {
  it("signs in, loads the learner, and shows the app", async () => {
    const auth = fakeAuth();
    renderSession(auth, async () => ({ name: "Ada Lovelace" }));
    expect(screen.getByRole("status")).toHaveTextContent("Signing you in");
    expect(await screen.findByRole("button", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(auth.init).toHaveBeenCalled();
  });

  it("signs out through the auth client", async () => {
    const auth = fakeAuth();
    renderSession(auth, async () => ({ name: "Ada Lovelace" }));
    await userEvent.click(await screen.findByRole("button", { name: "Ada Lovelace" }));
    expect(auth.signOut).toHaveBeenCalledOnce();
  });

  it("asks to sign in again when the API says 401", async () => {
    const auth = fakeAuth();
    renderSession(auth, () => Promise.reject(new SessionExpiredError()));
    expect(await screen.findByRole("heading", { name: "Please sign in again" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(auth.signIn).toHaveBeenCalledOnce();
  });

  it("asks to sign in again when a later call ends the session", async () => {
    renderSession(fakeAuth(), async () => ({ name: "Ada Lovelace" }));
    await screen.findByRole("button", { name: "Ada Lovelace" });
    act(() => sessionExpiry.notify());
    expect(screen.getByRole("heading", { name: "Please sign in again" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ada Lovelace" })).not.toBeInTheDocument();
  });

  it("offers a retry when the API can't be reached", async () => {
    const loadMe = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValue({ name: "Ada Lovelace" });
    renderSession(fakeAuth(), loadMe);
    expect(await screen.findByRole("heading", { name: "Can't reach Smart Tutor" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("button", { name: "Ada Lovelace" })).toBeInTheDocument();
  });
});
