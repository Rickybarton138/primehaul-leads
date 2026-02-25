"""
PrimeHaul Leads -- Main FastAPI application.

Consumer-facing survey flow that collects move details, room photos,
generates an AI-analysed inventory with instant price estimate,
then captures contact details as a qualified lead for removal companies.
"""

import asyncio
import logging
import os
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from sqlalchemy.orm import Session, joinedload

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.ai_vision import extract_removal_inventory
from app.config import settings
from app.database import get_db
from app.rate_limit import limiter
from app.geo import calculate_distance_miles
from app.models import Lead, LeadItem, LeadPhoto, LeadRoom
from app.pricing import calculate_lead_estimate, calculate_lead_price_pence

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("primehaul")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}
MAX_PHOTOS_PER_ROOM = 6
IMAGE_MAX_DIMENSION = 2048
JPEG_QUALITY = 85
LEAD_EXPIRY_DAYS = 14

# Progress percentages for the survey progress bar
PROGRESS = {
    "map": 10,
    "property": 20,
    "access": 35,
    "move_date": 45,
    "rooms": 55,
    "photos": 65,
    "review": 80,
    "estimate": 90,
    "contact": 95,
}

# Base directory for file uploads (relative to project root)
BASE_DIR = pathlib.Path(__file__).resolve().parent
UPLOAD_ROOT = BASE_DIR / "static" / "uploads"


def _safe_float(val, default=None):
    """Safely convert AI response values to float for database storage."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val, default=1):
    """Safely convert AI response values to int for database storage."""
    if val is None:
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PrimeHaul Leads",
    description="Lead generation platform for UK removal companies",
    version="1.0.0",
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Global error handler — log full tracebacks and return a user-friendly page
@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled 500 error on %s %s", request.method, request.url.path)
    return templates.TemplateResponse(
        "base.html",
        {"request": request, "error": "Something went wrong. Please try again."},
        status_code=500,
    )

# Static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Jinja2 templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ---------------------------------------------------------------------------
# Include sub-routers (company & admin panels)
# ---------------------------------------------------------------------------
from app.company_routes import router as company_router  # noqa: E402
from app.admin_routes import router as admin_router  # noqa: E402

app.include_router(company_router)
app.include_router(admin_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Liveness / readiness probe — verifies the DB connection is working."""
    from sqlalchemy import text

    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


# ---------------------------------------------------------------------------
# Helper: resolve a Lead by its public token or raise 404
# ---------------------------------------------------------------------------
def get_lead_or_404(token: str, db: Session) -> Lead:
    """Look up a Lead by its public survey token, raising HTTP 404 if missing."""
    lead = (
        db.query(Lead)
        .options(
            joinedload(Lead.rooms).joinedload(LeadRoom.items),
            joinedload(Lead.rooms).joinedload(LeadRoom.photos),
        )
        .filter(Lead.token == token)
        .first()
    )
    if lead is None:
        raise HTTPException(status_code=404, detail="Survey not found")
    return lead


# ---------------------------------------------------------------------------
# Helper: process and save an uploaded image
# ---------------------------------------------------------------------------
def _process_and_save_image(
    upload_dir: pathlib.Path,
    file_bytes: bytes,
    original_filename: str,
) -> dict:
    """
    Resize an image to fit within IMAGE_MAX_DIMENSION, convert to JPEG,
    and save to *upload_dir*.  Returns metadata dict.
    """
    import io

    unique_name = uuid.uuid4().hex + ".jpg"
    dest = upload_dir / unique_name

    img = Image.open(io.BytesIO(file_bytes))

    # Handle EXIF orientation so the saved file is right-side-up
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    # Convert palette / RGBA images to RGB for JPEG output
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    # Resize if the longest side exceeds the limit
    max_side = max(img.size)
    if max_side > IMAGE_MAX_DIMENSION:
        ratio = IMAGE_MAX_DIMENSION / max_side
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    img.save(str(dest), format="JPEG", quality=JPEG_QUALITY, optimize=True)

    file_size = dest.stat().st_size

    return {
        "filename": unique_name,
        "original_filename": original_filename,
        "storage_path": str(dest),
        "file_size_bytes": file_size,
        "mime_type": "image/jpeg",
    }


# ===================================================================
#  CONSUMER SURVEY ROUTES
# ===================================================================

# 1. Landing page
# -------------------------------------------------------------------
@app.get("/")
async def landing(request: Request):
    return templates.TemplateResponse("consumer/landing.html", {"request": request})


# 2. Start a new survey
# -------------------------------------------------------------------
@app.get("/start")
async def start_survey(request: Request, db: Session = Depends(get_db)):
    """Create a brand-new Lead with a unique short token and capture UTM params."""
    token = uuid.uuid4().hex[:12]

    lead = Lead(
        token=token,
        utm_source=request.query_params.get("utm_source"),
        utm_medium=request.query_params.get("utm_medium"),
        utm_campaign=request.query_params.get("utm_campaign"),
    )
    db.add(lead)
    db.commit()

    return RedirectResponse(url=f"/survey/{token}/map", status_code=303)


# -------------------------------------------------------------------
# 3 & 4. Map -- pickup / drop-off locations
# -------------------------------------------------------------------
@app.get("/survey/{token}/map")
async def survey_map(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)
    return templates.TemplateResponse(
        "consumer/move_map.html",
        {
            "request": request,
            "token": token,
            "lead": lead,
            "mapbox_token": settings.MAPBOX_ACCESS_TOKEN,
            "progress": PROGRESS["map"],
        },
    )


@app.post("/survey/{token}/map")
async def survey_map_post(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)
    form = await request.form()

    pickup_lat = float(form.get("pickup_lat", 0))
    pickup_lng = float(form.get("pickup_lng", 0))
    dropoff_lat = float(form.get("dropoff_lat", 0))
    dropoff_lng = float(form.get("dropoff_lng", 0))

    lead.pickup = {
        "label": form.get("pickup_label", ""),
        "lat": pickup_lat,
        "lng": pickup_lng,
        "postcode": form.get("pickup_postcode", ""),
        "city": form.get("pickup_city", ""),
    }
    lead.dropoff = {
        "label": form.get("dropoff_label", ""),
        "lat": dropoff_lat,
        "lng": dropoff_lng,
        "postcode": form.get("dropoff_postcode", ""),
        "city": form.get("dropoff_city", ""),
    }

    lead.distance_miles = calculate_distance_miles(
        pickup_lat, pickup_lng, dropoff_lat, dropoff_lng
    )

    db.commit()
    return RedirectResponse(url=f"/survey/{token}/property", status_code=303)


# -------------------------------------------------------------------
# 5 & 6. Property type
# -------------------------------------------------------------------
@app.get("/survey/{token}/property")
async def survey_property(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)
    return templates.TemplateResponse(
        "consumer/property_type.html",
        {
            "request": request,
            "token": token,
            "lead": lead,
            "progress": PROGRESS["property"],
        },
    )


@app.post("/survey/{token}/property")
async def survey_property_post(
    token: str, request: Request, db: Session = Depends(get_db)
):
    lead = get_lead_or_404(token, db)
    form = await request.form()

    lead.property_type = form.get("property_type", "")
    lead.dropoff_property_type = form.get("dropoff_property_type", "")

    db.commit()
    return RedirectResponse(url=f"/survey/{token}/access", status_code=303)


# -------------------------------------------------------------------
# 7 & 8. Access details (floors, lift, parking, etc.)
# -------------------------------------------------------------------
@app.get("/survey/{token}/access")
async def survey_access(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)
    return templates.TemplateResponse(
        "consumer/access.html",
        {
            "request": request,
            "token": token,
            "lead": lead,
            "progress": PROGRESS["access"],
        },
    )


@app.post("/survey/{token}/access")
async def survey_access_post(
    token: str, request: Request, db: Session = Depends(get_db)
):
    lead = get_lead_or_404(token, db)
    form = await request.form()

    # Build pickup access JSONB from individual form fields
    lead.pickup_access = {
        "floors": int(form.get("pickup_floors", 0) or 0),
        "has_lift": form.get("pickup_has_lift") == "true",
        "parking_type": form.get("pickup_parking_type", "driveway"),
        "parking_distance_m": int(form.get("pickup_parking_distance_m", 0) or 0),
        "narrow_access": form.get("pickup_narrow_access") == "true",
        "time_restriction": form.get("pickup_time_restriction") == "true",
        "booking_required": form.get("pickup_booking_required") == "true",
        "outdoor_steps": int(form.get("pickup_outdoor_steps", 0) or 0),
        "outdoor_path": form.get("pickup_outdoor_path") == "true",
    }

    # Build drop-off access JSONB
    lead.dropoff_access = {
        "floors": int(form.get("dropoff_floors", 0) or 0),
        "has_lift": form.get("dropoff_has_lift") == "true",
        "parking_type": form.get("dropoff_parking_type", "driveway"),
        "parking_distance_m": int(form.get("dropoff_parking_distance_m", 0) or 0),
        "narrow_access": form.get("dropoff_narrow_access") == "true",
        "time_restriction": form.get("dropoff_time_restriction") == "true",
        "booking_required": form.get("dropoff_booking_required") == "true",
        "outdoor_steps": int(form.get("dropoff_outdoor_steps", 0) or 0),
        "outdoor_path": form.get("dropoff_outdoor_path") == "true",
    }

    db.commit()
    return RedirectResponse(url=f"/survey/{token}/move-date", status_code=303)


# -------------------------------------------------------------------
# 9 & 10. Move date
# -------------------------------------------------------------------
@app.get("/survey/{token}/move-date")
async def survey_move_date(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)
    return templates.TemplateResponse(
        "consumer/move_date.html",
        {
            "request": request,
            "token": token,
            "lead": lead,
            "progress": PROGRESS["move_date"],
        },
    )


@app.post("/survey/{token}/move-date")
async def survey_move_date_post(
    token: str, request: Request, db: Session = Depends(get_db)
):
    lead = get_lead_or_404(token, db)
    form = await request.form()

    date_str = form.get("move_date", "")
    if date_str:
        try:
            lead.move_date = datetime.fromisoformat(date_str).replace(
                tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            # Gracefully handle malformed dates -- leave the field unchanged
            logger.warning("Invalid move_date value: %s", date_str)

    db.commit()
    return RedirectResponse(url=f"/survey/{token}/rooms", status_code=303)


# -------------------------------------------------------------------
# 11, 12 & 13. Room selection
# -------------------------------------------------------------------
@app.get("/survey/{token}/rooms")
async def survey_rooms(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)
    return templates.TemplateResponse(
        "consumer/rooms_pick.html",
        {
            "request": request,
            "token": token,
            "lead": lead,
            "rooms": lead.rooms,
            "progress": PROGRESS["rooms"],
        },
    )


@app.post("/survey/{token}/rooms/add")
async def survey_rooms_add(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)
    form = await request.form()

    room_name = (form.get("name", "") or "").strip()
    if not room_name:
        return RedirectResponse(url=f"/survey/{token}/rooms", status_code=303)

    room = LeadRoom(lead_id=lead.id, name=room_name)
    db.add(room)
    db.commit()

    return RedirectResponse(url=f"/survey/{token}/rooms", status_code=303)


@app.post("/survey/{token}/rooms/remove")
async def survey_rooms_remove(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)
    form = await request.form()
    room_name = (form.get("name", "") or "").strip()
    if room_name:
        room = db.query(LeadRoom).filter(
            LeadRoom.lead_id == lead.id, LeadRoom.name == room_name
        ).first()
        if room:
            db.delete(room)
            db.commit()
    return RedirectResponse(url=f"/survey/{token}/rooms", status_code=303)


@app.post("/survey/{token}/rooms/done")
async def survey_rooms_done(
    token: str, request: Request, db: Session = Depends(get_db)
):
    lead = get_lead_or_404(token, db)

    if not lead.rooms:
        # If no rooms were added, bounce back
        return RedirectResponse(url=f"/survey/{token}/rooms", status_code=303)

    first_room = sorted(lead.rooms, key=lambda r: r.created_at)[0]
    return RedirectResponse(
        url=f"/survey/{token}/room/{first_room.id}", status_code=303
    )


# -------------------------------------------------------------------
# 14 & 15. Room photo upload + AI inventory extraction
# -------------------------------------------------------------------
@app.get("/survey/{token}/room/{room_id}")
async def survey_room_photos(
    token: str, room_id: str, request: Request, db: Session = Depends(get_db)
):
    lead = get_lead_or_404(token, db)
    room = db.query(LeadRoom).filter(
        LeadRoom.id == room_id, LeadRoom.lead_id == lead.id
    ).first()
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    # Determine current room index for display
    sorted_rooms = sorted(lead.rooms, key=lambda r: r.created_at)
    room_index = next(
        (i for i, r in enumerate(sorted_rooms) if str(r.id) == str(room_id)), 0
    )

    return templates.TemplateResponse(
        "consumer/photos_upload.html",
        {
            "request": request,
            "token": token,
            "lead": lead,
            "room": room,
            "room_index": room_index,
            "total_rooms": len(sorted_rooms),
            "max_photos": MAX_PHOTOS_PER_ROOM,
            "progress": PROGRESS["photos"],
        },
    )


@app.post("/survey/{token}/room/{room_id}/upload")
async def survey_room_upload(
    token: str, room_id: str, request: Request, db: Session = Depends(get_db)
):
    lead = get_lead_or_404(token, db)
    room = db.query(LeadRoom).filter(
        LeadRoom.id == room_id, LeadRoom.lead_id == lead.id
    ).first()
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    form = await request.form()

    # Collect uploaded files (the HTML form field is named "photos")
    uploaded_files: list = form.getlist("photos")

    if not uploaded_files:
        return RedirectResponse(
            url=f"/survey/{token}/room/{room_id}", status_code=303
        )

    # Ensure upload directory exists
    upload_dir = UPLOAD_ROOT / "leads" / token
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: List[str] = []
    photos_saved = 0

    for upload in uploaded_files:
        # Skip empty file slots and enforce per-room limit
        if not hasattr(upload, "read"):
            continue
        if photos_saved >= MAX_PHOTOS_PER_ROOM:
            break

        content_type = getattr(upload, "content_type", "") or ""
        original_name = getattr(upload, "filename", "") or "unknown"

        # Validate MIME type
        if content_type not in ALLOWED_MIME_TYPES:
            logger.warning(
                "Rejected file %s with content_type=%s", original_name, content_type
            )
            continue

        file_bytes = await upload.read()
        if not file_bytes:
            continue

        try:
            meta = _process_and_save_image(upload_dir, file_bytes, original_name)
        except Exception:
            logger.exception("Failed to process image %s", original_name)
            continue

        photo = LeadPhoto(
            room_id=room.id,
            filename=meta["filename"],
            original_filename=meta["original_filename"],
            storage_path=meta["storage_path"],
            file_size_bytes=meta["file_size_bytes"],
            mime_type=meta["mime_type"],
        )
        db.add(photo)
        saved_paths.append(meta["storage_path"])
        photos_saved += 1

    db.flush()

    # ---- AI vision extraction (run in a thread to avoid blocking) ----
    if saved_paths:
        try:
            inventory = await asyncio.to_thread(
                extract_removal_inventory, saved_paths
            )
        except Exception:
            logger.exception("AI vision extraction failed for room %s", room_id)
            inventory = {
                "items": [],
                "summary": "We couldn't automatically identify items from your photos. "
                "Please add items manually in the review step.",
            }

        # Persist extracted items (wrap in try/except — AI can return bad data)
        try:
            for item_data in inventory.get("items", []):
                if not isinstance(item_data, dict):
                    continue
                item = LeadItem(
                    room_id=room.id,
                    name=str(item_data.get("name", "Unknown item"))[:255],
                    qty=_safe_int(item_data.get("qty"), 1),
                    length_cm=_safe_float(item_data.get("length_cm")),
                    width_cm=_safe_float(item_data.get("width_cm")),
                    height_cm=_safe_float(item_data.get("height_cm")),
                    weight_kg=_safe_float(item_data.get("weight_kg")),
                    cbm=_safe_float(item_data.get("cbm")),
                    bulky=bool(item_data.get("bulky", False)),
                    fragile=bool(item_data.get("fragile", False)),
                    item_category=str(item_data.get("item_category", ""))[:50] or None,
                    packing_requirement=str(item_data.get("packing_requirement", ""))[:50] or None,
                    notes=str(item_data.get("notes", ""))[:500] or None,
                )
                db.add(item)

            room.summary = str(inventory.get("summary", ""))[:500]
        except Exception:
            logger.exception("Failed to persist AI items for room %s", room_id)
            db.rollback()

    db.commit()

    # ---- Navigate to the next room, or to review if this was the last ----
    sorted_rooms = sorted(lead.rooms, key=lambda r: r.created_at)
    current_index = next(
        (i for i, r in enumerate(sorted_rooms) if str(r.id) == str(room_id)), -1
    )
    if current_index + 1 < len(sorted_rooms):
        next_room = sorted_rooms[current_index + 1]
        return RedirectResponse(
            url=f"/survey/{token}/room/{next_room.id}", status_code=303
        )

    return RedirectResponse(url=f"/survey/{token}/review", status_code=303)


# -------------------------------------------------------------------
# 16 & 17. Inventory review
# -------------------------------------------------------------------
@app.get("/survey/{token}/review")
async def survey_review(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)

    # Compute totals for display (not yet persisted -- that happens on POST)
    total_cbm = Decimal("0")
    total_weight_kg = Decimal("0")
    total_items = 0
    bulky_items = 0
    fragile_items = 0

    for room in lead.rooms:
        for item in room.items:
            qty = item.qty or 1
            total_items += qty
            if item.cbm:
                total_cbm += Decimal(str(item.cbm)) * qty
            if item.weight_kg:
                total_weight_kg += Decimal(str(item.weight_kg)) * qty
            if item.bulky:
                bulky_items += qty
            if item.fragile:
                fragile_items += qty

    return templates.TemplateResponse(
        "consumer/review.html",
        {
            "request": request,
            "token": token,
            "lead": lead,
            "rooms": lead.rooms,
            "total_cbm": round(total_cbm, 2),
            "total_weight_kg": round(total_weight_kg, 2),
            "total_items": total_items,
            "bulky_items": bulky_items,
            "fragile_items": fragile_items,
            "progress": PROGRESS["review"],
        },
    )


@app.post("/survey/{token}/review")
async def survey_review_post(
    token: str, request: Request, db: Session = Depends(get_db)
):
    lead = get_lead_or_404(token, db)

    # Finalise inventory totals on the lead record
    total_cbm = Decimal("0")
    total_weight_kg = Decimal("0")
    total_items = 0
    bulky_items = 0
    fragile_items = 0

    for room in lead.rooms:
        for item in room.items:
            qty = item.qty or 1
            total_items += qty
            if item.cbm:
                total_cbm += Decimal(str(item.cbm)) * qty
            if item.weight_kg:
                total_weight_kg += Decimal(str(item.weight_kg)) * qty
            if item.bulky:
                bulky_items += qty
            if item.fragile:
                fragile_items += qty

    lead.total_cbm = total_cbm
    lead.total_weight_kg = total_weight_kg
    lead.total_items = total_items
    lead.bulky_items = bulky_items
    lead.fragile_items = fragile_items

    # Generate consumer-facing price estimate
    estimate = calculate_lead_estimate(lead)
    lead.estimate_low = estimate["estimate_low"]
    lead.estimate_high = estimate["estimate_high"]

    db.commit()
    return RedirectResponse(url=f"/survey/{token}/estimate", status_code=303)


# -------------------------------------------------------------------
# 18. Estimate display
# -------------------------------------------------------------------
@app.get("/survey/{token}/estimate")
async def survey_estimate(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)
    estimate = calculate_lead_estimate(lead)
    return templates.TemplateResponse(
        "consumer/estimate.html",
        {
            "request": request,
            "token": token,
            "lead": lead,
            "breakdown": estimate.get("breakdown"),
            "progress": PROGRESS["estimate"],
        },
    )


# -------------------------------------------------------------------
# 19 & 20. Contact details (final step to submit the lead)
# -------------------------------------------------------------------
@app.get("/survey/{token}/contact")
async def survey_contact(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)
    return templates.TemplateResponse(
        "consumer/contact.html",
        {
            "request": request,
            "token": token,
            "lead": lead,
            "progress": PROGRESS["contact"],
        },
    )


@app.post("/survey/{token}/contact")
async def survey_contact_post(
    token: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    lead = get_lead_or_404(token, db)
    form = await request.form()

    lead.customer_name = (form.get("customer_name", "") or "").strip()
    lead.customer_email = (form.get("customer_email", "") or "").strip()
    lead.customer_phone = (form.get("customer_phone", "") or "").strip()

    now = datetime.now(timezone.utc)
    lead.status = "active"
    lead.submitted_at = now
    lead.expires_at = now + timedelta(days=LEAD_EXPIRY_DAYS)

    # Determine lead price based on CBM pricing tiers
    lead.lead_price_pence = calculate_lead_price_pence(
        float(lead.total_cbm or 0), db
    )

    db.commit()

    # Trigger asynchronous lead distribution to matching removal companies.
    # Import inside the handler to avoid circular imports and allow the
    # module to be created independently.
    try:
        from app import lead_matching

        background_tasks.add_task(lead_matching.distribute_lead, lead.id)
    except ImportError:
        logger.warning(
            "lead_matching module not available -- skipping distribution for lead %s",
            lead.id,
        )

    return RedirectResponse(url=f"/survey/{token}/thank-you", status_code=303)


# -------------------------------------------------------------------
# 21. Thank you page
# -------------------------------------------------------------------
@app.get("/survey/{token}/thank-you")
async def survey_thank_you(token: str, request: Request, db: Session = Depends(get_db)):
    lead = get_lead_or_404(token, db)
    return templates.TemplateResponse(
        "consumer/thank_you.html",
        {
            "request": request,
            "token": token,
            "lead": lead,
        },
    )


# -------------------------------------------------------------------
# 22. Serve uploaded lead photos
# -------------------------------------------------------------------
@app.get("/photo/leads/{token}/{filename}")
async def serve_lead_photo(token: str, filename: str):
    """Serve a photo file from the uploads directory.

    Basic path-traversal protection: strip anything that is not an
    expected filename character.
    """
    # Sanitise inputs to prevent directory traversal
    safe_token = "".join(c for c in token if c.isalnum())
    safe_filename = pathlib.Path(filename).name  # strips any directory components

    file_path = UPLOAD_ROOT / "leads" / safe_token / safe_filename

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")

    return FileResponse(
        path=str(file_path),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# -------------------------------------------------------------------
# 23. Stripe webhook
# -------------------------------------------------------------------
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        from app.stripe_billing import handle_stripe_webhook

        result = handle_stripe_webhook(payload, sig, db)
        return result
    except ImportError:
        logger.warning("stripe_billing module not available")
        return {"status": "skipped"}
    except Exception as e:
        logger.exception("Stripe webhook error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
