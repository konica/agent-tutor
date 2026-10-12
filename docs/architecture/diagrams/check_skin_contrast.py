"""Check the Smart Tutor diagram skin's text contrast (WCAG 2.x), light and dark.

    python docs/architecture/diagrams/check_skin_contrast.py [profile.md]

Reads the `### Semantic roles` table of a diagram-design profile (default: `smart-tutor-profile.md` next to this
file) and checks every text role against the surfaces diagram text sits on: `paper` (the page), `paper-2`, and the
node fill. `ink-strong` is checked against the accent fill it labels (`accent` at 0.85 over `paper`). Translucent
colours are composited over `paper` first. Exits 1 when a ratio is below 4.5:1. Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TEXT_ROLES = ("ink", "muted", "soft", "accent", "link")
MINIMUM = 4.5
ACCENT_FILL_OPACITY = 0.85

RGB = tuple[float, float, float]


def parse_color(value: str, paper: RGB | None = None) -> RGB:
    """Parse `#rrggbb` or `rgba(r,g,b,a)`; composite an rgba over `paper`."""
    value = value.strip()
    if value.startswith("#") and len(value) == 7:
        return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))
    match = re.fullmatch(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", value)
    if match and paper is not None:
        r, g, b, a = (float(x) for x in match.groups())
        return blend((r, g, b), paper, a)
    raise ValueError(f"unsupported colour {value!r}")


def blend(top: RGB, bottom: RGB, alpha: float) -> RGB:
    return (
        top[0] * alpha + bottom[0] * (1 - alpha),
        top[1] * alpha + bottom[1] * (1 - alpha),
        top[2] * alpha + bottom[2] * (1 - alpha),
    )


def luminance(rgb: RGB) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: RGB, b: RGB) -> float:
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def read_roles(profile: Path) -> dict[str, tuple[str, str]]:
    """Map role -> (light, dark) from the first backticked value in each colour cell."""
    text = profile.read_text(encoding="utf-8")
    section = text.split("### Semantic roles", 1)[1].split("\n### ", 1)[0]
    roles: dict[str, tuple[str, str]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not cells[0].startswith("`"):
            continue
        values = [re.search(r"`([^`]+)`", cell) for cell in cells[2:]]
        if values[0] and values[1]:
            roles[cells[0].strip("`")] = (values[0].group(1), values[1].group(1))
    return roles


def read_node_fill(profile: Path) -> tuple[str, str]:
    """The `backend` node fill (light, dark) from the node treatment table."""
    text = profile.read_text(encoding="utf-8")
    row = re.search(r"^\| `backend` \|([^|]+)\|", text, re.MULTILINE)
    if not row:
        raise ValueError("no `backend` row in the node treatment table")
    found = re.findall(r"`(#[0-9a-fA-F]{6})`", row.group(1))
    return found[0], found[-1]


def main() -> int:
    profile = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("smart-tutor-profile.md")
    roles = read_roles(profile)
    node_fill = read_node_fill(profile)
    failures = 0
    for theme, index in (("light", 0), ("dark", 1)):
        paper = parse_color(roles["paper"][index])
        surfaces = {
            "paper": paper,
            "paper-2": parse_color(roles["paper-2"][index], paper),
            "node fill": parse_color(node_fill[index], paper),
        }
        print(f"{theme}:")
        for role in TEXT_ROLES:
            color = parse_color(roles[role][index], paper)
            for surface_name, surface in surfaces.items():
                value = ratio(color, surface)
                ok = value >= MINIMUM
                failures += not ok
                print(f"  {role:<10} on {surface_name:<9} {value:5.2f}:1 {'ok' if ok else 'FAIL'}")
        accent_fill = blend(parse_color(roles["accent"][index], paper), paper, ACCENT_FILL_OPACITY)
        value = ratio(parse_color(roles["ink-strong"][index], paper), accent_fill)
        ok = value >= MINIMUM
        failures += not ok
        print(f"  {'ink-strong':<10} on accent   {value:5.2f}:1 {'ok' if ok else 'FAIL'}")
    print("all text roles clear 4.5:1" if not failures else f"{failures} pair(s) below 4.5:1")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
