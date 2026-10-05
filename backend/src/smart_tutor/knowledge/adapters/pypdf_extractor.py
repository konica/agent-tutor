"""PdfExtractor on pypdf (ADR 0005)."""

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from smart_tutor.knowledge.ports.pdf_extractor import PdfExtractor, UnreadablePdfError


class PypdfExtractor(PdfExtractor):
    def extract_pages(self, data: bytes) -> list[str]:
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise UnreadablePdfError("The PDF is encrypted.")
            return [page.extract_text() or "" for page in reader.pages]
        except (PyPdfError, ValueError) as error:
            raise UnreadablePdfError(str(error)) from error
