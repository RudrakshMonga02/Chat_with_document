"""
extractors.py — Factory Pattern for document text extraction.

Why a factory here?
-------------------
Previously extract_text() in rag.py had a growing if/elif chain:
    if name.endswith(".pdf"): ...
    elif name.endswith(".txt"): ...

Every new file type meant editing that function and risking breakage of
the others. The Factory Pattern fixes this by:

  1. Giving each file type its own class (PDFExtractor, TXTExtractor) — each
     is isolated and independently testable.
  2. A single factory function (get_extractor) maps extension → class. Adding
     .docx support in the future is just adding one new class and one line in
     the factory — nothing else changes.

How to add a new file type (e.g. .docx):
  - Create class DOCXExtractor with an extract(file) -> str method.
  - Add ".docx": DOCXExtractor to the EXTRACTORS dict below. Done.
"""

from abc import ABC, abstractmethod

from pypdf import PdfReader


# ---------------------------------------------------------------------------
# Base interface — every extractor must implement extract()
# ---------------------------------------------------------------------------
class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, django_file) -> str:
        """Pull plain text out of a Django uploaded file object."""


# ---------------------------------------------------------------------------
# Concrete extractors — one per supported file type
# ---------------------------------------------------------------------------
class PDFExtractor(BaseExtractor):
    def extract(self, django_file) -> str:
        reader = PdfReader(django_file)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)


class TXTExtractor(BaseExtractor):
    def extract(self, django_file) -> str:
        raw = django_file.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        return raw


# ---------------------------------------------------------------------------
# Factory — maps file extension to the right extractor class
# ---------------------------------------------------------------------------
EXTRACTORS: dict[str, type[BaseExtractor]] = {
    ".pdf": PDFExtractor,
    ".txt": TXTExtractor,
}


def get_extractor(filename: str) -> BaseExtractor:
    """
    Return the correct extractor instance for a given filename.
    Raises ValueError for unsupported extensions.
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    extractor_class = EXTRACTORS.get(ext)
    if not extractor_class:
        supported = ", ".join(EXTRACTORS.keys())
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported types: {supported}."
        )
    return extractor_class()
