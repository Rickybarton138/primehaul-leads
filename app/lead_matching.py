"""
PrimeHaul Leads -- Lead matching & distribution engine.

After a customer submits a lead, this module finds removal companies
whose service area covers the pickup location and whose preferences
match the lead characteristics, then sends each company a notification.
"""

import logging
from datetime import datetime, timezone

from app.geo import calculate_distance_miles
from app.models import Company, Lead, LeadNotification

logger = logging.getLogger("primehaul.matching")


# ---------------------------------------------------------------------------
# Core matching logic
# ---------------------------------------------------------------------------
def find_matching_companies(lead, db) -> list:
    """Find active companies whose service area covers the lead's pickup
    location and whose preferences match the lead.

    Matching criteria (all must pass):
    1. Company is active and has a base location set.
    2. Distance from company base to lead pickup <= company.service_radius_miles.
    3. If company has pref_min_cbm, the lead's total_cbm must be >= that value.
    4. If company has pref_max_cbm, the lead's total_cbm must be <= that value.
    5. If company has pref_property_types (JSONB list), the lead's property_type
       must be in that list.

    Returns:
        A list of Company objects that match all criteria.
    """
    # Extract pickup coordinates from the lead's JSONB pickup field
    pickup = lead.pickup or {}
    pickup_lat = pickup.get("lat")
    pickup_lng = pickup.get("lng")

    if pickup_lat is None or pickup_lng is None:
        logger.warning(
            "Lead %s has no pickup coordinates -- cannot match companies", lead.id
        )
        return []

    # Fetch all active companies that have a base location configured
    companies = (
        db.query(Company)
        .filter(
            Company.is_active.is_(True),
            Company.base_lat.isnot(None),
            Company.base_lng.isnot(None),
        )
        .all()
    )

    lead_cbm = float(lead.total_cbm or 0)
    lead_property_type = (lead.property_type or "").strip()

    matched = []

    for company in companies:
        # --- Distance check ---
        distance = calculate_distance_miles(
            company.base_lat,
            company.base_lng,
            float(pickup_lat),
            float(pickup_lng),
        )
        radius = company.service_radius_miles or 30
        if distance > radius:
            continue

        # --- CBM preference checks ---
        if company.pref_min_cbm is not None:
            if lead_cbm < float(company.pref_min_cbm):
                continue

        if company.pref_max_cbm is not None:
            if lead_cbm > float(company.pref_max_cbm):
                continue

        # --- Property type preference check ---
        if company.pref_property_types:
            # pref_property_types is a JSONB array, e.g. ["House", "Flat"]
            allowed_types = company.pref_property_types
            if isinstance(allowed_types, list) and allowed_types:
                # Case-insensitive comparison
                allowed_lower = [t.lower() for t in allowed_types if t]
                if lead_property_type.lower() not in allowed_lower:
                    continue

        matched.append(company)
        logger.debug(
            "Lead %s matched company %s (distance=%.1f mi)",
            lead.id,
            company.company_name,
            distance,
        )

    logger.info(
        "Lead %s: %d of %d active companies matched",
        lead.id,
        len(matched),
        len(companies),
    )
    return matched


# ---------------------------------------------------------------------------
# Background task: distribute a lead to matching companies
# ---------------------------------------------------------------------------
def distribute_lead(lead_id, db_session_factory=None):
    """Called as a background task after lead submission.

    Finds matching companies and sends them email notifications.

    Args:
        lead_id: UUID (or string) of the submitted lead.
        db_session_factory: A callable that returns a new SQLAlchemy Session.
            Defaults to ``SessionLocal`` from ``app.database`` when not
            provided.  A dedicated session is used because background tasks
            run outside the request lifecycle.
    """
    # Resolve session factory
    if db_session_factory is None:
        from app.database import SessionLocal
        db_session_factory = SessionLocal

    db = db_session_factory()

    try:
        # Load the lead
        lead = db.query(Lead).filter(Lead.id == str(lead_id)).first()
        if lead is None:
            logger.error("distribute_lead: Lead %s not found", lead_id)
            return

        if lead.status != "active":
            logger.info(
                "distribute_lead: Lead %s has status '%s', skipping",
                lead_id,
                lead.status,
            )
            return

        # Find matching companies
        matching_companies = find_matching_companies(lead, db)

        if not matching_companies:
            logger.info("distribute_lead: No matching companies for lead %s", lead_id)
            return

        # Import notification sender (may not be available yet in early dev)
        try:
            from app.notifications import send_lead_alert_email
        except ImportError:
            logger.warning(
                "notifications module not available -- recording matches without emails"
            )
            send_lead_alert_email = None

        # Send customer confirmation email
        try:
            from app.notifications import send_customer_confirmation
            send_customer_confirmation(lead)
        except ImportError:
            pass
        except Exception:
            logger.exception(
                "Failed to send customer confirmation for lead %s", lead_id
            )

        # Distribute to each matching company
        now = datetime.now(timezone.utc)

        for company in matching_companies:
            # Create a notification record
            notification = LeadNotification(
                lead_id=lead.id,
                company_id=company.id,
                sent_at=now,
                notification_method="email",
            )
            db.add(notification)

            # Attempt to send the email notification
            if send_lead_alert_email is not None:
                try:
                    send_lead_alert_email(company, lead)
                except Exception:
                    logger.exception(
                        "Failed to send lead alert to company %s (%s) for lead %s",
                        company.company_name,
                        company.id,
                        lead_id,
                    )

        db.commit()
        logger.info(
            "distribute_lead: Lead %s distributed to %d companies",
            lead_id,
            len(matching_companies),
        )

    except Exception:
        logger.exception("distribute_lead: Unhandled error for lead %s", lead_id)
        db.rollback()
    finally:
        db.close()
