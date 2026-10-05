# 0009. Serve the pilot from the CloudFront domain, through a VPC origin to an internal ALB

- Status: accepted
- Date: 2026-10-05

## Context

The pilot has no domain name (PRD Appendix A item 4). Learner tokens must not cross the internet unencrypted, so the public address needs HTTPS. The browser, the API, and Keycloak should share one origin, so the API needs no CORS.

## Decision

- **One public address:** the AWS-generated `https://<id>.cloudfront.net`. CloudFront routes by path: `/` goes to web, `/api/*` to the API, `/auth/*` to Keycloak.
- **CloudFront reaches an internal ALB through a VPC origin.** The load balancer has no public address and is reachable only from inside the VPC.
- **CDK owns the ALB, the listener rules, and the target groups.** The AWS Load Balancer Controller only registers pods, through a `TargetGroupBinding` that names the target group. The distribution never needs an ARN from a Helm install, so one `cdk deploy` creates the whole edge.
- **CloudFront to the ALB is plain HTTP.** The hop stays on AWS's network inside the VPC origin. The ALB gets no certificate, because a certificate needs a domain.
- **The web image uses relative `/api` and `/auth`.** It does not depend on the distribution's address, so the image builds before the distribution exists.

## Alternatives rejected

- **Own domain, ACM certificate, Route 53.** No domain exists yet (Appendix A item 4).
- **Internet-facing ALB with a secret header from CloudFront.** It leaves a public attack surface, and HTTPS on the ALB needs a domain anyway.
- **ALB created by a Kubernetes Ingress.** CloudFront would need the ALB's ARN after a Helm install, which makes the deploy two-phase.

## Consequences

- Moving to a custom domain later takes an ACM certificate in us-east-1, an alternate domain name on the distribution, and new Keycloak redirect URIs. Nothing else changes.
- The default `*.cloudfront.net` certificate fixes the minimum TLS version (the TLSv1 policy). That is acceptable for the pilot.
- A new service adds a target group, a listener rule, and a CloudFront behavior in `EdgeStack`.
