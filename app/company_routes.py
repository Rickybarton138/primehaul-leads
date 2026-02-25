"""
PrimeHaul Leads -- Company-facing routes.

Handles removal company registration, login, dashboard, service-area
configuration, lead preferences, lead preview/purchase, purchase history,
and account settings.
"""

import json
import logging
import pathlib
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.auth import (
    create_access_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.rate_limit import limiter
from app.dependencies import get_current_company
from app.geo import extract_city_from_label, extract_postcode_area
from app.models import (
    Company,
    Lead,
    LeadItem,
    LeadNotification,
    LeadPhoto,
    LeadPurchase,
    LeadRoom,
)
from app.pricing import calculate_lead_price_pence

# ---------------------------------------------------------------------------
# Lazy Stripe import -- may not be installed in dev environments
# ---------------------------------------------------------------------------
try:
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    STRIPE_AVAILABLE = bool(settings.STRIPE_SECRET_KEY)
except ImportError:
    stripe = None
    STRIPE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
logger = logging.getLogger("primehaul.company")

router = APIRouter()

_BASE_DIR = pathlib.Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def slugify(text: str) -> str:
    """Generate a URL-safe slug from arbitrary text."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:100]


def _lead_price_display(price_pence: int) -> str:
    """Format a price-in-pence as a human-readable GBP string."""
    pounds = price_pence / 100
    if pounds == int(pounds):
        return f"\u00a3{int(pounds)}"
    return f"\u00a3{pounds:.2f}"


# ===================================================================
#  REGISTRATION & AUTH
# ===================================================================

# 1. GET /company/register
# -------------------------------------------------------------------
@router.get("/company/register", response_class=HTMLResponse)
async def register_form(request: Request):
    return templates.TemplateResponse(
        "company/register.html",
        {"request": request, "error": None, "form": None},
    )


# 2. POST /company/register
# -------------------------------------------------------------------
@router.post("/company/register", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def register_submit(
    request: Request,
    company_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    form_data = {
        "company_name": company_name,
        "email": email,
        "phone": phone,
    }

    # -- Validation --
    if not company_name.strip():
        return templates.TemplateResponse(
            "company/register.html",
            {"request": request, "error": "Company name is required.", "form": form_data},
        )

    if password != password_confirm:
        return templates.TemplateResponse(
            "company/register.html",
            {"request": request, "error": "Passwords do not match.", "form": form_data},
        )

    is_strong, pw_msg = validate_password_strength(password)
    if not is_strong:
        return templates.TemplateResponse(
            "company/register.html",
            {"request": request, "error": pw_msg, "form": form_data},
        )

    # Check email uniqueness
    existing = db.query(Company).filter(Company.email == email.strip().lower()).first()
    if existing:
        return templates.TemplateResponse(
            "company/register.html",
            {"request": request, "error": "An account with this email already exists.", "form": form_data},
        )

    # Create company
    slug = slugify(company_name)

    # Ensure slug uniqueness by appending short hex suffix if needed
    slug_exists = db.query(Company).filter(Company.slug == slug).first()
    if slug_exists:
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    company = Company(
        company_name=company_name.strip(),
        slug=slug,
        email=email.strip().lower(),
        phone=phone.strip() or None,
        password_hash=hash_password(password),
    )
    db.add(company)
    db.commit()

    return RedirectResponse(
        url="/company/login?success=Account+created+successfully.+Please+sign+in.",
        status_code=303,
    )


# 3. GET /company/login
# -------------------------------------------------------------------
@router.get("/company/login", response_class=HTMLResponse)
async def login_form(request: Request):
    success = request.query_params.get("success")
    return templates.TemplateResponse(
        "company/login.html",
        {"request": request, "error": None, "success": success, "form": None},
    )


# 4. POST /company/login
# -------------------------------------------------------------------
@router.post("/company/login", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    form_data = {"email": email}

    company = (
        db.query(Company)
        .filter(Company.email == email.strip().lower())
        .first()
    )

    if not company or not verify_password(password, company.password_hash):
        return templates.TemplateResponse(
            "company/login.html",
            {"request": request, "error": "Invalid email or password.", "success": None, "form": form_data},
        )

    if not company.is_active:
        return templates.TemplateResponse(
            "company/login.html",
            {"request": request, "error": "This account has been deactivated.", "success": None, "form": form_data},
        )

    # Create JWT
    token = create_access_token(subject_id=str(company.id), token_type="company")

    # Update last login
    company.last_login_at = datetime.now(timezone.utc)
    db.commit()

    response = RedirectResponse(url="/company/dashboard", status_code=303)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.APP_ENV != "development",
        max_age=60 * 60 * 24,  # 24 hours
    )
    return response


# 5. POST /company/logout
# -------------------------------------------------------------------
@router.post("/company/logout")
async def logout():
    response = RedirectResponse(url="/company/login", status_code=303)
    response.delete_cookie(key="access_token")
    return response


# ===================================================================
#  DASHBOARD (auth required)
# ===================================================================

# 6. GET /company/dashboard
# -------------------------------------------------------------------
@router.get("/company/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    # Stats
    leads_received = (
        db.query(func.count(LeadNotification.id))
        .filter(LeadNotification.company_id == company.id)
        .scalar()
    ) or 0

    leads_purchased = (
        db.query(func.count(LeadPurchase.id))
        .filter(LeadPurchase.company_id == company.id)
        .scalar()
    ) or 0

    total_spent = (
        db.query(func.coalesce(func.sum(LeadPurchase.price_pence), 0))
        .filter(
            LeadPurchase.company_id == company.id,
            LeadPurchase.payment_status == "paid",
        )
        .scalar()
    ) or 0

    stats = {
        "leads_received": leads_received,
        "leads_purchased": leads_purchased,
        "total_spent": total_spent,
    }

    # Recent notifications (last 10) with lead data
    recent_notifications = (
        db.query(LeadNotification)
        .options(joinedload(LeadNotification.lead))
        .filter(LeadNotification.company_id == company.id)
        .order_by(LeadNotification.sent_at.desc())
        .limit(10)
        .all()
    )

    return templates.TemplateResponse(
        "company/dashboard.html",
        {
            "request": request,
            "company": company,
            "stats": stats,
            "recent_notifications": recent_notifications,
            "active_page": "dashboard",
        },
    )


# ===================================================================
#  SERVICE AREA
# ===================================================================

# 7. GET /company/service-area
# -------------------------------------------------------------------
@router.get("/company/service-area", response_class=HTMLResponse)
async def service_area_form(
    request: Request,
    company: Company = Depends(get_current_company),
):
    return templates.TemplateResponse(
        "company/service_area.html",
        {
            "request": request,
            "company": company,
            "mapbox_token": settings.MAPBOX_ACCESS_TOKEN,
            "error": None,
            "success": None,
            "active_page": "service_area",
        },
    )


# 8. POST /company/service-area
# -------------------------------------------------------------------
@router.post("/company/service-area", response_class=HTMLResponse)
async def service_area_submit(
    request: Request,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    form = await request.form()

    base_postcode = (form.get("base_postcode", "") or "").strip()
    try:
        service_radius_miles = int(form.get("service_radius_miles", 30) or 30)
    except (ValueError, TypeError):
        service_radius_miles = 30
    service_radius_miles = max(1, min(service_radius_miles, 500))

    # Lat/lng may come from hidden form fields populated by client-side JS
    base_lat = form.get("base_lat")
    base_lng = form.get("base_lng")

    if not base_postcode:
        return templates.TemplateResponse(
            "company/service_area.html",
            {
                "request": request,
                "company": company,
                "mapbox_token": settings.MAPBOX_ACCESS_TOKEN,
                "error": "Base postcode is required.",
                "success": None,
                "active_page": "service_area",
            },
        )

    company.base_postcode = base_postcode
    company.service_radius_miles = service_radius_miles

    if base_lat and base_lng:
        try:
            company.base_lat = float(base_lat)
            company.base_lng = float(base_lng)
        except (ValueError, TypeError):
            pass

    db.commit()

    return templates.TemplateResponse(
        "company/service_area.html",
        {
            "request": request,
            "company": company,
            "mapbox_token": settings.MAPBOX_ACCESS_TOKEN,
            "error": None,
            "success": "Service area updated successfully.",
            "active_page": "service_area",
        },
    )


# ===================================================================
#  PREFERENCES
# ===================================================================

# 9. GET /company/preferences
# -------------------------------------------------------------------
@router.get("/company/preferences", response_class=HTMLResponse)
async def preferences_form(
    request: Request,
    company: Company = Depends(get_current_company),
):
    return templates.TemplateResponse(
        "company/preferences.html",
        {
            "request": request,
            "company": company,
            "error": None,
            "success": None,
            "active_page": "preferences",
        },
    )


# 10. POST /company/preferences
# -------------------------------------------------------------------
@router.post("/company/preferences", response_class=HTMLResponse)
async def preferences_submit(
    request: Request,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    form = await request.form()

    # CBM range
    min_cbm = form.get("min_cbm")
    max_cbm = form.get("max_cbm")
    company.pref_min_cbm = Decimal(min_cbm) if min_cbm else None
    company.pref_max_cbm = Decimal(max_cbm) if max_cbm else None

    # Property types (checkboxes -> list)
    property_types = form.getlist("property_types")
    company.pref_property_types = property_types if property_types else None

    # Notification channels
    notification_email = (form.get("notification_email", "") or "").strip()
    notification_phone = (form.get("notification_phone", "") or "").strip()
    company.pref_notification_email = notification_email or None
    company.pref_notification_phone = notification_phone or None

    db.commit()

    return templates.TemplateResponse(
        "company/preferences.html",
        {
            "request": request,
            "company": company,
            "error": None,
            "success": "Preferences saved successfully.",
            "active_page": "preferences",
        },
    )


# ===================================================================
#  LEAD PREVIEW & PURCHASE
# ===================================================================

# 11. GET /company/leads/{lead_id}/preview
# -------------------------------------------------------------------
@router.get("/company/leads/{lead_id}/preview", response_class=HTMLResponse)
async def lead_preview(
    lead_id: str,
    request: Request,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Ensure lead is still active
    if lead.status != "active":
        return templates.TemplateResponse(
            "company/lead_preview.html",
            {
                "request": request,
                "company": company,
                "lead": lead,
                "lead_price_display": "",
                "error": "This lead is no longer available.",
                "active_page": "dashboard",
            },
        )

    # Calculate price for display
    price_pence = lead.lead_price_pence or calculate_lead_price_pence(
        float(lead.total_cbm or 0), db
    )
    lead_price_display = _lead_price_display(price_pence)

    return templates.TemplateResponse(
        "company/lead_preview.html",
        {
            "request": request,
            "company": company,
            "lead": lead,
            "lead_price_display": lead_price_display,
            "error": None,
            "active_page": "dashboard",
        },
    )


# 12. POST /company/leads/{lead_id}/purchase
# -------------------------------------------------------------------
@router.post("/company/leads/{lead_id}/purchase")
async def lead_purchase(
    lead_id: str,
    request: Request,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Check if already purchased by this company
    existing_purchase = (
        db.query(LeadPurchase)
        .filter(
            LeadPurchase.lead_id == lead.id,
            LeadPurchase.company_id == company.id,
        )
        .first()
    )
    if existing_purchase:
        return RedirectResponse(
            url=f"/company/leads/{lead_id}/purchased", status_code=303
        )

    price_pence = lead.lead_price_pence or calculate_lead_price_pence(
        float(lead.total_cbm or 0), db
    )

    # --- Stripe Checkout ---
    if STRIPE_AVAILABLE and stripe:
        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                mode="payment",
                customer_email=company.email,
                line_items=[
                    {
                        "price_data": {
                            "currency": "gbp",
                            "unit_amount": price_pence,
                            "product_data": {
                                "name": f"Lead Purchase - {extract_postcode_area(lead.pickup.get('postcode', '') if lead.pickup else '')} area",
                                "description": (
                                    f"{lead.total_cbm} CBM | {lead.property_type or 'Move'}"
                                ),
                            },
                        },
                        "quantity": 1,
                    }
                ],
                metadata={
                    "lead_id": str(lead.id),
                    "company_id": str(company.id),
                    "price_pence": str(price_pence),
                },
                success_url=(
                    f"{settings.APP_URL}/company/purchase-success"
                    f"?session_id={{CHECKOUT_SESSION_ID}}"
                ),
                cancel_url=f"{settings.APP_URL}/company/leads/{lead_id}/preview",
            )

            # Create a pending purchase record
            purchase = LeadPurchase(
                lead_id=lead.id,
                company_id=company.id,
                price_pence=price_pence,
                stripe_checkout_session_id=checkout_session.id,
                payment_status="pending",
            )
            db.add(purchase)
            db.commit()

            return RedirectResponse(url=checkout_session.url, status_code=303)

        except Exception:
            logger.exception("Stripe checkout session creation failed")
            raise HTTPException(
                status_code=502,
                detail="Payment processing is temporarily unavailable. Please try again later.",
            )

    # --- Dev mode: create purchase directly without Stripe ---
    if settings.APP_ENV != "development":
        raise HTTPException(
            status_code=503,
            detail="Payment processing is not configured.",
        )

    purchase = LeadPurchase(
        lead_id=lead.id,
        company_id=company.id,
        price_pence=price_pence,
        payment_status="paid",
        paid_at=datetime.now(timezone.utc),
    )
    db.add(purchase)

    # Mark the notification as purchased if one exists
    notification = (
        db.query(LeadNotification)
        .filter(
            LeadNotification.lead_id == lead.id,
            LeadNotification.company_id == company.id,
        )
        .first()
    )
    if notification:
        notification.purchased_at = datetime.now(timezone.utc)

    db.commit()

    return RedirectResponse(
        url=f"/company/leads/{lead_id}/purchased", status_code=303
    )


# 13. GET /company/purchase-success
# -------------------------------------------------------------------
@router.get("/company/purchase-success", response_class=HTMLResponse)
async def purchase_success(
    request: Request,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    session_id = request.query_params.get("session_id")

    lead = None

    if session_id and STRIPE_AVAILABLE and stripe:
        try:
            checkout_session = stripe.checkout.Session.retrieve(session_id)

            # Find and update the purchase record
            purchase = (
                db.query(LeadPurchase)
                .filter(LeadPurchase.stripe_checkout_session_id == session_id)
                .first()
            )

            if purchase and purchase.payment_status != "paid":
                purchase.payment_status = "paid"
                purchase.paid_at = datetime.now(timezone.utc)

                if checkout_session.payment_intent:
                    purchase.stripe_payment_intent_id = checkout_session.payment_intent

                # Mark the notification as purchased
                notification = (
                    db.query(LeadNotification)
                    .filter(
                        LeadNotification.lead_id == purchase.lead_id,
                        LeadNotification.company_id == company.id,
                    )
                    .first()
                )
                if notification:
                    notification.purchased_at = datetime.now(timezone.utc)

                db.commit()

            if purchase:
                lead = db.query(Lead).filter(Lead.id == purchase.lead_id).first()

        except Exception:
            logger.exception("Error processing Stripe success callback")

    # If no Stripe session, try to find the most recent purchase
    if not lead:
        recent_purchase = (
            db.query(LeadPurchase)
            .filter(LeadPurchase.company_id == company.id)
            .order_by(LeadPurchase.created_at.desc())
            .first()
        )
        if recent_purchase:
            lead = db.query(Lead).filter(Lead.id == recent_purchase.lead_id).first()

    if not lead:
        return RedirectResponse(url="/company/dashboard", status_code=303)

    return templates.TemplateResponse(
        "company/purchase_success.html",
        {
            "request": request,
            "company": company,
            "lead": lead,
            "active_page": "dashboard",
        },
    )


# 14. GET /company/leads/{lead_id}/purchased
# -------------------------------------------------------------------
@router.get("/company/leads/{lead_id}/purchased", response_class=HTMLResponse)
async def lead_purchased(
    lead_id: str,
    request: Request,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    # Verify this company purchased this lead
    purchase = (
        db.query(LeadPurchase)
        .filter(
            LeadPurchase.lead_id == lead_id,
            LeadPurchase.company_id == company.id,
            LeadPurchase.payment_status == "paid",
        )
        .first()
    )
    if not purchase:
        raise HTTPException(status_code=403, detail="You have not purchased this lead.")

    # Load full lead with rooms, items, and photos
    lead = (
        db.query(Lead)
        .options(
            joinedload(Lead.rooms).joinedload(LeadRoom.items),
            joinedload(Lead.rooms).joinedload(LeadRoom.photos),
        )
        .filter(Lead.id == lead_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Build rooms with items for the template
    rooms_with_items = sorted(lead.rooms, key=lambda r: r.created_at)

    return templates.TemplateResponse(
        "company/lead_purchased.html",
        {
            "request": request,
            "company": company,
            "lead": lead,
            "rooms_with_items": rooms_with_items,
            "active_page": "purchases",
        },
    )


# ===================================================================
#  PURCHASE HISTORY & ACCOUNT
# ===================================================================

# 15. GET /company/purchases
# -------------------------------------------------------------------
@router.get("/company/purchases", response_class=HTMLResponse)
async def purchases_list(
    request: Request,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    purchases = (
        db.query(LeadPurchase)
        .options(joinedload(LeadPurchase.lead))
        .filter(LeadPurchase.company_id == company.id)
        .order_by(LeadPurchase.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        "company/purchases.html",
        {
            "request": request,
            "company": company,
            "purchases": purchases,
            "active_page": "purchases",
        },
    )


# 16. GET /company/account
# -------------------------------------------------------------------
@router.get("/company/account", response_class=HTMLResponse)
async def account_form(
    request: Request,
    company: Company = Depends(get_current_company),
):
    return templates.TemplateResponse(
        "company/account.html",
        {
            "request": request,
            "company": company,
            "error": None,
            "success": None,
            "active_page": "account",
        },
    )


# 17. POST /company/account
# -------------------------------------------------------------------
@router.post("/company/account", response_class=HTMLResponse)
async def account_submit(
    request: Request,
    company: Company = Depends(get_current_company),
    db: Session = Depends(get_db),
):
    form = await request.form()

    email = (form.get("email", "") or "").strip().lower()
    phone = (form.get("phone", "") or "").strip()
    current_password = (form.get("current_password", "") or "").strip()
    new_password = (form.get("new_password", "") or "").strip()
    new_password_confirm = (form.get("new_password_confirm", "") or "").strip()

    # Validate email
    if not email:
        return templates.TemplateResponse(
            "company/account.html",
            {
                "request": request,
                "company": company,
                "error": "Email address is required.",
                "success": None,
                "active_page": "account",
            },
        )

    # Check email uniqueness if changed
    if email != company.email:
        existing = db.query(Company).filter(Company.email == email).first()
        if existing:
            return templates.TemplateResponse(
                "company/account.html",
                {
                    "request": request,
                    "company": company,
                    "error": "This email address is already in use by another account.",
                    "success": None,
                    "active_page": "account",
                },
            )

    # Handle password change
    if new_password:
        if not current_password:
            return templates.TemplateResponse(
                "company/account.html",
                {
                    "request": request,
                    "company": company,
                    "error": "Please enter your current password to set a new one.",
                    "success": None,
                    "active_page": "account",
                },
            )

        if not verify_password(current_password, company.password_hash):
            return templates.TemplateResponse(
                "company/account.html",
                {
                    "request": request,
                    "company": company,
                    "error": "Current password is incorrect.",
                    "success": None,
                    "active_page": "account",
                },
            )

        if new_password != new_password_confirm:
            return templates.TemplateResponse(
                "company/account.html",
                {
                    "request": request,
                    "company": company,
                    "error": "New passwords do not match.",
                    "success": None,
                    "active_page": "account",
                },
            )

        is_strong, pw_msg = validate_password_strength(new_password)
        if not is_strong:
            return templates.TemplateResponse(
                "company/account.html",
                {
                    "request": request,
                    "company": company,
                    "error": pw_msg,
                    "success": None,
                    "active_page": "account",
                },
            )

        company.password_hash = hash_password(new_password)

    # Update fields
    company.email = email
    company.phone = phone or None

    db.commit()

    return templates.TemplateResponse(
        "company/account.html",
        {
            "request": request,
            "company": company,
            "error": None,
            "success": "Account updated successfully.",
            "active_page": "account",
        },
    )
