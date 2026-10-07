# Public Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public landing page at `/` that explains Smart Tutor and leads to Keycloak sign-up and sign-in, while every app route still requires sign-in (issue #102).

**Architecture:** The sign-in requirement moves from `main.tsx` (which wraps the whole app in `SessionProvider`) into the router: a pathless layout route wraps `AppShell` in a session guard, and `/` renders `LandingPage` outside it. Routes become a factory, `createRoutes({ auth, RequireSession })`, so tests inject a fake guard and fake auth. `AuthClient.signIn` gains options (`register`, `redirectTo`) and initialises keycloak-js lazily without `onLoad`, which makes no network request, so the landing page touches Keycloak only when a button is chosen.

**Tech Stack:** React 19, react-router 8 (`createBrowserRouter`, `RouteObject`), keycloak-js 26, CSS modules with tokens from `web/src/styles/tokens.css`, Vitest + Testing Library.

**Spec:** Issue #102; PRD v2.19 §8 US-1 (first criterion) and Q46; design brief §6.0 and §9 at tag `design-v0.7`; prototype `sdd/design/prototype/js/landing.js` and `v03.css` (`.landing`, `.ld-*`) at `design-v0.7`; `DESIGN.md`.

## Global Constraints

- Copy is verbatim from brief §9:
  - Headline: "Ask your own documents. Get answers you can check." (two lines; the second in `--accent-text`)
  - Sub-line: "Upload your PDFs. Smart Tutor answers only from them and shows the title and page for every answer."
  - Buttons: "Create an account" (primary), "Sign in" (secondary). Below them: "Pilot · laptop browsers only."
  - How it works (kicker "How it works"): "Upload your PDFs" · "Ask a question" · "Check the page it came from".
  - Trust points: "**Only your documents:** the tutor never answers from anything else." · "**Private to you:** no one else sees your documents, conversations, or notes." · "Every answer cites the document title and page." · "A pilot for laptop browsers."
  - Closing heading "Ask your own documents." with both buttons again; footer "© 2026 Smart Tutor". No "Terms of use" link (Q45). No image.
- "Create an account" → `keycloak.login({ action: "register", redirectUri: origin + "/library" })`; "Sign in" → `keycloak.login({ redirectUri: origin + "/library" })`.
- `/` makes no request to Keycloak on load; `/` does not render the app shell (no left nav, no upload tray).
- Every app route (`/library`, `/chat`, `/conversations`, `/notes`, `/subjects`, `/usage`, any unknown path) is guarded; unknown paths redirect to `/library`.
- Sign-out keeps `keycloak.logout({ redirectUri: origin + "/" })`.
- Every color, font size, space, radius in feature CSS is a `var(--…)` token; a missing token is added to `tokens.css` first. Laptop only (1440px design, 1280px check), light and dark.
- Visible `:focus-visible` outline on every control (base.css already provides it; don't override).

## Review Focus

1. Signed-in visitor on `/` clicks "Sign in" — keycloak-js must not throw "init called twice" or "adapter undefined"; it inits once without `onLoad` and redirects (SSO returns straight to `/library`). Test: `signIn` before and after `init` calls `kc.init` at most once.
2. Keycloak redirect back to `/library#state=…&code=…` — the guarded route's `init({ onLoad: "login-required" })` must process the callback; landing's lazy init must never run on `/library`. Test: route test proves `/` never calls `auth.init`, `/library` does.
3. StrictMode double-mount on `/` — still no Keycloak call. Test: render `/` in StrictMode with the real `SessionProvider` guard, assert `auth.init` not called.
4. "Please sign in again" (session expired) keeps returning to the current page, not `/library`. Test: `signIn()` with no options calls `kc.login({})` (no `redirectUri`).
5. Document title on `/` — the app shell isn't there to set it. Test: landing sets `document.title` to "Smart Tutor".

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `web/src/auth/authClient.ts` | modify | `SignInOptions` type; `signIn(options?)` |
| `web/src/auth/keycloakClient.ts` | modify | lazy init without `onLoad` for `signIn`; map options to `keycloak.login` |
| `web/src/auth/keycloakClient.test.ts` | modify | tests for the above |
| `web/src/features/landing/LandingPage.tsx` | create | the page |
| `web/src/features/landing/LandingPage.module.css` | create | `.ld-*` styles rebuilt with tokens |
| `web/src/features/landing/LandingPage.test.tsx` | create | copy, buttons, title |
| `web/src/styles/tokens.css` | modify | add `--fs-64` |
| `web/src/app/routes.tsx` | modify | `createRoutes({ auth, RequireSession })` |
| `web/src/app/routes.test.tsx` | modify | public `/`, guarded app routes |
| `web/src/App.tsx` | modify | `App({ routes })` |
| `web/src/main.tsx` | modify | build the guard; no top-level `SessionProvider` |
| `web/src/components/AppShell/AppShell.tsx` | modify | comment only (`/ → /library` redirect no longer exists) |
| `DESIGN.md` | modify | note `--fs-64` and the landing page layout |

---

### Task 1: `signIn` options and lazy Keycloak init

**Files:**
- Modify: `web/src/auth/authClient.ts`
- Modify: `web/src/auth/keycloakClient.ts`
- Test: `web/src/auth/keycloakClient.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export type SignInOptions = {
    /** Open Keycloak's registration page instead of its login page. */
    register?: boolean;
    /** App path to return to after Keycloak, e.g. "/library". Default: the current page. */
    redirectTo?: string;
  };
  // AuthClient.signIn(options?: SignInOptions): Promise<void>
  ```

- [ ] **Step 1: Write the failing tests** — append to the `describe("keycloak client", …)` block in `keycloakClient.test.ts`:

```ts
  it("signs in from a page that never initialised Keycloak, without onLoad", async () => {
    await createKeycloakClient(config).signIn({ redirectTo: "/library" });
    expect(kc.init).toHaveBeenCalledWith({ pkceMethod: "S256", checkLoginIframe: false });
    expect(kc.login).toHaveBeenCalledWith({ redirectUri: `${window.location.origin}/library` });
  });

  it("opens the registration page for a new account", async () => {
    await createKeycloakClient(config).signIn({ register: true, redirectTo: "/library" });
    expect(kc.login).toHaveBeenCalledWith({ action: "register", redirectUri: `${window.location.origin}/library` });
  });

  it("signs in again to the current page after a session ends", async () => {
    const auth = createKeycloakClient(config);
    await auth.init();
    await auth.signIn();
    expect(kc.init).toHaveBeenCalledOnce(); // reuses the login-required init
    expect(kc.login).toHaveBeenCalledWith({});
  });

  it("initialises Keycloak once when sign-in is chosen twice", async () => {
    const auth = createKeycloakClient(config);
    await Promise.all([auth.signIn(), auth.signIn({ register: true })]);
    expect(kc.init).toHaveBeenCalledOnce();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/auth/keycloakClient.test.ts`
Expected: the four new tests FAIL (`kc.init` not called / `login` called with no args).

- [ ] **Step 3: Implement**

In `authClient.ts`, add the `SignInOptions` type above `AuthClient` (exact code from Interfaces) and change the member to:

```ts
  /** Opens Keycloak's login (or registration) page; works before init(). */
  signIn(options?: SignInOptions): Promise<void>;
```

In `keycloakClient.ts`, replace the body of `createKeycloakClient` with:

```ts
  const keycloak = new Keycloak(config);
  // keycloak-js throws if init runs twice (StrictMode), so every caller shares one init.
  let initialized: Promise<void> | undefined;

  const start = (options: KeycloakInitOptions) => {
    initialized ??= keycloak.init({ ...options, pkceMethod: "S256", checkLoginIframe: false }).then(
      () => undefined,
      (error: unknown) => {
        initialized = undefined; // a failed init must not stay cached, so "Try again" can re-run it
        throw error;
      },
    );
    return initialized;
  };

  return {
    init: () => start({ onLoad: "login-required" }),
    async getToken() {
      await keycloak.updateToken(60);
      if (!keycloak.token) throw new Error("Not signed in");
      return keycloak.token;
    },
    // The landing page signs in without init(): init without onLoad sends no request.
    async signIn({ register, redirectTo }: SignInOptions = {}) {
      await start({});
      await keycloak.login({
        ...(register && { action: "register" }),
        ...(redirectTo && { redirectUri: `${window.location.origin}${redirectTo}` }),
      });
    },
    signOut: () => keycloak.logout({ redirectUri: `${window.location.origin}/` }),
  };
```

Update the imports: `import Keycloak, { type KeycloakInitOptions } from "keycloak-js";` and `import type { AuthClient, SignInOptions } from "./authClient";`. Keep `{ onLoad: "login-required", pkceMethod: "S256", checkLoginIframe: false }` as the exact init argument for `init()` — the existing test "signs in with PKCE and login-required" asserts it (property order doesn't matter to `toHaveBeenCalledWith`).

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/auth`
Expected: PASS (all keycloak client and SessionProvider tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/auth
git commit -m "Let sign-in open Keycloak login or registration before init" -m "The public landing page (#102) must not call Keycloak on load, so signIn initialises keycloak-js lazily without onLoad (no network request) and can open the registration page and return to /library."
```

---

### Task 2: Landing page component

**Files:**
- Create: `web/src/features/landing/LandingPage.tsx`
- Create: `web/src/features/landing/LandingPage.module.css`
- Create: `web/src/features/landing/LandingPage.test.tsx`
- Modify: `web/src/styles/tokens.css` (add `--fs-64: 64px;` to the `--fs-*` line block in `:root, [data-theme="light"]`; check whether `[data-theme="dark"]` repeats size tokens — if it does, add it there too)
- Modify: `DESIGN.md` (Tokens table: sizes `--fs-12` … `--fs-40`, plus `--fs-64` for the landing headline; Layout: one bullet "**Landing page** (`/`): public, outside the app shell, centered `--page-w` column with header, hero, how it works, trust points, closing, footer.")

**Interfaces:**
- Consumes: `AuthClient["signIn"]` and `SignInOptions` from Task 1.
- Produces: `export function LandingPage({ signIn }: { signIn: AuthClient["signIn"] }): JSX.Element`

- [ ] **Step 1: Write the failing test** — `LandingPage.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run src/features/landing`
Expected: FAIL — cannot resolve `./LandingPage`.

- [ ] **Step 3: Implement** — `LandingPage.tsx`:

```tsx
import { useEffect } from "react";

import type { AuthClient } from "../../auth/authClient";
import { BrandMark } from "../../components/BrandMark/BrandMark";
import { Button } from "../../components/Button/Button";
import styles from "./LandingPage.module.css";

// Brief §9 landing copy, verbatim.
const STEPS = ["Upload your PDFs", "Ask a question", "Check the page it came from"];
const TRUST: [lead: string, rest: string][] = [
  ["Only your documents:", "the tutor never answers from anything else."],
  ["Private to you:", "no one else sees your documents, conversations, or notes."],
  ["", "Every answer cites the document title and page."],
  ["", "A pilot for laptop browsers."],
];

type Props = { signIn: AuthClient["signIn"] };

// The public page at / (brief §6.0, US-1): outside the app shell, text only. Keycloak opens only
// when a button is chosen; both buttons return to the Library (a signed-in visitor goes straight there).
export function LandingPage({ signIn }: Props) {
  useEffect(() => {
    document.title = "Smart Tutor";
  }, []);

  const createAccount = () => void signIn({ register: true, redirectTo: "/library" });
  const logIn = () => void signIn({ redirectTo: "/library" });
  const ctas = (
    <div className={styles.ctas}>
      <Button variant="primary" size="lg" onClick={createAccount}>
        Create an account
      </Button>
      <Button variant="secondary" size="lg" onClick={logIn}>
        Sign in
      </Button>
    </div>
  );

  return (
    <div className={styles.landing}>
      <header className={styles.head}>
        <BrandMark />
        <Button variant="ghost" onClick={logIn}>
          Sign in
        </Button>
      </header>
      <main className={styles.main} id="main-content">
        <section className={styles.hero} aria-labelledby="landing-title">
          <h1 id="landing-title" className={styles.title}>
            <span>Ask your own documents.</span> <span className={styles.accent}>Get answers you can check.</span>
          </h1>
          <p className={styles.sub}>Upload your PDFs. Smart Tutor answers only from them and shows the title and page for every answer.</p>
          {ctas}
          <p className={styles.pilot}>Pilot · laptop browsers only.</p>
        </section>

        <section className={styles.section} aria-labelledby="landing-how">
          <h2 id="landing-how" className={styles.kicker}>
            How it works
          </h2>
          <ol className={styles.steps} aria-labelledby="landing-how">
            {STEPS.map((step, i) => (
              <li key={step}>
                <span className={styles.num} aria-hidden="true">{`0${i + 1}`}</span>
                <span className={styles.step}>{step}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.section}>
          <ul className={styles.trust} aria-label="What you can rely on">
            {TRUST.map(([lead, rest]) => (
              <li key={rest}>
                {lead && <strong>{lead}</strong>}
                {lead && " "}
                {rest}
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.close} aria-labelledby="landing-close">
          <h2 id="landing-close" className={styles.closeTitle}>
            Ask your own documents.
          </h2>
          {ctas}
        </section>
      </main>
      <footer className={styles.foot}>© 2026 Smart Tutor</footer>
    </div>
  );
}
```

Note on the step test: `aria-hidden` spans still contribute to `textContent`, hence `"01Upload your PDFs"`. The space between the two `<span>`s in `h1` makes the heading's text "Ask your own documents. Get answers you can check."

`LandingPage.module.css` (rebuilds prototype `.ld-*` at `design-v0.7` with tokens; `--page-w` is 1120px):

```css
.landing { min-height: 100vh; display: grid; grid-template-rows: auto 1fr auto; background: var(--bg); color: var(--text); }
.head, .main, .foot { width: min(var(--page-w), 100% - 2 * var(--sp-8)); margin-inline: auto; }
.head { display: flex; align-items: center; justify-content: space-between; padding: var(--sp-6) 0; }

.hero { padding: var(--sp-16) 0; border-bottom: 1px solid var(--border); }
.title { margin: 0; font-size: var(--fs-64); line-height: 1.08; letter-spacing: -.02em; max-width: 28ch; text-wrap: balance; }
.title span { display: block; }
.accent { color: var(--accent-text); }
.sub { margin: var(--sp-6) 0 0; font-size: var(--fs-20); line-height: var(--lh-body); color: var(--text-2); max-width: 54ch; }
.ctas { display: flex; flex-wrap: wrap; gap: var(--sp-3); margin-top: var(--sp-8); }
.pilot { margin: var(--sp-4) 0 0; font-size: var(--fs-14); color: var(--text-2); }

.section { padding: var(--sp-12) 0; border-bottom: 1px solid var(--border); }
.kicker { margin: 0 0 var(--sp-6); font-family: var(--font-body); font-size: var(--fs-12); font-weight: 650; text-transform: uppercase; letter-spacing: .08em; color: var(--text-2); }
.steps { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--sp-8); }
.steps li { display: grid; gap: var(--sp-3); align-content: start; }
.num { font-family: var(--font-mono); font-size: var(--fs-14); color: var(--accent-text); }
.step { font-family: var(--font-display); font-size: var(--fs-24); font-weight: 600; line-height: 1.25; letter-spacing: -.01em; }
.trust { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--sp-8); }
.trust li { padding-top: var(--sp-4); border-top: 2px solid var(--text); font-size: var(--fs-16); line-height: var(--lh-body); color: var(--text-2); }
.trust strong { color: var(--text); font-weight: 650; }

.close { padding: var(--sp-16) 0; }
.closeTitle { margin: 0; font-size: var(--fs-40); }
.close .ctas { margin-top: var(--sp-6); }

.foot { display: flex; align-items: center; padding: var(--sp-4) 0 var(--sp-6); border-top: 1px solid var(--border); font-size: var(--fs-14); color: var(--text-2); }
```

If `--page-w` is not in `tokens.css`, check its real name in the Layout block (`DESIGN.md` says `--page-w` 1120px) and use that.

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/features/landing`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/landing web/src/styles/tokens.css DESIGN.md
git commit -m "Add the public landing page" -m "Brief §6.0 and §9 (design-v0.7, landing-default): what Smart Tutor does, how it works, trust points, and Create an account / Sign in, which open Keycloak only when chosen and return to the Library (#102)."
```

---

### Task 3: Public `/`, guarded app routes

**Files:**
- Modify: `web/src/app/routes.tsx`
- Modify: `web/src/app/routes.test.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/main.tsx`
- Modify: `web/src/components/AppShell/AppShell.tsx` (comment only)

**Interfaces:**
- Consumes: `LandingPage({ signIn })` (Task 2); `AuthClient` with `signIn(options?)` (Task 1); `SessionProvider({ auth, loadMe, children })` (existing).
- Produces:
  ```ts
  export type RouteDeps = {
    auth: Pick<AuthClient, "signIn">;
    /** Wraps every app route; renders its children only for a live session. */
    RequireSession: ComponentType<{ children: ReactNode }>;
  };
  export function createRoutes(deps: RouteDeps): RouteObject[];
  export function App({ routes }: { routes: RouteObject[] }): JSX.Element;
  ```

- [ ] **Step 1: Write the failing tests** — rework `routes.test.tsx`:

Replace the imports of `routes` and the `renderAt` helper with:

```tsx
import { SessionContext, SessionProvider } from "../auth/SessionProvider";
import type { AuthClient } from "../auth/authClient";
import { NAV } from "./nav";
import { createRoutes } from "./routes";

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
```

Add `import type { ReactNode } from "react";` (merge with the existing `StrictMode` import).

Replace the test "redirects / to the Library" with these, in a new `describe("public landing page", …)` block:

```tsx
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
    expect(await screen.findByRole("button", { name: "Create an account", hidden: false })).toBeInTheDocument();
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
    const nav = within(await screen.findByRole("navigation", { name: "Main" }));
    await userEvent.click(nav.getByRole("button", { name: /Ada Lovelace/ }));
    await userEvent.click(nav.getByRole("button", { name: "Sign out" }));
    expect(auth.signOut).toHaveBeenCalledOnce();
  });
});
```

The last test overlaps with "shows the learner's name and signs out from the user menu"; keep both — this one goes through the real `SessionProvider`.

Also replace the test "leaves focus alone when the app opens at / and redirects" with:

```tsx
  it("leaves focus alone when an unknown path redirects to the Library", async () => {
    renderAt("/nope");
    await screen.findByRole("heading", { level: 1, name: "Library" });
    expect(screen.getByRole("main")).not.toHaveFocus();
  });
```

All other existing tests stay as they are (they call `renderAt(path)` and get the `SignedIn` guard).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/app`
Expected: FAIL — `createRoutes` is not exported.

- [ ] **Step 3: Implement**

`routes.tsx`:

```tsx
import type { ComponentType, ReactNode } from "react";
import { Navigate, type RouteObject } from "react-router";

import type { AuthClient } from "../auth/authClient";
import { AppShell } from "../components/AppShell/AppShell";
import { ChatPage } from "../features/chat/ChatPage";
import { LandingPage } from "../features/landing/LandingPage";
import { LibraryPage } from "../features/library/LibraryPage";
import { NAV } from "./nav";
import { PlaceholderPage } from "./PlaceholderPage";

export type RouteDeps = {
  auth: Pick<AuthClient, "signIn">;
  /** Wraps every app route; renders its children only for a live session. */
  RequireSession: ComponentType<{ children: ReactNode }>;
};

// `/` is the public landing page (US-1); every other path needs a session.
export function createRoutes({ auth, RequireSession }: RouteDeps): RouteObject[] {
  return [
    { path: "/", element: <LandingPage signIn={auth.signIn} /> },
    {
      element: (
        <RequireSession>
          <AppShell />
        </RequireSession>
      ),
      children: [
        { path: "library", element: <LibraryPage />, handle: { wide: true } },
        { path: "chat", element: <ChatPage /> },
        ...NAV.filter((item) => item.path !== "/library" && item.path !== "/chat").map((item) => ({
          path: item.path.slice(1),
          element: <PlaceholderPage title={item.label} description={item.description} />,
        })),
        { path: "*", element: <Navigate to="/library" replace /> },
      ],
    },
  ];
}
```

`App.tsx`:

```tsx
// Screens live in src/features/<feature>; shared UI in src/components; Keycloak login (PKCE) in src/auth; API client in src/api.
import { useState } from "react";
import { createBrowserRouter, RouterProvider, type RouteObject } from "react-router";

export function App({ routes }: { routes: RouteObject[] }) {
  const [router] = useState(() => createBrowserRouter(routes));
  return <RouterProvider router={router} />;
}
```

`main.tsx` — replace the render block and imports so the guard is built from the existing `auth` and `loadMe`:

```tsx
import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { createRoutes } from "./app/routes";
// …existing api/auth/theme imports unchanged…

const auth = createKeycloakClient();
configureApiClient({ baseUrl: apiBaseUrl(), getToken: () => auth.getToken(), onUnauthorized: sessionExpiry.notify });

function RequireSession({ children }: { children: ReactNode }) {
  return (
    <SessionProvider auth={auth} loadMe={loadMe}>
      {children}
    </SessionProvider>
  );
}

const routes = createRoutes({ auth, RequireSession });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App routes={routes} />
  </StrictMode>,
);
```

`AuthClient.signIn` is a plain closure property in `keycloakClient.ts` (no `this`), so passing `auth.signIn` unbound is safe.

`AppShell.tsx` — change the comment `// runs this twice with the same path) and not on a redirect such as / → /library.` to `// runs this twice with the same path) and not on a redirect such as an unknown path → /library.`

- [ ] **Step 4: Run the whole web suite and the build**

Run: `cd web && npx vitest run && npm run build`
Expected: all tests PASS; `tsc -b && vite build` succeeds.

- [ ] **Step 5: Commit**

```bash
git add web/src/app web/src/App.tsx web/src/main.tsx web/src/components/AppShell/AppShell.tsx
git commit -m "Serve the landing page at / and require sign-in only for app routes" -m "SessionProvider wrapped the whole app with login-required, so a signed-out visitor never saw a public page (#102). It now wraps the AppShell routes; / renders the landing page and makes no request to Keycloak, and sign-out (which returns to /) lands there."
```

---

### Task 4 (controller, not a subagent): visual check

- [ ] Run `npm run dev` in `web/` (no Keycloak needed for `/`), screenshot `http://localhost:10453/` at 1440×900 and 1280×800 in light and dark with Playwright (`colorScheme: "dark"`), compare with `.design-shots/v0.7/landing-default.{light,dark}.png`, and fix differences.
- [ ] Tab through the page and confirm a visible focus outline on each button.
