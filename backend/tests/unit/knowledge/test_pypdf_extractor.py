from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter

from fakes.pdfs import make_pdf
from smart_tutor.knowledge.adapters.pypdf_extractor import PypdfExtractor
from smart_tutor.knowledge.ports.pdf_extractor import UnreadablePdfError


def test_extracts_one_text_per_page_with_blank_pages_kept() -> None:
    pages = PypdfExtractor().extract_pages(make_pdf(["Hello page one", "", "Page three"]))

    assert len(pages) == 3
    assert "Hello page one" in pages[0]
    assert pages[1].strip() == ""
    assert "Page three" in pages[2]


def test_keeps_line_breaks_and_escaped_characters() -> None:
    pages = PypdfExtractor().extract_pages(make_pdf(["Line (one)\nback\\slash"]))

    assert "Line (one)" in pages[0]
    assert "back\\slash" in pages[0]


@pytest.mark.parametrize("data", [b"not a pdf", make_pdf(["Hello"])[:40], b""])
def test_unreadable_bytes_raise(data: bytes) -> None:
    with pytest.raises(UnreadablePdfError):
        PypdfExtractor().extract_pages(data)


def test_encrypted_pdf_raises() -> None:
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_pdf(["Secret"]))))
    writer.encrypt("pw")
    out = BytesIO()
    writer.write(out)

    with pytest.raises(UnreadablePdfError):
        PypdfExtractor().extract_pages(out.getvalue())
