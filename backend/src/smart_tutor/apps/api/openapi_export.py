"""Write the API's OpenAPI schema for the web client generator: python -m smart_tutor.apps.api.openapi_export <path>."""

import json
import sys
from pathlib import Path

from smart_tutor.apps.api.main import create_app


def openapi_json() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    Path(sys.argv[1]).write_text(openapi_json(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
