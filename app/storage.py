"""
Cloud storage abstraction — S3-compatible (AWS S3, Cloudflare R2, DigitalOcean Spaces).
Falls back to local filesystem when S3 is not configured.
"""

import io
import logging
import os
import pathlib
import uuid

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Image processing constants
IMAGE_MAX_DIMENSION = 2048
JPEG_QUALITY = 85

# S3 config from environment
S3_BUCKET = os.getenv("S3_BUCKET_NAME", "")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY_ID", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "")
S3_ENDPOINT = os.getenv("S3_ENDPOINT_URL", "")  # e.g. https://xxx.r2.cloudflarestorage.com
S3_REGION = os.getenv("S3_REGION", "auto")
S3_PUBLIC_URL = os.getenv("S3_PUBLIC_URL", "")  # e.g. https://cdn.primehaul.co.uk

_s3_client = None


def _get_s3():
    """Lazy-initialise the S3 client."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    if not all([S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY]):
        return None
    kwargs = {
        "aws_access_key_id": S3_ACCESS_KEY,
        "aws_secret_access_key": S3_SECRET_KEY,
        "region_name": S3_REGION,
    }
    if S3_ENDPOINT:
        kwargs["endpoint_url"] = S3_ENDPOINT
    _s3_client = boto3.client("s3", **kwargs)
    return _s3_client


def is_cloud_storage() -> bool:
    return _get_s3() is not None


def _process_image(file_bytes: bytes) -> tuple[bytes, int, int]:
    """Process raw upload bytes → optimised JPEG bytes. Returns (jpeg_bytes, width, height)."""
    img = Image.open(io.BytesIO(file_bytes))

    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    max_side = max(img.size)
    if max_side > IMAGE_MAX_DIMENSION:
        ratio = IMAGE_MAX_DIMENSION / max_side
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue(), img.width, img.height


def upload_photo(token: str, file_bytes: bytes, original_filename: str) -> dict:
    """
    Process and upload a photo.  Uses S3 if configured, otherwise falls back
    to the local filesystem under app/static/uploads/.

    Returns a metadata dict compatible with LeadPhoto columns.
    """
    jpeg_bytes, w, h = _process_image(file_bytes)
    unique_name = uuid.uuid4().hex + ".jpg"
    s3_key = f"leads/{token}/{unique_name}"
    s3 = _get_s3()

    if s3:
        try:
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=jpeg_bytes,
                ContentType="image/jpeg",
                CacheControl="public, max-age=86400",
            )
            if S3_PUBLIC_URL:
                public_url = f"{S3_PUBLIC_URL.rstrip('/')}/{s3_key}"
            else:
                public_url = f"/photo/leads/{token}/{unique_name}"

            return {
                "filename": unique_name,
                "original_filename": original_filename,
                "storage_path": f"s3://{S3_BUCKET}/{s3_key}",
                "file_size_bytes": len(jpeg_bytes),
                "mime_type": "image/jpeg",
                "public_url": public_url,
            }
        except (ClientError, NoCredentialsError) as exc:
            logger.error("S3 upload failed, falling back to local: %s", exc)
            # Fall through to local storage

    # Local filesystem fallback
    base_dir = pathlib.Path(__file__).resolve().parent
    upload_dir = base_dir / "static" / "uploads" / "leads" / token
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / unique_name
    dest.write_bytes(jpeg_bytes)

    return {
        "filename": unique_name,
        "original_filename": original_filename,
        "storage_path": str(dest),
        "file_size_bytes": len(jpeg_bytes),
        "mime_type": "image/jpeg",
        "public_url": f"/photo/leads/{token}/{unique_name}",
    }


def get_photo_bytes(storage_path: str) -> bytes | None:
    """
    Read photo bytes from S3 or local filesystem.
    Used by ai_vision.py to feed images to OpenAI.
    """
    if storage_path.startswith("s3://"):
        s3 = _get_s3()
        if not s3:
            logger.error("S3 not configured but storage_path is s3://")
            return None
        # Parse s3://bucket/key
        parts = storage_path[5:].split("/", 1)
        bucket, key = parts[0], parts[1]
        try:
            resp = s3.get_object(Bucket=bucket, Key=key)
            return resp["Body"].read()
        except ClientError as exc:
            logger.error("Failed to read from S3: %s", exc)
            return None
    else:
        # Local file path
        path = pathlib.Path(storage_path)
        if path.is_file():
            return path.read_bytes()
        return None


def get_photo_url(token: str, filename: str, storage_path: str = "") -> str | None:
    """
    Get a servable URL for a photo.
    For S3 with public URL configured, returns the CDN URL.
    For local storage, returns the internal route path.
    """
    if storage_path.startswith("s3://") and S3_PUBLIC_URL:
        return f"{S3_PUBLIC_URL.rstrip('/')}/leads/{token}/{filename}"

    if storage_path.startswith("s3://") and not S3_PUBLIC_URL:
        # Generate a presigned URL (1 hour expiry)
        s3 = _get_s3()
        if s3:
            key = f"leads/{token}/{filename}"
            try:
                return s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": S3_BUCKET, "Key": key},
                    ExpiresIn=3600,
                )
            except ClientError:
                pass

    # Fallback — serve via our own route
    return f"/photo/leads/{token}/{filename}"


def delete_photo(storage_path: str) -> bool:
    """Delete a photo from S3 or local filesystem."""
    if storage_path.startswith("s3://"):
        s3 = _get_s3()
        if not s3:
            return False
        parts = storage_path[5:].split("/", 1)
        bucket, key = parts[0], parts[1]
        try:
            s3.delete_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            logger.error("Failed to delete from S3: %s", exc)
            return False
    else:
        path = pathlib.Path(storage_path)
        if path.is_file():
            path.unlink()
            return True
        return False
