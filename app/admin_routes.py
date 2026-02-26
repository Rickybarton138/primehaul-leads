"""
PrimeHaul Leads -- Admin panel routes.

Provides a server-rendered admin dashboard for managing leads, companies,
pricing tiers, and viewing revenue.  All routes are mounted under /admin
and protected by JWT-based admin authentication (cookie: admin_token).
"""

import pathlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import create_access_token, verify_password
from app.config import settings
from app.database import get_db
from app.rate_limit import limiter
from app.dependencies import get_current_admin
from app.models import (
    AdminUser,
    Company,
    Lead,
    LeadPricingTier,
    LeadPurchase,
    SocialConfig,
    SocialPost,
)
from app.social_autopilot import (
    force_generate_batch,
    manually_publish_post,
    skip_post,
    _get_config,
)

router = APIRouter()

_BASE_DIR = pathlib.Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


# ---------------------------------------------------------------------------
# 1. GET /admin/login -- Render login page
# ---------------------------------------------------------------------------
@router.get("/admin/login")
async def admin_login_page(request: Request):
    return templates.TemplateResponse(
        "admin/login.html",
        {"request": request},
    )


# ---------------------------------------------------------------------------
# 2. POST /admin/login -- Authenticate admin, set JWT cookie, redirect
# ---------------------------------------------------------------------------
@router.post("/admin/login")
@limiter.limit("5/minute")
async def admin_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = db.query(AdminUser).filter(AdminUser.email == email).first()

    if not admin or not verify_password(password, admin.password_hash):
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "Invalid email or password"},
        )

    if not admin.is_active:
        return templates.TemplateResponse(
            "admin/login.html",
            {"request": request, "error": "Account is disabled"},
        )

    token = create_access_token(subject_id=str(admin.id), token_type="admin")

    response = RedirectResponse(url="/admin/dashboard", status_code=303)
    response.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.APP_ENV != "development",
    )
    return response


# ---------------------------------------------------------------------------
# 3. POST /admin/logout -- Clear cookie and redirect to login
# ---------------------------------------------------------------------------
@router.post("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(key="admin_token")
    return response


# ---------------------------------------------------------------------------
# 4. GET /admin/dashboard -- Aggregated stats overview
# ---------------------------------------------------------------------------
@router.get("/admin/dashboard")
async def admin_dashboard(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    total_leads = db.query(func.count(Lead.id)).scalar() or 0

    active_leads = (
        db.query(func.count(Lead.id))
        .filter(Lead.status == "active", Lead.expires_at > now)
        .scalar()
        or 0
    )

    total_companies = db.query(func.count(Company.id)).scalar() or 0

    total_revenue_pence = (
        db.query(func.sum(LeadPurchase.price_pence))
        .filter(LeadPurchase.payment_status == "paid")
        .scalar()
        or 0
    )
    total_revenue = total_revenue_pence / 100  # GBP

    recent_leads = (
        db.query(Lead).order_by(Lead.created_at.desc()).limit(10).all()
    )

    recent_companies = (
        db.query(Company).order_by(Company.created_at.desc()).limit(5).all()
    )

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "admin": admin,
            "active_page": "dashboard",
            "stats": {
                "total_leads": total_leads,
                "active_leads": active_leads,
                "total_companies": total_companies,
                "total_revenue": total_revenue,
                "recent_leads": recent_leads,
                "recent_companies": recent_companies,
            },
        },
    )


# ---------------------------------------------------------------------------
# 5. GET /admin/leads -- List all leads with optional status filter
# ---------------------------------------------------------------------------
@router.get("/admin/leads")
async def admin_leads(
    request: Request,
    status: str = None,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Lead)

    if status:
        query = query.filter(Lead.status == status)

    leads = query.order_by(Lead.created_at.desc()).all()

    # Attach purchase count to each lead for display
    leads_with_counts = []
    for lead in leads:
        purchase_count = (
            db.query(func.count(LeadPurchase.id))
            .filter(LeadPurchase.lead_id == lead.id)
            .scalar()
            or 0
        )
        leads_with_counts.append(
            {"lead": lead, "purchase_count": purchase_count}
        )

    return templates.TemplateResponse(
        "admin/leads.html",
        {
            "request": request,
            "admin": admin,
            "active_page": "leads",
            "leads": leads_with_counts,
            "current_status": status,
        },
    )


# ---------------------------------------------------------------------------
# 6. GET /admin/companies -- List all companies with purchase counts
# ---------------------------------------------------------------------------
@router.get("/admin/companies")
async def admin_companies(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    companies = db.query(Company).order_by(Company.created_at.desc()).all()

    companies_with_counts = []
    for company in companies:
        total_purchases = (
            db.query(func.count(LeadPurchase.id))
            .filter(LeadPurchase.company_id == company.id)
            .scalar()
            or 0
        )
        companies_with_counts.append(
            {"company": company, "total_purchases": total_purchases}
        )

    return templates.TemplateResponse(
        "admin/companies.html",
        {
            "request": request,
            "admin": admin,
            "active_page": "companies",
            "companies": companies_with_counts,
        },
    )


# ---------------------------------------------------------------------------
# 7. POST /admin/companies/{company_id}/verify -- Mark company as verified
# ---------------------------------------------------------------------------
@router.post("/admin/companies/{company_id}/verify")
async def admin_verify_company(
    company_id: str,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if company:
        company.is_verified = True
        db.commit()

    return RedirectResponse(url="/admin/companies", status_code=303)


# ---------------------------------------------------------------------------
# 8. GET /admin/pricing -- List all pricing tiers
# ---------------------------------------------------------------------------
@router.get("/admin/pricing")
async def admin_pricing(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    tiers = (
        db.query(LeadPricingTier)
        .order_by(LeadPricingTier.min_cbm)
        .all()
    )

    return templates.TemplateResponse(
        "admin/pricing_tiers.html",
        {
            "request": request,
            "admin": admin,
            "active_page": "pricing",
            "tiers": tiers,
        },
    )


# ---------------------------------------------------------------------------
# 9. POST /admin/pricing -- Add a new pricing tier
# ---------------------------------------------------------------------------
@router.post("/admin/pricing")
async def admin_add_pricing_tier(
    name: str = Form(...),
    min_cbm: float = Form(...),
    max_cbm: float = Form(...),
    price_pence: int = Form(...),
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    tier = LeadPricingTier(
        name=name,
        min_cbm=min_cbm,
        max_cbm=max_cbm,
        price_pence=price_pence,
    )
    db.add(tier)
    db.commit()

    return RedirectResponse(url="/admin/pricing", status_code=303)


# ---------------------------------------------------------------------------
# 10. POST /admin/pricing/{tier_id}/toggle -- Toggle tier active status
# ---------------------------------------------------------------------------
@router.post("/admin/pricing/{tier_id}/toggle")
async def admin_toggle_pricing_tier(
    tier_id: str,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    tier = (
        db.query(LeadPricingTier)
        .filter(LeadPricingTier.id == tier_id)
        .first()
    )
    if tier:
        tier.is_active = not tier.is_active
        db.commit()

    return RedirectResponse(url="/admin/pricing", status_code=303)


# ---------------------------------------------------------------------------
# 11. GET /admin/revenue -- Revenue report (paid purchases)
# ---------------------------------------------------------------------------
@router.get("/admin/revenue")
async def admin_revenue(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    purchases = (
        db.query(LeadPurchase)
        .filter(LeadPurchase.payment_status == "paid")
        .order_by(LeadPurchase.paid_at.desc())
        .all()
    )

    total_revenue_pence = (
        db.query(func.sum(LeadPurchase.price_pence))
        .filter(LeadPurchase.payment_status == "paid")
        .scalar()
        or 0
    )
    total_revenue = total_revenue_pence / 100  # GBP

    return templates.TemplateResponse(
        "admin/revenue.html",
        {
            "request": request,
            "admin": admin,
            "active_page": "revenue",
            "purchases": purchases,
            "total_revenue": total_revenue,
        },
    )


# ---------------------------------------------------------------------------
# 12. GET /admin/social -- Social media auto-pilot dashboard
# ---------------------------------------------------------------------------
@router.get("/admin/social")
async def admin_social_dashboard(
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    config = _get_config(db)

    # Stats
    total_posts = db.query(func.count(SocialPost.id)).scalar() or 0
    published = (
        db.query(func.count(SocialPost.id))
        .filter(SocialPost.status == "published")
        .scalar() or 0
    )
    scheduled = (
        db.query(func.count(SocialPost.id))
        .filter(SocialPost.status == "scheduled")
        .scalar() or 0
    )
    failed = (
        db.query(func.count(SocialPost.id))
        .filter(SocialPost.status == "failed")
        .scalar() or 0
    )

    # Upcoming scheduled posts
    now = datetime.now(timezone.utc)
    upcoming = (
        db.query(SocialPost)
        .filter(SocialPost.status.in_(["scheduled", "draft"]))
        .order_by(SocialPost.scheduled_for)
        .limit(20)
        .all()
    )

    # Recently published
    recent = (
        db.query(SocialPost)
        .filter(SocialPost.status == "published")
        .order_by(SocialPost.published_at.desc())
        .limit(10)
        .all()
    )

    return templates.TemplateResponse(
        "admin/social_dashboard.html",
        {
            "request": request,
            "admin": admin,
            "active_page": "social",
            "config": config,
            "stats": {
                "total": total_posts,
                "published": published,
                "scheduled": scheduled,
                "failed": failed,
            },
            "upcoming": upcoming,
            "recent": recent,
        },
    )


# ---------------------------------------------------------------------------
# 13. POST /admin/social/generate -- Force-generate a new content batch
# ---------------------------------------------------------------------------
@router.post("/admin/social/generate")
async def admin_social_generate(
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    force_generate_batch(db)
    return RedirectResponse(url="/admin/social", status_code=303)


# ---------------------------------------------------------------------------
# 14. POST /admin/social/post/{post_id}/publish -- Manually publish one post
# ---------------------------------------------------------------------------
@router.post("/admin/social/post/{post_id}/publish")
async def admin_social_publish(
    post_id: str,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    manually_publish_post(db, post_id)
    return RedirectResponse(url="/admin/social", status_code=303)


# ---------------------------------------------------------------------------
# 15. POST /admin/social/post/{post_id}/skip -- Move to drafts
# ---------------------------------------------------------------------------
@router.post("/admin/social/post/{post_id}/skip")
async def admin_social_skip(
    post_id: str,
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    skip_post(db, post_id)
    return RedirectResponse(url="/admin/social", status_code=303)


# ---------------------------------------------------------------------------
# 16. POST /admin/social/settings -- Update social config
# ---------------------------------------------------------------------------
@router.post("/admin/social/settings")
async def admin_social_settings(
    request: Request,
    posts_per_day: int = Form(2),
    auto_publish: bool = Form(False),
    admin: AdminUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    config = _get_config(db)
    config.posts_per_day = posts_per_day
    config.auto_publish = auto_publish

    form = await request.form()
    times_raw = form.get("posting_times", "09:00,18:00")
    config.posting_times = [t.strip() for t in times_raw.split(",") if t.strip()]

    platforms = form.getlist("platforms")
    if platforms:
        config.active_platforms = platforms

    db.commit()
    return RedirectResponse(url="/admin/social", status_code=303)
