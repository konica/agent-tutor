from io import BytesIO

import pytest
from pypdf import PageObject, PdfReader, PdfWriter

from fakes.pdfs import make_pdf, make_scanned_pdf
from smart_tutor.knowledge.adapters.pypdf_extractor import PypdfExtractor
from smart_tutor.knowledge.domain.content import has_text_layer
from smart_tutor.knowledge.ports.pdf_extractor import TooManyPagesError, UnreadablePdfError


def test_extracts_one_text_per_page_with_blank_pages_kept() -> None:
    pages = PypdfExtractor().extract_pages(make_pdf(["Hello page one", "", "Page three"]), 500)

    assert len(pages) == 3
    assert "Hello page one" in pages[0]
    assert pages[1].strip() == ""
    assert "Page three" in pages[2]


def test_keeps_line_breaks_and_escaped_characters() -> None:
    pages = PypdfExtractor().extract_pages(make_pdf(["Line (one)\nback\\slash"]), 500)

    assert "Line (one)" in pages[0]
    assert "back\\slash" in pages[0]


@pytest.mark.parametrize("data", [b"not a pdf", make_pdf(["Hello"])[:40], b""])
def test_unreadable_bytes_raise(data: bytes) -> None:
    with pytest.raises(UnreadablePdfError):
        PypdfExtractor().extract_pages(data, 500)


def test_encrypted_pdf_raises() -> None:
    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_pdf(["Secret"]))))
    writer.encrypt("pw")
    out = BytesIO()
    writer.write(out)

    with pytest.raises(UnreadablePdfError):
        PypdfExtractor().extract_pages(out.getvalue(), 500)


@pytest.mark.parametrize("error", [KeyError("/DescendantFonts"), AttributeError("get_object"), TypeError("bad")])
def test_any_parser_exception_becomes_unreadable(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def broken(self: PageObject, *args: object, **kwargs: object) -> str:
        raise error

    monkeypatch.setattr(PageObject, "extract_text", broken)

    with pytest.raises(UnreadablePdfError) as raised:
        PypdfExtractor().extract_pages(make_pdf(["Hello"]), 500)
    assert raised.value.__cause__ is error


def test_a_scanned_pdf_has_pages_but_no_text() -> None:
    pages = PypdfExtractor().extract_pages(make_scanned_pdf(3), 500)

    assert len(pages) == 3
    assert not has_text_layer(pages)


def test_more_pages_than_the_limit_raise_before_reading_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def never(self: PageObject, *args: object, **kwargs: object) -> str:
        raise AssertionError("text was extracted")

    monkeypatch.setattr(PageObject, "extract_text", never)

    with pytest.raises(TooManyPagesError) as raised:
        PypdfExtractor().extract_pages(make_pdf(["p"] * 4), 3)
    assert raised.value.pages == 4


def test_exactly_the_limit_is_accepted() -> None:
    assert len(PypdfExtractor().extract_pages(make_pdf(["p"] * 3), 3)) == 3
