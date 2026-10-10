"""A page's cleaned text: what chunks are cut from and what `start_index` counts in (PRD §9.2 step 6, §9.4)."""

import re
import unicodedata
from collections.abc import Sequence


def clean_page_text(text: str) -> str:
    """Fold ligatures, rejoin words hyphenated across lines, and drop control characters except \\n and \\t."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) != "Cc")


def locate_chunks(page_text: str, texts: Sequence[str]) -> list[int | None]:
    """Each chunk's offset in the cleaned page text, chunks given in the chunker's order (None when absent).

    The splitter's chunks start in increasing order, so each search starts just after the previous chunk's start;
    that picks the right copy of a repeated passage. A chunk not found there is looked for in the whole page.
    """
    found: list[int | None] = []
    after = 0
    for text in texts:
        index = page_text.find(text, after)
        if index < 0:
            index = page_text.find(text)
        if index < 0:
            found.append(None)
            continue
        found.append(index)
        after = index + 1
    return found
