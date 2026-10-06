# Landing page and a thinner Keycloak login

Date: 2026-10-06. Participants: Product Owner reviewer (PO), UI/UX Designer reviewer (UX), facilitated by Claude, for the owner (Thao Dinh). Status: **applied with the recommended defaults** for decisions 1–3 (owner said "go ahead", 2026-10-06); the owner may override any of them in review. Recorded in PRD v2.14 (US-1, Q45) and brief v0.5.

The owner asked for "a landing page to provide an overview of Smart Tutor" and to "minimize the customization of the login page in Keycloak".

## Today

- Every visit to the app redirects straight to Keycloak (`keycloak-js` with `onLoad: "login-required"`); there is no public page. `/` redirects to `/library` inside the app shell.
- Brief v0.4 §6.2 asks for a **custom Keycloak theme** for the login, registration, and email-verification pages (states `auth-sign-in`, `auth-sign-up`, `auth-verify-email`), plus an **in-app Terms step** on first sign-in (`terms-first-run`, `terms-accepted`).
- The realm has no theme yet (`local/keycloak/realm-smart-tutor.json`: self-registration and email verification on, no `loginTheme`).
- The pilot is served from one CloudFront address: `/` web, `/api/*` API, `/auth/*` Keycloak (ADR 0009). No custom domain.

## Where the reviewers agree

| Topic | Agreed position |
|---|---|
| Landing page | Worth it for the pilot, kept minimal. It answers "what is this?" for someone who opens the bare CloudFront link from an invite, and moves them to sign-up. |
| Leave out | Pricing, testimonials, logos, blog, SEO work, later-release features (quizzes, sharing, research map), stock "AI" imagery, mobile promises, accuracy claims beyond "cites its source". |
| Honesty points | Answers come only from your own documents; documents are private to you; laptop only; it is a pilot. |
| Keycloak | **Stock layout with brand overrides only:** a theme that extends Keycloak's default (`keycloak.v2`), adds the Smart Tutor logo, sets a few CSS variables (accent color, background, font), and sets the realm display name. Stock forms, labels, errors, and email-verification pages. No custom templates. Cheap to keep across Keycloak upgrades. |
| Terms | Stay in the app on first sign-in. Keycloak knows nothing about the upload warranty; the in-app step is testable and easy to change. `terms-first-run` and `terms-accepted` are unchanged. |
| Accessibility | The stock Keycloak pages already handle labels, focus, and errors; our CSS must keep focus rings visible and AA contrast. |

## Where they differ

| Topic | PO | UX | Facilitator's recommendation |
|---|---|---|---|
| Page size | One hero: name, one line, two benefits, "Sign up". | Hero, "How it works" (upload → ask → check the page), four trust points, closing call to action, footer with Terms. | **UX's sections, as one short page.** "How it works" and the trust points carry the honesty points; the extra cost is copy, not engineering. |
| Hero image | — (text only) | A static render of the app (Library plus a cited answer). | **Decision 1.** |
| Signed-in visitor at `/` | — | Show the landing page with "Open your library" (needs `check-sso` and a silent-check page). | **Simpler:** the landing page doesn't talk to Keycloak at all. "Sign in" goes through Keycloak, which returns a signed-in visitor to `/library` at once (single sign-on), so no `landing-signed-in` state and no silent-check page. **Decision 2.** |
| PRD form | New story "US-0.5 View product overview"; success metric "90% of sign-ups start on the landing page". | One-line change to US-1 (journey starts on the landing page). | **Extend US-1** with one acceptance criterion; no new story or ticket parent. The landing page is the only public way in, so the PO's metric would always be ~100%; measure sign-up completion (landing → verified → terms accepted) instead. |
| Effort | Landing ~2 days, Keycloak CSS ~5 days. | — | Both estimates look high for a static page and one CSS file plus a logo; slice sizes come from `to-tickets`. |

The PO's risk "learners confuse Keycloak's email with the terms" does not apply: Keycloak's emails cover only email verification.

## Proposal

**Landing page at `/`** (public; every other route requires sign-in):

```
[Smart Tutor logo]                                  [Sign in]
--------------------------------------------------------------
 Ask your own documents.                  | (image or nothing:
 Get answers you can check.               |  Decision 1)
 Upload your PDFs. Smart Tutor answers    |
 only from them and shows the title and   |
 page for every answer.                   |
 [Create an account]  [Sign in]           |
 Pilot · laptop browsers only             |
--------------------------------------------------------------
 How it works:  1 Upload your PDFs  2 Ask  3 Check the page
--------------------------------------------------------------
 Only your documents | Private to you | Title and page cited | Pilot, laptop only
--------------------------------------------------------------
 [Create an account]  [Sign in]                  Terms of use
```

- "Create an account" → Keycloak registration; "Sign in" → Keycloak login; both return to `/library`. Sign-out returns to `/`.
- Same tokens and fonts as the app (`DESIGN.md`); light theme required, dark supported.
- Keycloak: stock `keycloak.v2` pages with the Smart Tutor logo, colors, font, and realm display name ("Smart Tutor").

**Changes once the owner decides:**

| Where | Change |
|---|---|
| PRD (v2.13) | US-1: "*Given* a visitor who isn't signed in, *when* they open Smart Tutor, *then* they see the landing page (what it does, the honesty points, "Create an account", "Sign in"); every other page requires sign-in." Scope line: public landing page; Keycloak's hosted pages with Smart Tutor logo and colors only. Decisions log row. |
| Brief (v0.5) | §0 lists the states; §4 scope; §5 J1 starts on the landing page (plus a returning variant: landing → Sign in → Library); new §6.0 Landing with the copy above in §9; §6.2 becomes "Keycloak pages (stock layout, logo and colors) and Terms". |
| States | New `landing-default`. `auth-sign-in`, `auth-sign-up`, `auth-verify-email` become low-detail references ("stock Keycloak layout with Smart Tutor logo and colors"). Terms states unchanged. |
| Tickets | US-1 (#8) gets the new criterion and `landing-default`; the Keycloak theme becomes a small slice under #8 (theme folder mounted in Compose and Helm, realm `loginTheme`, post-logout redirect to `/`). |
| Code (later, via tickets) | `onLoad: "login-required"` moves from global to a guard on app routes; `/` renders the landing page outside the app shell. |

## Decisions for the owner

1. **Hero image:** text only for the pilot (fastest, no design round for imagery), or a static render of the app (a Library and a cited answer, made from the prototype)? *Recommendation: text only now; add the render after the pilot if sign-ups need it.*
2. **Signed-in visitor at `/`:** same landing page, where "Sign in" returns them to the Library through single sign-on (simplest), or a signed-in variant with "Open your library" (needs `check-sso` and one more state)? *Recommendation: the simplest.*
3. **PRD form:** extend US-1 (recommended), or a new story for the landing page?

## Update (2026-10-06, later)

The product owner then removed the terms of use step and the Settings page (#46, #49, #50; PRD v2.14 Q45). The "Terms" row above and the footer link no longer apply: the landing page has no terms link, and the Library's upload area says "Only upload documents you have the right to use." instead (PRD v2.15 Q47, brief v0.6).
