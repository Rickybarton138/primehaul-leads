# PrimeHaul Leads - Project Agent Instructions

## Identity
You are the dedicated agent for **PrimeHaul Leads**, a B2C2B lead generation platform for UK removal companies. You have deep knowledge of this entire codebase and should never need reminding of the architecture.

## Project Summary
Consumers fill out a multi-step survey with room photos → OpenAI Vision extracts furniture inventory → system calculates moving cost estimate → lead is distributed to matching removal companies → companies purchase qualified leads via Stripe.

**Live:** https://leads.primehaul.co.uk
**GitHub:** Rickybarton138/primehaul-leads
**Owner:** Ricky (rickybarton138@btinternet.com)

## Tech Stack
- **Backend:** FastAPI 0.115.6, Uvicorn, Python 3.12.8
- **Database:** PostgreSQL, SQLAlchemy 2.0, Alembic, psycopg3/psycopg2
- **AI:** OpenAI Vision (gpt-4o-mini) for photo→inventory extraction
- **Payments:** Stripe Checkout Sessions + webhooks
- **Frontend:** Jinja2 templates (40 files), Mapbox maps
- **Images:** Pillow (resize ≤2048px, JPEG 85%, EXIF transpose)
- **Auth:** JWT (python-jose, 24h), bcrypt, cookie-based
- **Storage:** S3-compatible (R2/AWS/DO) + local fallback
- **Social:** APScheduler + OpenAI autopilot (FB, IG, X, LinkedIn)
- **Email:** SMTP transactional (Gmail)
- **Deploy:** Railway (primary)

## File Map

### Core Application
| File | Purpose | Lines |
|------|---------|-------|
| `app/main.py` | FastAPI app, all consumer survey routes, health check, social proof API, photo serving | ~1100 |
| `app/models.py` | 14 SQLAlchemy models (Lead, LeadRoom, LeadItem, LeadPhoto, Company, LeadPurchase, LeadNotification, LeadPricingTier, AdminUser, EmailLog, StripeEvent, ErrorLog, SocialPost, SocialAccount, SocialConfig) | ~390 |
| `app/config.py` | Settings singleton from env vars, production validation | ~80 |
| `app/database.py` | Engine + SessionLocal factory, `get_db()` dependency | ~30 |
| `app/db_utils.py` | `normalize_database_url()` - rewrites postgres:// to best available driver | ~45 |

### Auth & Security
| File | Purpose |
|------|---------|
| `app/auth.py` | `hash_password()`, `verify_password()`, `create_access_token()`, `decode_access_token()`, `validate_password_strength()` |
| `app/dependencies.py` | `get_current_company()`, `get_current_admin()` - cookie JWT → model or 302 redirect |
| `app/rate_limit.py` | SlowAPI limiter singleton (IP-based) |

### Business Logic
| File | Purpose |
|------|---------|
| `app/pricing.py` | `calculate_lead_estimate()` (consumer-facing £ range) + `calculate_lead_price_pence()` (B2B lead price from DB tiers) |
| `app/ai_vision.py` | `extract_removal_inventory(image_paths)` → {items[], summary} via GPT-4o-mini. Compresses to 1200px/70% before base64. |
| `app/lead_matching.py` | `find_matching_companies()` by distance + CBM + property prefs. `distribute_lead()` background task after submission. |
| `app/geo.py` | `calculate_distance_miles()` (haversine), `extract_postcode_area()`, `extract_city_from_label()` |
| `app/storage.py` | `upload_photo()`, `get_photo_bytes()`, `get_photo_url()`, `delete_photo()` - S3 with local fallback |
| `app/notifications.py` | SMTP emails: customer_confirmation, lead_alert (redacted), purchase_confirmation (full details), manual |
| `app/stripe_billing.py` | `create_lead_purchase_session()`, `handle_checkout_completed()` webhook, `ensure_stripe_customer()` |
| `app/error_tracking.py` | `ErrorTrackingMiddleware` (5xx → DB), `DBLogHandler` (ERROR+ → error_logs table) |

### Route Modules
| File | Prefix | Purpose |
|------|--------|---------|
| `app/main.py` | `/`, `/survey/`, `/share/`, `/api/`, `/photo/`, `/webhooks/` | Consumer survey flow (12 steps), sharing, social proof, photos, Stripe webhooks |
| `app/company_routes.py` | `/company/` | Register, login, dashboard, lead preview/purchase, service area, preferences, account |
| `app/admin_routes.py` | `/admin/` | Login, dashboard KPIs, leads, companies (verify), pricing tiers, revenue, email, errors, analytics, social dashboard |
| `app/seo_routes.py` | `/removals/`, `/robots.txt`, `/sitemap.xml`, `/llms.txt` | 60 city pages, 69 route pages, removals index, SEO files |

### Social Automation
| File | Purpose |
|------|---------|
| `app/social_autopilot.py` | `generate_weekly_content()`, `publish_due_posts()`, `check_all_engagement()`. Content pillars: tip/stat/promo/seasonal/relatable/local. Branded 1080x1080 images via Pillow. Platform APIs: tweepy (X), httpx (FB/IG/LinkedIn). |

### Templates (40 files)
```
app/templates/
├── base.html, base_admin.html, base_company.html
├── consumer/
│   ├── landing.html, move_map.html, property_type.html, access.html
│   ├── move_date.html, rooms_pick.html, photos_upload.html
│   ├── review.html, estimate.html, contact.html, thank_you.html
│   ├── share_card.html, privacy.html, terms.html
│   ├── city_landing.html, route_landing.html, removals_index.html
├── company/
│   ├── register.html, login.html, dashboard.html
│   ├── lead_preview.html, lead_purchased.html, purchases.html
│   ├── service_area.html, preferences.html, account.html
├── admin/
│   ├── login.html, dashboard.html, leads.html, companies.html
│   ├── pricing_tiers.html, revenue.html, email.html
│   ├── errors.html, analytics.html, social_dashboard.html
```

### Infrastructure
| File | Purpose |
|------|---------|
| `startup.py` | Production startup: check DB state → run Alembic migrations → create_all fallback |
| `railway.json` | Railway config: NIXPACKS build, healthcheck /health (30s), restart on failure (10 retries) |
| `Procfile` | `python startup.py && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}` |
| `vercel.json` | Vercel serverless config (routes to `api/index.py`) - may be legacy |
| `api/index.py` | Vercel entry point: imports app.main, catch-all error handler |
| `alembic.ini` | Alembic config (no hardcoded URL - env.py sets dynamically) |
| `alembic/env.py` | Reads DATABASE_URL, sets target_metadata from app.models.Base |
| `alembic/versions/` | 4 migrations: initial_schema, viral_referral, email_logs, error_tracking+social |

### Tests
```
tests/
├── conftest.py          # In-memory SQLite, JSONB/UUID compat, dependency overrides
├── test_survey_flow.py  # End-to-end survey
├── test_pricing.py      # Pricing tiers
├── test_geo.py          # Distance calc
├── test_company.py      # Registration, purchase
├── test_admin.py        # Admin access
├── test_storage.py      # S3/local
├── test_db_utils.py     # URL normalization
├── test_referrals.py    # Referral rewards
└── test_health.py       # Health endpoint
```

## Database Schema

### Lead Lifecycle
```
in_progress → (contact submitted) → active → (14 days) → expired
```

### Key Relationships
```
Lead ──┬── LeadRoom ──┬── LeadItem (name, qty, dimensions, weight, CBM, bulky, fragile)
       │              └── LeadPhoto (filename, storage_path, file_size)
       ├── LeadPurchase ── Company
       └── LeadNotification ── Company
```

### JSONB Fields
- `Lead.pickup/dropoff`: `{label, lat, lng, city, postcode}`
- `Lead.pickup_access/dropoff_access`: `{floors, has_lift, parking_type, parking_distance_m, narrow_access, time_restriction, booking_required, outdoor_steps, outdoor_path}`

## Consumer Survey Flow
```
/ → /start (create Lead + token)
  → /survey/{token}/map (Mapbox pickup/dropoff)
  → /survey/{token}/property (pickup + dropoff types)
  → /survey/{token}/access (floors, lift, parking, steps per location)
  → /survey/{token}/move-date
  → /survey/{token}/rooms (add/remove room names)
  → /survey/{token}/room/{room_id} (upload ≤6 photos → AI extraction)
  → /survey/{token}/review (edit inventory, see totals)
  → /survey/{token}/estimate (price range + referral sharing)
  → /survey/{token}/contact (name, email, phone → submit)
  → /survey/{token}/thank-you (share link + ref code)
```

## Pricing Formula (Consumer Estimate)
```
base_fee = £250
+ total_cbm × £35
+ bulky_items × £25
+ fragile_items × £15
+ weight_kg over 1000 × £0.50
+ miles beyond 10 × £1.50
+ access_cost(pickup) + access_cost(dropoff)
  → floors × £15, no_lift +£50, parking (street £25, permit £40, limited £60)
  → parking_distance per 50m +£10, narrow +£35, time_restriction +£25
  → booking_required +£20, steps per 5 +£15, outdoor_path +£20
low = total × 0.85
high = total × 1.25
```

## Lead Matching Algorithm
1. Company.is_active = True, has base_lat/lng
2. haversine(company.base → lead.pickup) ≤ company.service_radius_miles
3. If pref_min_cbm set: lead.total_cbm ≥ min
4. If pref_max_cbm set: lead.total_cbm ≤ max
5. If pref_property_types set: lead.property_type in list (case-insensitive)

## Required Environment Variables
**Critical:** `DATABASE_URL`, `JWT_SECRET_KEY`, `OPENAI_API_KEY`, `MAPBOX_ACCESS_TOKEN`, `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`

**Optional (graceful degradation):** S3 vars, SMTP vars, social media tokens, `GOOGLE_ANALYTICS_ID`, `GOOGLE_SITE_VERIFICATION`, `CANONICAL_DOMAIN`

## Known Issues (2026-03-13)
1. Duplicate `/health` endpoint in main.py (second masks DB failures)
2. Vercel + Railway configs both exist (unclear primary)
3. database.py crashes at import if DATABASE_URL missing
4. Social proof shows "0" on landing (JS call to /api/social-proof may fail)
5. Local uploads won't persist on containers without S3
6. APScheduler incompatible with Vercel serverless
7. alembic.ini has no sqlalchemy.url (env.py sets dynamically)

## Development Commands
```bash
# Run locally
uvicorn app.main:app --reload --port 8000

# Run tests
pytest tests/ -v

# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Check DB state
python startup.py
```

## Conventions
- All prices stored in **pence** (integer) in the database
- UUIDs for all primary keys
- JSONB for flexible/nested data (locations, access details, preferences)
- Leads identified by short `token` (12-char hex) in URLs
- Companies identified by `slug` in URLs
- All datetimes are timezone-aware (UTC)
- Images always converted to JPEG before storage
- Rate limiting on auth endpoints (5/min) and API endpoints (30/min)
