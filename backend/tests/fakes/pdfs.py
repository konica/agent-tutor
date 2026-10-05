"""A minimal valid PDF for tests: one Helvetica font, one text line per `Tj`."""


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str]) -> bytes:
    """A PDF with one page per string (newlines start new lines; an empty string is a blank page)."""
    count = len(pages)
    font_id = 3 + 2 * count
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode())
    for i, text in enumerate(pages):
        content_id = 4 + 2 * i
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        if text:
            lines = " T* ".join(f"({_escape(line)}) Tj" for line in text.split("\n"))
            stream = f"BT /F1 12 Tf 72 720 Td 14 TL {lines} ET".encode("latin-1")
        else:
            stream = b""
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    return _assemble(objects)


def make_scanned_pdf(pages: int) -> bytes:
    """A scan: each page is one full-page grey image and has no text layer (PRD M0 note: tested in US-2)."""
    image = bytes(range(0, 256, 4))  # 8x8 8-bit greys
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    image_id = 3 + 2 * pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(pages))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    draw = b"q 612 0 0 792 0 0 cm /Im1 Do Q"
    for i in range(pages):
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /XObject << /Im1 {image_id} 0 R >> >> /Contents {4 + 2 * i} 0 R >>"
            ).encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(draw) + draw + b"\nendstream")
    objects.append(
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length %d >>\nstream\n" % len(image) + image + b"\nendstream"
    )
    return _assemble(objects)


def _assemble(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)
