"""Bounded basic file validation; no malware scanning is performed."""

import io
import warnings
from pathlib import PurePosixPath

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.errors import DomainError

TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def validate(data: bytes, filename: str, declared_type: str, limit: int) -> tuple[str, str]:
    name = filename.strip()
    if (
        not name
        or len(name) > 180
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
        or any(c in name for c in "/\\")
        or name in {".", ".."}
    ):
        raise DomainError(
            "VALIDATION_FAILED",
            "Use a filename of 1–180 characters without paths or control characters.",
            422,
        )
    kind = TYPES.get(PurePosixPath(name).suffix.lower())
    if not kind or declared_type != kind:
        raise DomainError(
            "VALIDATION_FAILED", "Upload a PDF, PNG or JPEG with a matching file type.", 422
        )
    if not data or len(data) > limit:
        raise DomainError(
            "VALIDATION_FAILED", "The file is empty or exceeds the upload size limit.", 422
        )
    try:
        if kind == "application/pdf":
            if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
                raise ValueError("Invalid PDF")
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted or not len(reader.pages) or len(reader.pages) > 200:
                raise ValueError("Encrypted or excessive PDF")
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.width * image.height > 20_000_000 or image.format != (
                        "PNG" if kind == "image/png" else "JPEG"
                    ):
                        raise ValueError("Invalid image")
                    image.verify()
    except (
        ValueError,
        SyntaxError,
        OSError,
        PdfReadError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise DomainError(
            "VALIDATION_FAILED",
            "The document is malformed, encrypted or exceeds the content limits.",
            422,
        ) from exc
    return name, kind
