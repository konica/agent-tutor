# web

React + TypeScript (Vite). `npm install && npm run dev` → http://localhost:5173 (Keycloak client `smart-tutor-web`).

| Path | What |
|---|---|
| `src/features/` | One folder per feature: `library` (upload, documents), `subjects` (choose, rename), `chat`, `conversations`, `notes`, `usage`; (R2) `research-map`; (R3) `quizzes`, `reports` |
| `src/api/` | Typed client generated from the API's OpenAPI schema |
| `src/auth/` | Keycloak OIDC (Authorization Code + PKCE) |
| `src/components/` | Shared UI |

Mockups follow the versioned briefs in `sdd/design-briefs/`.

## Configuration

Build-time variables, defaulting to Docker Compose: `VITE_API_URL` (`http://localhost:8001`), `VITE_KEYCLOAK_URL` (`http://localhost:10480`), `VITE_KEYCLOAK_REALM` (`smart-tutor`), `VITE_KEYCLOAK_CLIENT_ID` (`smart-tutor-web`).

## API client

`src/api/openapi.json` is a snapshot of the API's OpenAPI schema and `src/api/generated/` is generated from it; `make api-client` (or `npm run api:generate` here) regenerates both. The generator lives in its own package, `tools/api-gen/` (TypeScript 6 and `@hey-api/openapi-ts`, own lockfile), because the app's TypeScript 7 has no JavaScript compiler API; `npm run api:generate` delegates to it.
