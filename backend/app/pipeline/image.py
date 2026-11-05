"""Image preparation: orientation, GPS stripping, resizing, sharpness score, code decoding."""

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageOps, ImageStat
from pillow_heif import register_heif_opener

register_heif_opener()

# Refuse "decompression bombs": tiny files that expand to huge images in memory.
Image.MAX_IMAGE_PIXELS = 60_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)

MAX_SIDE = 2000
ACCEPTED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


class UnsupportedImage(ValueError):
    pass


@dataclass
class PreparedImage:
    data: bytes
    media_type: str
    width: int
    height: int
    sharpness: float


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(raw: bytes) -> PreparedImage:
    """Return a JPEG with orientation applied, metadata removed and the long side capped."""
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
    except Exception as e:  # Pillow raises several unrelated types for bad input
        raise UnsupportedImage("This file isn't an image we can read") from e
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    # Re-encoding without exif drops GPS and device metadata.
    img.save(out, format="JPEG", quality=90, optimize=True)
    return PreparedImage(out.getvalue(), "image/jpeg", img.width, img.height, sharpness(img))


def sharpness(img: Image.Image) -> float:
    """Variance of edges on a grayscale copy: low values suggest blur."""
    gray = img.convert("L")
    gray.thumbnail((1000, 1000))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).var[0])


def decode_codes(data: bytes) -> list[str]:
    """Decode QR codes and barcodes when the optional zbar library is installed."""
    try:
        from pyzbar.pyzbar import decode  # type: ignore[import-not-found]
    except ImportError:
        return []
    try:
        img = Image.open(io.BytesIO(data))
        return [r.data.decode("utf-8", "replace") for r in decode(img)]
    except Exception:  # noqa: BLE001 - decoding is best effort
        return []
