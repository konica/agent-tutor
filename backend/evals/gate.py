"""The release gate (PRD §10.1): an experiment's scores against thresholds.yaml, as a pass/fail table.

A metric is a leaf of a release's tree, named by its dotted path (`subject_name_check.false_rejections`). Its
comparator is `min` (mean score >= value), `max` (mean score <= value), or `max_failures` (examples scoring below 1
<= value); a missing score counts as 0. A metric no suite scored is "not run": reported, never a pass, and it doesn't
fail the gate. A scored metric thresholds.yaml doesn't list is "no threshold", so a misspelled key shows.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

THRESHOLDS = Path(__file__).parent / "thresholds.yaml"
Comparator = Literal["min", "max", "max_failures"]
COMPARATORS: tuple[Comparator, ...] = ("min", "max", "max_failures")
Status = Literal["pass", "fail", "not run", "no threshold"]


@dataclass(frozen=True)
class Threshold:
    metric: str
    comparator: Comparator
    value: float


@dataclass(frozen=True)
class Row:
    metric: str
    status: Status
    threshold: Threshold | None
    observed: float | None  # the mean score, or for max_failures the number of failing examples
    examples: int


def load_thresholds(release: str, path: Path = THRESHOLDS) -> list[Threshold]:
    tree = yaml.safe_load(path.read_text(encoding="utf-8"))
    releases = [name for name in tree if name.startswith("release_")]
    if release not in releases:
        raise ValueError(f"{release!r} is not a release table in {path.name} (it has {', '.join(releases)})")
    return list(_leaves(tree[release], ""))


def _leaves(node: Mapping[str, Any], prefix: str) -> Iterator[Threshold]:
    for name, value in node.items():
        metric = f"{prefix}{name}"
        if not isinstance(value, Mapping):
            raise ValueError(f"{metric}: expected a comparator (min, max, max_failures) or nested metrics")
        found = [c for c in COMPARATORS if c in value]
        if len(found) > 1:
            raise ValueError(f"{metric}: more than one comparator ({', '.join(found)})")
        if found:
            yield Threshold(metric, found[0], float(value[found[0]]))
        else:
            yield from _leaves(value, f"{metric}.")


def _mean(scores: Sequence[float]) -> float:
    return sum(scores) / len(scores)


def check(thresholds: Sequence[Threshold], scores: Mapping[str, Sequence[float | bool | None]]) -> list[Row]:
    def numbers(metric: str) -> list[float]:
        return [0.0 if s is None else float(s) for s in scores.get(metric, [])]

    rows: list[Row] = []
    for t in thresholds:
        got = numbers(t.metric)
        if not got:
            rows.append(Row(t.metric, "not run", t, None, 0))
            continue
        if t.comparator == "max_failures":
            observed = float(sum(1 for s in got if s < 1))
            ok = observed <= t.value
        else:
            observed = _mean(got)
            ok = observed >= t.value if t.comparator == "min" else observed <= t.value
        rows.append(Row(t.metric, "pass" if ok else "fail", t, observed, len(got)))
    known = {t.metric for t in thresholds}
    for metric in scores:
        if metric not in known and (got := numbers(metric)):
            rows.append(Row(metric, "no threshold", None, _mean(got), len(got)))
    return rows


def passed(rows: Sequence[Row]) -> bool:
    return not any(r.status == "fail" for r in rows)


def ran(rows: Sequence[Row]) -> bool:
    return any(r.examples > 0 for r in rows)


def _target(t: Threshold | None) -> str:
    if t is None:
        return "-"
    if t.comparator == "max_failures":
        return f"<= {t.value:g} failures"
    return f"{'>=' if t.comparator == 'min' else '<='} {t.value:.2f}"


def _observed(r: Row) -> str:
    if r.observed is None:
        return "-"
    if r.threshold is not None and r.threshold.comparator == "max_failures":
        return f"{r.observed:g} failed"
    return f"{r.observed:.3f}"


def _verdict(rows: Sequence[Row]) -> str:
    counts = {s: sum(1 for r in rows if r.status == s) for s in ("pass", "fail", "not run")}
    verdict = "PASS" if passed(rows) else "FAIL"
    return f"{verdict} ({counts['pass']} passed, {counts['fail']} failed, {counts['not run']} not run)"


def render(rows: Sequence[Row], links: Mapping[str, str]) -> str:
    table = [("metric", "target", "observed", "examples", "result")]
    table += [
        (
            r.metric,
            _target(r.threshold),
            _observed(r),
            str(r.examples),
            r.status.upper() if r.status in ("pass", "fail") else r.status,
        )
        for r in rows
    ]
    widths = [max(len(line[i]) for line in table) for i in range(5)]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(line, widths, strict=True)).rstrip() for line in table]
    lines.insert(1, "  ".join("-" * w for w in widths))
    if links:
        lines += ["", "Experiments:"] + [f"  {name}: {url}" for name, url in links.items()]
    lines += ["", f"Gate: {_verdict(rows)}"]
    return "\n".join(lines)


def render_markdown(rows: Sequence[Row], links: Mapping[str, str], title: str) -> str:
    """The table for a GitHub job summary: a heading with the verdict, the metrics, then the experiments."""
    result = {"pass": "PASS", "fail": "**FAIL**"}
    lines = [
        f"### {title}: {_verdict(rows)}",
        "",
        "| metric | target | observed | examples | result |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.metric} | {_target(r.threshold)} | {_observed(r)} | {r.examples} | {result.get(r.status, r.status)} |"
        for r in rows
    ]
    if links:
        lines += ["", "Experiments:", ""]
        lines += [f"- [{name}]({url})" if url.startswith("http") else f"- {name}: {url}" for name, url in links.items()]
    return "\n".join(lines)
