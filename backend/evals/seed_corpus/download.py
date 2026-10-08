"""Download the seed corpus PDFs, verifying each against its manifest SHA-256.

Run: `uv run --extra eval python -m evals.seed_corpus.download` (from `backend/`).
"""

from __future__ import annotations

import hashlib
import time
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

from evals.seed_corpus.manifest import PDF_DIR, SeedDocument, load_manifest

USER_AGENT = "smart-tutor-eval/0.1 (seed corpus download; https://github.com/konica/agent-tutor)"
ARXIV_PAUSE_SECONDS = 3.0


class ChecksumError(Exception):
    """Downloaded bytes do not match the manifest's SHA-256."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_all(
    docs: Sequence[SeedDocument],
    fetch: Callable[[str], bytes],
    pdf_dir: Path = PDF_DIR,
) -> list[str]:
    """Fetch every missing or corrupt PDF; return the ids fetched.

    A file whose hash differs from the manifest is never written.
    """
    fetched: list[str] = []
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        path = doc.pdf_path(pdf_dir)
        if path.exists() and _sha256(path.read_bytes()) == doc.sha256:
            continue
        data = fetch(doc.url)
        digest = _sha256(data)
        if digest != doc.sha256:
            raise ChecksumError(f"{doc.id}: sha256 {digest} from {doc.url} does not match manifest {doc.sha256}")
        path.write_bytes(data)
        fetched.append(doc.id)
    return fetched


def _urlopen_fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        data: bytes = response.read()
    if "arxiv.org" in url:
        time.sleep(ARXIV_PAUSE_SECONDS)
    return data


def main() -> None:
    docs = load_manifest()
    fetched = download_all(docs, _urlopen_fetch)
    print(f"{len(docs)} documents; fetched {len(fetched)}, {len(docs) - len(fetched)} already present")


if __name__ == "__main__":
    main()
