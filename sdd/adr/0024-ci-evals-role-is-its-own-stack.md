# 0024. The CI evals role is its own stack

- Status: accepted
- Date: 2026-10-15

## Context

#226 gave the CI smoke evals a Bedrock-only AWS role, but as a runbook: an admin made it by hand from two checked-in policy JSON files. The product owner (2026-10-15, #337) wants every AWS resource in a stack, so it can be tracked and removed. The role had never been created. The deploy workflows run `cdk deploy --all -c smart-tutor:mode=…`, and ADR 0016 keeps the two deployment modes apart.

## Decision

- **The role is the stack `SmartTutor-EvalsCI`.** It holds the role `smart-tutor-evals-ci` and its inline Bedrock policy, built from `models.py`.
- **It has its own CDK entry,** `infra/evals_ci_app.py`, and is never part of `build_app`. Neither mode's stacks change.
- **An admin deploys and destroys it** with `make evals-ci-deploy` and `make evals-ci-destroy`.
- **It imports the GitHub OIDC provider by ARN,** the shared exception ADR 0016 already allows.
- **It outputs `RoleArn`,** which the admin sets as the GitHub secret `EVALS_AWS_ROLE_ARN`.

## Alternatives rejected

- **Keep the runbook.** The role is hand-made, untracked, and hard to remove.
- **Add it to `build_app` in both modes.** Each mode's `deploy --all` would own it, two apps would fight over one stack name, and a mode's teardown would delete CI's role.
- **Add it to one mode.** That ties CI to the lifetime of that mode.
- **Let a workflow deploy it.** A role can't create itself, and the deploy roles would need IAM rights over CI's role.
- **A separate CDK project, like `platform/langfuse`.** It needs `infra`'s `models.py` and context, and a second project for one role is too much.

## Consequences

- One more stack an admin deploys by hand, and again after a model change.
- Tearing down native-cloud's `GitHubDeploy` would still delete the OIDC provider that this role (and on-premise's deploy role) trusts. That is a separate follow-up.
