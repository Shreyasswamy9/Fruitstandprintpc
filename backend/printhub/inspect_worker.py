"""Isolated document inspector.

Run as a separate process (`python -I inspect_worker.py ...`) with CPU,
memory and wall-clock limits so that a malformed or hostile upload cannot
stall or crash the service. It never trusts the original filename: the
type is decided from the file's content.

Prints one JSON object on stdout:
  {"ok": true, "kind": "pdf"|"image", "mime": ..., "pages": n, "width_pt": w,
   "height_pt": h, "notes": [...], "print_name": optional, "print_mime": optional}
  {"ok": false, "code": ..., "message": ...}
"""
import json
import sys
from pathlib import Path


def sniff(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if b"%PDF-" in head[:1024]:
        return "application/pdf"
    return None


def fail(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "message": message}


def inspect_pdf(path: Path, max_pages: int) -> dict:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            return fail(
                "pdf_encrypted",
                "This PDF is password-protected or encrypted. Save an unprotected copy and upload that instead.",
            )
        pages = len(reader.pages)
        if pages == 0:
            return fail("pdf_empty", "This PDF has no pages.")
        if pages > max_pages:
            return fail("pdf_too_many_pages", f"This PDF has {pages} pages. The limit is {max_pages} pages per file.")
        first = reader.pages[0]
        box = first.mediabox
        width, height = float(box.width), float(box.height)
        rotate = int(first.get("/Rotate", 0) or 0) % 360
        if rotate in (90, 270):
            width, height = height, width
        notes = []
        sizes = set()
        for page in reader.pages[: min(pages, 50)]:
            b = page.mediabox
            sizes.add((round(float(b.width)), round(float(b.height))))
        if len(sizes) > 1:
            notes.append("Pages in this PDF have different sizes; each page is scaled to the selected paper.")
        return {
            "ok": True,
            "kind": "pdf",
            "mime": "application/pdf",
            "pages": pages,
            "width_pt": round(width, 2),
            "height_pt": round(height, 2),
            "notes": notes,
        }
    except PdfReadError as exc:
        return fail("pdf_unreadable", f"This PDF could not be read ({str(exc)[:120]}).")


def inspect_image(path: Path, mime: str, max_pixels: int, out_dir: Path, file_id: str) -> dict:
    from PIL import Image, ImageOps, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            fmt = (img.format or "").upper()
            expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[mime]
            if fmt != expected:
                return fail("image_mismatch", "The image data does not match its file signature.")
            width, height = img.size
            if width * height > max_pixels:
                return fail("image_too_large", f"This image is {width}×{height} pixels, larger than the supported limit.")
            img.load()
            notes = []
            frames = getattr(img, "n_frames", 1)
            if frames > 1:
                notes.append(f"This is an animated image with {frames} frames. Only the first frame will print.")
            dpi = img.info.get("dpi")
            orientation = img.getexif().get(0x0112, 1)
            needs_copy = mime == "image/webp" or orientation not in (1, None)
            print_name = print_mime = None
            if needs_copy:
                out = ImageOps.exif_transpose(img) if orientation not in (1, None) else img.copy()
                if out.mode not in ("RGB", "RGBA", "L", "LA"):
                    out = out.convert("RGBA" if "A" in out.mode else "RGB")
                print_name = f"{file_id}.print.png"
                out.save(out_dir / print_name, format="PNG")
                print_mime = "image/png"
                if mime == "image/webp":
                    notes.append(
                        "WebP is not accepted by the print system, so a lossless PNG copy with identical pixels is sent instead."
                    )
                if orientation not in (1, None):
                    notes.append("The camera rotation tag was applied so the image prints the same way it appears in the preview.")
                    width, height = out.size
            if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
                notes.append("Transparent areas print as blank paper.")
            ppi = float(dpi[0]) if dpi and dpi[0] else None
            return {
                "ok": True,
                "kind": "image",
                "mime": mime,
                "pages": 1,
                "width_px": width,
                "height_px": height,
                "ppi": round(ppi, 1) if ppi else None,
                "width_pt": round(width / ppi * 72, 2) if ppi else None,
                "height_pt": round(height / ppi * 72, 2) if ppi else None,
                "notes": notes,
                "print_name": print_name,
                "print_mime": print_mime,
            }
    except Image.DecompressionBombError:
        return fail("image_too_large", "This image has too many pixels to process safely.")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        return fail("image_unreadable", f"This image could not be read ({str(exc)[:120]}).")


def main(argv: list[str]) -> int:
    path, max_pages, max_pixels, out_dir, file_id = Path(argv[1]), int(argv[2]), int(argv[3]), Path(argv[4]), argv[5]
    with open(path, "rb") as fh:
        head = fh.read(2048)
    mime = sniff(head)
    if mime is None:
        result = fail(
            "unsupported_type", "This file type isn't supported. Upload a PDF, JPEG, PNG or WebP file."
        )
    elif mime == "application/pdf":
        result = inspect_pdf(path, max_pages)
    else:
        result = inspect_image(path, mime, max_pixels, out_dir, file_id)
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except MemoryError:
        sys.stdout.write(json.dumps(fail("too_complex", "This file needs more memory to process than is allowed.")))
        sys.exit(0)
