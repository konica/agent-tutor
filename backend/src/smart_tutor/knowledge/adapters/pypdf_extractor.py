"""PdfExtractor on pypdf (ADR 0005)."""

from io import BytesIO

from pypdf import PdfReader

from smart_tutor.knowledge.ports.pdf_extractor import PdfExtractor, UnreadablePdfError


class PypdfExtractor(PdfExtractor):
    def extract_pages(self, data: bytes) -> list[str]:
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise UnreadablePdfError("The PDF is encrypted.")
            return [page.extract_text() or "" for page in reader.pages]
        except UnreadablePdfError:
            raise
        except Exception as error:
            # pypdf raises more than PyPdfError on corrupt files (KeyError, AttributeError, TypeError, ...).
            # A crash here would leave the document processing forever, so any parse failure is "unreadable".
            raise UnreadablePdfError(f"{type(error).__name__}: {error}") from error
