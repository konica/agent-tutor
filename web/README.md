# web

React + TypeScript (Vite). `npm install && npm run dev` → http://localhost:5173 (Keycloak client `smart-tutor-web`).

| Path | What |
|---|---|
| `src/features/` | One folder per feature: `library` (upload, documents), `subjects` (choose, rename), `chat`, `conversations`, `notes`, `usage`; (R2) `research-map`; (R3) `quizzes`, `reports` |
| `src/api/` | Typed client generated from the API's OpenAPI schema |
| `src/auth/` | Keycloak OIDC (Authorization Code + PKCE) |
| `src/components/` | Shared UI |

Mockups follow the versioned briefs in `sdd/design-briefs/`.
