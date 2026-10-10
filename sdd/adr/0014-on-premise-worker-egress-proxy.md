# 0014. On-premise worker egress: an internal network and an allowlisting proxy

- Status: accepted
- Date: 2026-10-10
- Narrows: 0012's "Worker egress gap" (the worker can no longer reach the internet)

## Context

ADR 0012 left the on-premise worker able to reach the internet, so a compromised PDF parser could send data out. Native-cloud closes this with a NetworkPolicy. On-premise needs its own mechanism.

The worker talks to S3, SQS, SSM, Bedrock, the instance metadata service (for its credentials), and Postgres. The Host VPC has no NAT and only an S3 gateway endpoint, so the AWS services are reached at public IP addresses that every AWS customer shares.

## Decision

- The worker runs on an `internal: true` Compose network (`worker`), which has no route out of the VM. Postgres is on that network too.
- A Squid container (`egress-proxy`) is the worker's only way out. It allows CONNECT on port 443 to the documents bucket and to the SQS, SSM, and Bedrock runtime endpoints in the region, and plain HTTP on port 80 to the instance metadata service. It refuses everything else with 403. Hosts are matched by exact name.
- The Squid configuration is an interpolated environment variable in `compose.yaml`, so the bucket and region come from the same settings as the rest of the stack.
- `deploy/on-premise/check-egress.py` runs inside the worker on every deploy. It must fail to reach other hosts, directly and through the proxy, and must reach the allowed ones. A leak, or a check that fails to run or crashes, stops the worker and fails the deploy; an unreachable allowed host fails the deploy and leaves the worker running. The weekly patch window (`ensure-healthy.sh`) re-runs the isolation and egress checks the same way, so a worker that fails them doesn't come back after patching.

## Alternatives rejected

- **Host firewall (`DOCKER-USER` iptables) by IP address.** AWS's published ranges for SQS, SSM, and Bedrock include every customer's EC2 addresses, so an IP allowlist would admit any server on EC2. The proxy admits only the named AWS API endpoints.
- **Interface VPC endpoints for SQS, SSM, and Bedrock.** They would make IP rules meaningful, but cost about $7 a month each and change DNS for the whole VM.
- **A custom proxy.** More code to trust than Squid.

## Consequences

- One more container (about 20 MB of RAM).
- A new AWS endpoint for the worker means editing the allowlist in `compose.yaml`. The deploy check fails the deploy until then.
- Squid sees only the host name in CONNECT; a compromised worker controls what goes inside the tunnel. It can still send data out through the allowed AWS APIs: by signing requests with credentials of its own (for example, SendMessage to another account's queue on the SQS endpoint), to resources that allow anonymous access, or by naming another bucket inside a tunnel opened to our bucket's host (S3 front ends serve every bucket, and the S3 gateway endpoint has the default full-access policy). This is the same residual as native-cloud's NetworkPolicy. What the proxy closes is every other host: arbitrary internet hosts, any server on EC2, and DNS.
- Follow-up hardening would close that residual: an S3 gateway endpoint policy limited to our account (free), and interface endpoints with policies for SQS, SSM, and Bedrock (about $7 a month each).
- Native-cloud is unchanged.
