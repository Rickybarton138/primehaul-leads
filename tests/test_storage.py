"""Tests for the storage module (local filesystem fallback)."""

import io
from PIL import Image

from app.storage import upload_photo, get_photo_bytes, is_cloud_storage


def _make_test_image(width=100, height=100):
    """Create a minimal test JPEG image."""
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_is_cloud_storage_false_without_config():
    """Without S3 env vars, should use local storage."""
    assert is_cloud_storage() is False


def test_upload_photo_local_fallback():
    """Upload should succeed using local filesystem when S3 is not configured."""
    image_bytes = _make_test_image()
    meta = upload_photo("testtoken99", image_bytes, "test_photo.jpg")

    assert meta["filename"].endswith(".jpg")
    assert meta["original_filename"] == "test_photo.jpg"
    assert meta["mime_type"] == "image/jpeg"
    assert meta["file_size_bytes"] > 0
    assert "testtoken99" in meta["storage_path"]

    # Should be able to read it back
    content = get_photo_bytes(meta["storage_path"])
    assert content is not None
    assert len(content) > 0


def test_upload_photo_processes_image():
    """Upload should resize large images."""
    # Create a large image
    image_bytes = _make_test_image(4000, 3000)
    meta = upload_photo("testtoken_big", image_bytes, "big_photo.jpg")

    # Verify it was processed (file size should be reasonable)
    assert meta["file_size_bytes"] > 0
    assert meta["file_size_bytes"] < len(image_bytes)  # Should be smaller after compression


def test_get_photo_bytes_nonexistent():
    """Reading a nonexistent path should return None."""
    result = get_photo_bytes("/nonexistent/path/photo.jpg")
    assert result is None


def test_get_photo_bytes_s3_without_config():
    """Reading an s3:// path without config should return None."""
    result = get_photo_bytes("s3://fakebucket/leads/token/photo.jpg")
    assert result is None
