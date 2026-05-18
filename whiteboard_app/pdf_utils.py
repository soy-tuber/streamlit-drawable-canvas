"""PDF helpers — rasterise PDF pages so we can use them as canvas backgrounds."""

import io

try:
    import fitz  # PyMuPDF
except ImportError as e:
    fitz = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def pdf_page_count(pdf_bytes: bytes) -> int:
    _ensure()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return doc.page_count
    finally:
        doc.close()


def render_page(pdf_bytes: bytes, page_index: int, dpi: int = 150) -> bytes:
    """Return a PNG byte string for the requested 0-based page."""
    _ensure()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if page_index < 0 or page_index >= doc.page_count:
            raise IndexError(f"page_index {page_index} out of range (0..{doc.page_count - 1})")
        page = doc.load_page(page_index)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def render_all_pages(pdf_bytes: bytes, dpi: int = 150):
    _ensure()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        for page in doc:
            pix = page.get_pixmap(matrix=mat, alpha=False)
            yield pix.tobytes("png")
    finally:
        doc.close()


def png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Read PNG width/height from the IHDR chunk without Pillow."""
    if len(png_bytes) < 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    w = int.from_bytes(png_bytes[16:20], "big")
    h = int.from_bytes(png_bytes[20:24], "big")
    return w, h


def _ensure():
    if fitz is None:
        raise RuntimeError(
            "PyMuPDF (pymupdf) is required for PDF backgrounds. "
            "Install with: pip install pymupdf"
        ) from _IMPORT_ERR


__all__ = ["pdf_page_count", "render_page", "render_all_pages", "png_dimensions"]
