"""CronJob (daily): delete decline-log entries older than 90 days (PRD §9.6, §11).

Traces are not deleted here: they expire through their LangSmith project's retention, at most 180 days (D25; the
deploy runbooks set it). Threads, notes, and learning records are kept (PRD D25, §9.6, §11).
"""


def main() -> None:
    raise NotImplementedError("M4: retention job")


if __name__ == "__main__":
    main()
