"""CronJob (daily): delete decline-log entries older than 90 days (PRD §9.6, §11).

Traces are not deleted here: a `trace-retention` job of ours will delete them from Langfuse within 180 days (D25; ADR
0023 §2; #321 builds it). Threads, notes, and learning records are kept (PRD D25, §9.6, §11).
"""


def main() -> None:
    raise NotImplementedError("M4: retention job")


if __name__ == "__main__":
    main()
