# 0022. On-premise hosts run 07:00–18:00 and carry no CloudWatch alarms

- Status: accepted
- Date: 2026-10-14
- Supersedes: #152's recovery alarm and uptime check, and #151's backup and snapshot alarms

## Context

The on-premise host runs around the clock, but learners use the pilot during the day. The product owner wants it off
00:00–07:00 and 18:00–24:00 in Asia/Ho_Chi_Minh (GMT+7), every day, to save cost, and no CloudWatch alarms: they cost
money, and with a daily stop the uptime alarm would email twice a day. The same will apply to the shared Langfuse host
(ADR 0021, when that host lands). Spec: `sdd/specs/2026-10-14-off-hours-and-langfuse-host-design.md`.

## Decision

- **Schedule.** Each host has an EventBridge Scheduler group `<prefix>-off-hours` with three schedules in
  Asia/Ho_Chi_Minh: `stop` at 18:00, `stop-late` at 00:00, `start` at 07:00. They call `ec2:StopInstances` and
  `ec2:StartInstances` directly (universal targets), retry twice, and use a role that may only start and stop that
  instance. No Lambda, no dead-letter queue.
- **Manual starts.** Anyone with EC2 access may start a host at any hour; it boots as at 07:00 (the data volume
  mounts, Docker starts every service, the Elastic IP and certificates stay). `stop-late` stops a host started in the
  evening; an operator who needs it overnight disables `stop-late` and enables it again afterwards.
- **Clean stops.** A stop shuts the OS down. Postgres (and ClickHouse on the Langfuse host) get a 60 s grace period, and
  Docker's systemd unit gets 120 s to stop.
- **No CloudWatch alarms.** The recovery alarm, uptime check, and backup and snapshot alarms are removed, with the
  `JobFailed` metric that fed one of them. EC2's default automatic recovery still moves an instance off failed
  hardware. The weekly patching window moves to Sunday 07:20 and still emails its alert topic when it fails (an
  EventBridge rule, not an alarm).

## Consequences

- Learners can't use the product 18:00–07:00; the site doesn't answer (the DuckDNS name points at the host). The PRD
  states the hours.
- Nobody is told when the site is down during the day, when a nightly dump fails (`journalctl -u smart-tutor-backup`),
  or when a snapshot fails. The runbooks list the checks to run by hand.
- A deploy still running at 18:00 is cut off; deploy before 17:30 or start the host first.
- The nightly dump (03:00) runs at the next boot (`Persistent=true`); the 02:00 snapshot works on a stopped instance.
- Compute cost falls to about 46% of always-on. The two Elastic IPs are charged whether the hosts run or not.
