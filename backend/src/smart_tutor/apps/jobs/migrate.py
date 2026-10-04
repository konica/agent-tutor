"""Bring the database schema to the latest revision.

Runs before the API starts (Compose `migrate`, a Helm hook later).
"""

from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings


def main() -> None:
    upgrade_to_head(Settings().database_url)


if __name__ == "__main__":
    main()
