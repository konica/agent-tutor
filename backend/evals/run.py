"""Run an evaluation split as a LangSmith experiment and check it against thresholds.yaml.

Usage: uv run --extra eval python -m evals.run --split smoke|full
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["smoke", "full"], required=True)
    args = parser.parse_args()
    raise NotImplementedError(f"M2: run the {args.split} split")


if __name__ == "__main__":
    main()
