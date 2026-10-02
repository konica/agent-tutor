"""CronJob (daily): tag content files no active document references, so S3 lifecycle moves them to Glacier.

Removes the tag again when a document becomes active (M1, PRD §9.5).
"""


def main() -> None:
    raise NotImplementedError("M1: Glacier tagger")


if __name__ == "__main__":
    main()
