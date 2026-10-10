import { act, render, screen, within } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { loadConversation } from "../api/chat";
import { loadDocuments } from "../api/documents";
import type { DocumentResponse } from "../api/generated/types.gen";
import { SessionContext, SessionProvider } from "../auth/SessionProvider";
import type { AuthClient } from "../auth/authClient";
import { NAV } from "./nav";
import { createRoutes } from "./routes";

// The Library loads documents from the API; these tests are about routing, so it sees an empty library.
vi.mock("../api/documents", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/documents")>()),
  loadDocuments: vi.fn(async (): Promise<DocumentResponse[]> => []),
  loadUploadLimits: async () => ({ max_bytes: 52_428_800, max_pages: 500 }),
  uploadPdf: vi.fn(),
}));

// A conversation's URL loads it from the API; these tests are about routing, so it is an empty conversation.
vi.mock("../api/chat", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/chat")>()),
  loadConversation: vi.fn(async (threadId: string) => ({
    thread: { thread_id: threadId, title: "Attention basics", search_scope: "library" as const },
    turns: [],
  })),
  loadDocumentsUsed: vi.fn(async () => []),
}));

const signOut = vi.fn();

function fakeAuth(): AuthClient {
  return {
    init: vi.fn(async () => {}),
    getToken: vi.fn(async () => "t"),
    signIn: vi.fn(async () => {}),
    signOut: vi.fn(async () => {}),
  };
}

// Most tests are about the shell, so the guard hands it a signed-in learner straight away.
function SignedIn({ children }: { children: ReactNode }) {
  return <SessionContext.Provider value={{ name: "Ada Lovelace", signOut }}>{children}</SessionContext.Provider>;
}

function renderAt(path: string, { strict = false, auth = fakeAuth(), RequireSession = SignedIn } = {}) {
  const router = createMemoryRouter(createRoutes({ auth, RequireSession }), { initialEntries: [path] });
  const app = <RouterProvider router={router} />;
  render(strict ? <StrictMode>{app}</StrictMode> : app);
  return router;
}

// The real guard: SessionProvider over a fake Keycloak.
function guardedBy(auth: AuthClient) {
  return function RequireSession({ children }: { children: ReactNode }) {
    return (
      <SessionProvider auth={auth} loadMe={async () => ({ name: "Ada Lovelace" })}>
        {children}
      </SessionProvider>
    );
  };
}

const nav = () => within(screen.getByRole("navigation", { name: "Main" }));

describe("public landing page", () => {
  it("shows the landing page at /, outside the app shell", () => {
    const router = renderAt("/");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Ask your own documents.");
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
  });

  it("does not sign in on / (no request to Keycloak), even in StrictMode", async () => {
    const auth = fakeAuth();
    renderAt("/", { auth, RequireSession: guardedBy(auth), strict: true });
    expect((await screen.findAllByRole("button", { name: "Create an account" }))[0]).toBeInTheDocument();
    expect(auth.init).not.toHaveBeenCalled();
    expect(auth.signIn).not.toHaveBeenCalled();
  });

  it("opens Keycloak registration from the landing page, returning to the Library", async () => {
    const auth = fakeAuth();
    renderAt("/", { auth });
    await userEvent.click(screen.getAllByRole("button", { name: "Create an account" })[0]!);
    expect(auth.signIn).toHaveBeenCalledWith({ register: true, redirectTo: "/library" });
  });

  it.each(["/library", "/chat", "/notes", "/nope"])("signs in before showing %s", async (path) => {
    const auth = fakeAuth();
    renderAt(path, { auth, RequireSession: guardedBy(auth) });
    expect(screen.getByRole("status")).toHaveTextContent("Signing you in");
    expect(await screen.findByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(auth.init).toHaveBeenCalled();
  });

  it("returns to the landing page on sign-out", async () => {
    // keycloakClient signs out to origin + "/" (keycloakClient.test.ts); / must then render the landing page signed out.
    const auth = fakeAuth();
    renderAt("/library", { auth, RequireSession: guardedBy(auth) });
    const menu = within(await screen.findByRole("navigation", { name: "Main" }));
    await userEvent.click(menu.getByRole("button", { name: /Ada Lovelace/ }));
    await userEvent.click(menu.getByRole("button", { name: "Sign out" }));
    expect(auth.signOut).toHaveBeenCalledOnce();
  });
});

describe("app shell routes", () => {
  it("lists the Release 1 nav items in brief order", () => {
    renderAt("/library");
    const labels = nav().getAllByRole("link").map((a) => a.getAttribute("aria-label") ?? a.textContent?.trim());
    expect(labels).toEqual(["Smart Tutor, Library", "Library", "Chat", "Conversations", "Notes", "Subjects", "Usage"]);
  });

  it("nav items are links", () => {
    renderAt("/library");
    for (const item of NAV) {
      expect(nav().getByRole("link", { name: item.label })).toHaveAttribute("href", item.path);
    }
  });

  // <Navigate> redirects in an effect, so wait for the Library before reading the location.
  it("redirects unknown paths to the Library", async () => {
    const router = renderAt("/nope");
    expect(await screen.findByRole("heading", { level: 1, name: "Library" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/library");
  });

  it("renders the requested page on a deep link", () => {
    renderAt("/notes");
    expect(screen.getByRole("heading", { level: 1, name: "Notes" })).toBeInTheDocument();
    expect(nav().getByRole("link", { name: "Notes" })).toHaveAttribute("aria-current", "page");
    expect(nav().getByRole("link", { name: "Library" })).not.toHaveAttribute("aria-current");
  });

  it("renders the Chat page with a question box", async () => {
    // The Chat page offers the question box only when the learner has a ready document.
    vi.mocked(loadDocuments).mockResolvedValueOnce([{ state: "ready" } as DocumentResponse]);
    renderAt("/chat");
    expect(await screen.findByRole("textbox", { name: "Your question" })).toBeEnabled();
    expect(screen.getByRole("heading", { level: 1, name: "New conversation" })).toBeInTheDocument();
  });

  it("opens a conversation at its URL in the Chat page", async () => {
    vi.mocked(loadDocuments).mockResolvedValueOnce([{ state: "ready" } as DocumentResponse]);
    renderAt("/chat/t1");
    expect(await screen.findByRole("textbox", { name: "Your question" })).toBeEnabled();
    expect(await screen.findByRole("button", { name: "Attention basics. Edit title" })).toBeInTheDocument();
    expect(loadConversation).toHaveBeenCalledWith("t1");
    expect(nav().getByRole("link", { name: "Chat" })).toHaveAttribute("aria-current", "page");
  });

  it("shows the needs-subjects badge on Library from any page", async () => {
    vi.mocked(loadDocuments).mockImplementation(async (filters) => (filters?.state === "awaiting_subjects" ? [{ state: "awaiting_subjects" } as DocumentResponse] : []));
    try {
      renderAt("/chat");
      expect(await nav().findByRole("link", { name: "Library, 1 needs subjects" })).toBeVisible();
    } finally {
      vi.mocked(loadDocuments).mockImplementation(async () => []);
    }
  });

  it("moves to a page and marks it current when a nav item is clicked", async () => {
    renderAt("/library");
    await userEvent.click(nav().getByRole("link", { name: "Usage" }));
    expect(screen.getByRole("heading", { level: 1, name: "Usage" })).toBeInTheDocument();
    expect(nav().getByRole("link", { name: "Usage" })).toHaveAttribute("aria-current", "page");
  });

  it("shows the first-run Library", async () => {
    renderAt("/library");
    expect(await screen.findByRole("heading", { level: 2, name: "Upload your first document" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose PDFs" })).toBeEnabled();
  });

  it("sets the document title from the current page", async () => {
    renderAt("/library");
    expect(document.title).toBe("Library · Smart Tutor");
    await userEvent.click(nav().getByRole("link", { name: "Notes" }));
    expect(document.title).toBe("Notes · Smart Tutor");
  });

  it("shows the learner's name and signs out from the user menu", async () => {
    renderAt("/library");
    await userEvent.click(nav().getByRole("button", { name: /Ada Lovelace/ }));
    await userEvent.click(nav().getByRole("button", { name: "Sign out" }));
    expect(signOut).toHaveBeenCalledOnce();
  });

  it("moves focus to the main region after navigating", async () => {
    renderAt("/library");
    await userEvent.click(nav().getByRole("link", { name: "Usage" }));
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("moves focus to the main region on browser Back", async () => {
    const router = renderAt("/library");
    await userEvent.click(nav().getByRole("link", { name: "Usage" }));
    (document.activeElement as HTMLElement).blur();
    await act(() => router.navigate(-1));
    expect(screen.getByRole("heading", { level: 1, name: "Library" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("leaves focus alone when an unknown path redirects to the Library", async () => {
    renderAt("/nope");
    await screen.findByRole("heading", { level: 1, name: "Library" });
    expect(screen.getByRole("main")).not.toHaveFocus();
  });

  it("leaves focus alone on first load in StrictMode", async () => {
    renderAt("/library", { strict: true });
    await screen.findByRole("heading", { level: 1, name: "Library" });
    expect(screen.getByRole("main")).not.toHaveFocus();
  });
});

describe("collapsible nav", () => {
  afterEach(() => localStorage.clear());

  it("collapses to the rail from the keyboard and remembers it", async () => {
    renderAt("/library");
    const toggle = nav().getByRole("button", { name: "Collapse navigation" });
    for (let i = 0; i < 30 && document.activeElement !== toggle; i += 1) await userEvent.tab();
    expect(toggle).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(nav().getByRole("button", { name: "Expand navigation" })).toBeInTheDocument();
    expect(localStorage.getItem("smart-tutor.nav-collapsed")).toBe("1");
  });
});
