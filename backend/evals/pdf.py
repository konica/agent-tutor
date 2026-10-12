"""A text-only PDF for generated seed documents (the canary documents, #194): Helvetica, wrapped lines, one page per
PAGE_LINES lines, and no dates or ids, so the same text always gives the same bytes and its SHA-256 can be pinned in
the manifest like a downloaded document's. Paragraphs are separated by blank lines; the text must be ASCII."""

import textwrap

LINE_CHARS = 90
PAGE_LINES = 48


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _lines(text: str) -> list[str]:
    lines: list[str] = []
    for paragraph in text.strip().split("\n\n"):
        lines += textwrap.wrap(" ".join(paragraph.split()), LINE_CHARS)
        lines.append("")
    return lines[:-1]


def text_pdf(text: str) -> bytes:
    lines = _lines(text)
    pages = [lines[i : i + PAGE_LINES] for i in range(0, len(lines), PAGE_LINES)] or [[]]
    count = len(pages)
    font_id = 3 + 2 * count
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode())
    for i, page in enumerate(pages):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {4 + 2 * i} 0 R >>"
            ).encode()
        )
        shown = " T* ".join(f"({_escape(line)}) Tj" for line in page)
        stream = f"BT /F1 11 Tf 56 740 Td 14 TL {shown} ET".encode("ascii")
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)
