"""Generated seed documents: a text PDF that pypdf reads back and that is the same bytes every time."""

import io

from pypdf import PdfReader

from evals.pdf import text_pdf

TEXT = "Field notes (CANARY-1)\n\n" + "\n\n".join(f"Paragraph {i} mentions CANARY-1 and agents." for i in range(80))


def test_a_text_pdf_reads_back_through_pypdf() -> None:
    reader = PdfReader(io.BytesIO(text_pdf(TEXT)))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Field notes (CANARY-1)" in text
    assert "Paragraph 79 mentions CANARY-1" in text


def test_long_text_breaks_into_pages_each_above_the_scan_threshold() -> None:
    reader = PdfReader(io.BytesIO(text_pdf(TEXT)))
    assert len(reader.pages) > 1
    assert all(len("".join(p.extract_text().split())) >= 50 for p in reader.pages)  # MIN_AVERAGE_CHARS


def test_long_lines_are_wrapped() -> None:
    reader = PdfReader(io.BytesIO(text_pdf("word " * 200)))
    lines = reader.pages[0].extract_text().splitlines()
    assert len(lines) > 1 and all(len(line) <= 90 for line in lines)


def test_the_same_text_gives_the_same_bytes() -> None:
    assert text_pdf(TEXT) == text_pdf(TEXT)
