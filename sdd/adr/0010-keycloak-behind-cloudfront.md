# 0010. Keycloak behind CloudFront: pinned hostname, a trusted `Forwarded` header, and databases made by a Helm hook

- Status: accepted
- Date: 2026-10-06

## Context

Keycloak runs at `/auth` behind CloudFront and an internal ALB, and the hop between them is plain HTTP (ADR 0009). The ALB overwrites `X-Forwarded-Proto` with `http`, so Keycloak cannot learn from that header that the learner used HTTPS. CloudFormation can create the RDS instance but cannot run SQL, so something else must create the `app` and `keycloak` databases and roles.

A spike showed what the proxy headers change. Without them, sign-in through an HTTPS proxy that forwards plain HTTP worked, but `KEYCLOAK_IDENTITY` and `KEYCLOAK_SESSION` were not `Secure`. With a static `Forwarded: proto=https` header and `KC_PROXY_HEADERS=forwarded`, both cookies were `Secure`. The spike also showed that a read-only root filesystem needs a writable `/opt/keycloak/data`.

## Decision

- **Pinned hostname.** `KC_HOSTNAME` is the full public URL with `/auth` (`https://<id>.cloudfront.net/auth`), passed as `global.publicUrl`. Keycloak refuses to start without it.
- **A trusted `Forwarded` header.** CloudFront adds `Forwarded: proto=https` to every origin request, and Keycloak reads only that header (`KC_PROXY_HEADERS=forwarded`). CloudFront overwrites a value the viewer sends, so the viewer cannot forge it.
- **An optimized image.** `deploy/keycloak/Dockerfile` runs `kc.sh build` once, so a pod starts with `start --optimized` and does not re-augment on every start.
- **One RDS instance, two databases, two roles.** A Helm `pre-install,pre-upgrade` hook Job (`db-bootstrap`) connects with the master secret and creates the roles and databases idempotently. It sets the role passwords from the `smart-tutor/db/*` secrets. The Job leaves the cluster after it succeeds.
- **The realm is imported once** from a file with environment placeholders. Client secrets come from Secrets Manager.

## Alternatives rejected

- **`KC_PROXY_HEADERS=xforwarded`.** The ALB sets `X-Forwarded-Proto: http`, so the cookies are not `Secure`.
- **No proxy headers.** Sign-in works, but the session cookies are not `Secure` (the spike).
- **A Lambda custom resource for the SQL.** It needs a bundled database driver and a Lambda inside the VPC, which is more to build and maintain than a hook Job.
- **Keycloak as the RDS master user.** Keycloak would have no isolation from the app's data.
- **The stock image with `start`.** Keycloak re-augments on every start, which slows each pod start.

## Consequences

- A new distribution address or a custom domain needs `--set global.publicUrl` on the next deploy, and the redirect URIs changed in the admin console. The realm import does not overwrite an existing realm.
- A password rotation in Secrets Manager reaches the database on the next `helm upgrade`, because the hook runs before every install and upgrade.
- Client IP addresses in Keycloak events are the ALB's.
