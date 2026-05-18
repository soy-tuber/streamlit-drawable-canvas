"""Composite background + handwriting strokes into shareable PNG / PDF."""

import io

from PIL import Image

DEFAULT_SIZE = (1280, 800)


def _flatten(page_row) -> Image.Image:
    """Compose one page (background + strokes raster) into an RGB Pillow image."""
    bg_bytes = page_row.get("bg_data")
    strokes_bytes = page_row.get("image_png")

    if strokes_bytes:
        strokes = Image.open(io.BytesIO(strokes_bytes)).convert("RGBA")
    else:
        strokes = None

    if bg_bytes:
        bg = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
        if strokes is not None:
            if strokes.size != bg.size:
                strokes = strokes.resize(bg.size, Image.LANCZOS)
            bg.alpha_composite(strokes)
        out = bg
    elif strokes is not None:
        canvas = Image.new("RGBA", strokes.size, (255, 255, 255, 255))
        canvas.alpha_composite(strokes)
        out = canvas
    else:
        out = Image.new("RGBA", DEFAULT_SIZE, (255, 255, 255, 255))

    return out.convert("RGB")


def page_png(page_row) -> bytes:
    """Return PNG bytes for a single board page row."""
    img = _flatten(page_row)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def board_pdf(pages) -> bytes:
    """Render multiple pages into a single PDF (one page per board page)."""
    if not pages:
        raise ValueError("no pages to export")
    imgs = [_flatten(p) for p in pages]
    buf = io.BytesIO()
    first, rest = imgs[0], imgs[1:]
    first.save(buf, format="PDF", save_all=True, append_images=rest, resolution=150.0)
    return buf.getvalue()


__all__ = ["page_png", "board_pdf"]
