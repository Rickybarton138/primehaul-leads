"""
PrimeHaul Leads -- Stripe billing integration.

Handles per-lead purchases via Stripe Checkout Sessions and processes
webhook events to confirm payments.
"""

import logging
import os
from datetime import datetime, timezone

import stripe
from dotenv import load_dotenv

from app.config import settings
from app.models import LeadNotification, LeadPurchase, StripeEvent

load_dotenv()

logger = logging.getLogger("primehaul.stripe")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

APP_URL = settings.APP_URL.rstrip("/")


# ---------------------------------------------------------------------------
# Customer management
# ---------------------------------------------------------------------------
def ensure_stripe_customer(company, db) -> str:
    """Create or return the Stripe customer ID for a company.

    If the company already has a ``stripe_customer_id`` stored, it is
    returned immediately.  Otherwise a new Stripe Customer is created
    and the ID is persisted on the company record.

    Returns:
        The Stripe customer ID string.
    """
    if company.stripe_customer_id:
        return company.stripe_customer_id

    customer = stripe.Customer.create(
        email=company.email,
        name=company.company_name,
        metadata={"company_id": str(company.id)},
    )

    company.stripe_customer_id = customer.id
    db.commit()

    logger.info(
        "Created Stripe customer %s for company %s (%s)",
        customer.id,
        company.company_name,
        company.id,
    )
    return customer.id


# ---------------------------------------------------------------------------
# Checkout session creation
# ---------------------------------------------------------------------------
def create_lead_purchase_session(company, lead, db) -> dict:
    """Create a Stripe Checkout Session for purchasing a single lead.

    Builds a one-time payment session with the lead price, creates a
    ``LeadPurchase`` record in *pending* state, and returns the checkout
    URL for redirecting the company user.

    Returns:
        A dict with ``url`` (the Checkout redirect URL) and
        ``session_id`` (the Stripe session identifier).

    Raises:
        stripe.error.StripeError: On Stripe API failures.
    """
    # Ensure the company has a Stripe customer record
    customer_id = ensure_stripe_customer(company, db)

    # Build redirect URLs
    success_url = (
        f"{APP_URL}/company/purchase-success"
        f"?session_id={{CHECKOUT_SESSION_ID}}&lead_id={lead.id}"
    )
    cancel_url = f"{APP_URL}/company/leads/{lead.id}/preview"

    # Derive a human-friendly description
    pickup_area = "Unknown"
    dropoff_area = "Unknown"
    if lead.pickup and isinstance(lead.pickup, dict):
        pickup_area = lead.pickup.get("city") or lead.pickup.get("postcode", "Unknown")
    if lead.dropoff and isinstance(lead.dropoff, dict):
        dropoff_area = (
            lead.dropoff.get("city") or lead.dropoff.get("postcode", "Unknown")
        )

    product_name = f"Moving Lead: {pickup_area} to {dropoff_area}"
    product_description = (
        f"{lead.total_cbm or 0} CBM | {lead.total_items or 0} items | "
        f"{lead.property_type or 'N/A'}"
    )

    # Create the Stripe Checkout Session
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": "gbp",
                    "unit_amount": lead.lead_price_pence,
                    "product_data": {
                        "name": product_name,
                        "description": product_description,
                    },
                },
                "quantity": 1,
            }
        ],
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "type": "lead_purchase",
            "lead_id": str(lead.id),
            "company_id": str(company.id),
        },
    )

    # Create a pending purchase record in our database
    purchase = LeadPurchase(
        lead_id=lead.id,
        company_id=company.id,
        price_pence=lead.lead_price_pence,
        stripe_checkout_session_id=session.id,
        payment_status="pending",
    )
    db.add(purchase)
    db.commit()

    logger.info(
        "Created checkout session %s for company %s, lead %s (%s pence)",
        session.id,
        company.id,
        lead.id,
        lead.lead_price_pence,
    )

    return {"url": session.url, "session_id": session.id}


# ---------------------------------------------------------------------------
# Webhook: checkout.session.completed
# ---------------------------------------------------------------------------
def handle_checkout_completed(session_data: dict, db):
    """Handle a Stripe ``checkout.session.completed`` webhook event.

    Marks the corresponding ``LeadPurchase`` as paid, records the
    payment intent ID, and updates the ``LeadNotification`` funnel
    timestamp.

    Args:
        session_data: The ``session`` object from the Stripe event payload.
        db: An active SQLAlchemy session.
    """
    metadata = session_data.get("metadata", {})
    lead_id = metadata.get("lead_id")
    company_id = metadata.get("company_id")
    checkout_session_id = session_data.get("id")
    payment_intent_id = session_data.get("payment_intent")

    if not checkout_session_id:
        logger.warning("checkout.session.completed event missing session id")
        return

    # Only process lead_purchase events
    if metadata.get("type") != "lead_purchase":
        logger.info(
            "Ignoring checkout.session.completed with type=%s",
            metadata.get("type"),
        )
        return

    # Find the pending purchase record
    purchase = (
        db.query(LeadPurchase)
        .filter(LeadPurchase.stripe_checkout_session_id == checkout_session_id)
        .first()
    )

    if purchase is None:
        logger.error(
            "No LeadPurchase found for checkout session %s", checkout_session_id
        )
        return

    if purchase.payment_status == "paid":
        logger.info(
            "Purchase %s already marked as paid -- idempotent skip", purchase.id
        )
        return

    # Mark the purchase as paid
    now = datetime.now(timezone.utc)
    purchase.payment_status = "paid"
    purchase.paid_at = now
    purchase.stripe_payment_intent_id = payment_intent_id

    # Update the corresponding LeadNotification's purchased_at timestamp
    if lead_id and company_id:
        notification = (
            db.query(LeadNotification)
            .filter(
                LeadNotification.lead_id == lead_id,
                LeadNotification.company_id == company_id,
            )
            .first()
        )
        if notification:
            notification.purchased_at = now

    db.commit()

    logger.info(
        "Payment confirmed: purchase %s, session %s, lead %s, company %s",
        purchase.id,
        checkout_session_id,
        lead_id,
        company_id,
    )

    # Send purchase confirmation email
    try:
        from app.notifications import send_purchase_confirmation
        from app.models import Company, Lead

        company = db.query(Company).filter(Company.id == company_id).first()
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if company and lead:
            send_purchase_confirmation(company, lead)
    except ImportError:
        logger.warning("notifications module not available -- skipping confirmation email")
    except Exception:
        logger.exception(
            "Failed to send purchase confirmation for lead %s, company %s",
            lead_id,
            company_id,
        )


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------
def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    """Verify a Stripe webhook signature and return the parsed event.

    Args:
        payload: The raw request body bytes.
        sig_header: The ``Stripe-Signature`` header value.

    Returns:
        The verified Stripe event as a dict-like object.

    Raises:
        stripe.error.SignatureVerificationError: If the signature is invalid.
        ValueError: If the webhook secret is not configured.
    """
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise ValueError(
            "STRIPE_WEBHOOK_SECRET is not configured -- cannot verify webhooks"
        )

    event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    return event


# ---------------------------------------------------------------------------
# Webhook handler (called from a route in main.py or company_routes.py)
# ---------------------------------------------------------------------------
def handle_stripe_webhook(payload: bytes, sig_header: str, db) -> dict:
    """Top-level webhook handler that verifies the signature, logs the
    event, and dispatches to the appropriate handler.

    This function is designed to be called from a FastAPI route::

        @router.post("/webhooks/stripe")
        async def stripe_webhook(request: Request, db=Depends(get_db)):
            payload = await request.body()
            sig = request.headers.get("stripe-signature", "")
            result = handle_stripe_webhook(payload, sig, db)
            return result

    Args:
        payload: Raw request body bytes.
        sig_header: The ``Stripe-Signature`` header value.
        db: An active SQLAlchemy session.

    Returns:
        A dict with ``status`` key indicating the result.
    """
    # Verify signature
    event = verify_webhook_signature(payload, sig_header)

    event_type = event.get("type", "")
    event_id = event.get("id", "")

    # Idempotency: check if we have already processed this event
    existing = (
        db.query(StripeEvent)
        .filter(StripeEvent.stripe_event_id == event_id)
        .first()
    )
    if existing and existing.processed:
        logger.info("Stripe event %s already processed -- skipping", event_id)
        return {"status": "already_processed"}

    # Log the event
    if existing is None:
        stripe_event = StripeEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            payload=event,
            processed=False,
        )
        db.add(stripe_event)
        db.flush()
    else:
        stripe_event = existing

    # Dispatch by event type
    if event_type == "checkout.session.completed":
        session_data = event.get("data", {}).get("object", {})
        handle_checkout_completed(session_data, db)
        stripe_event.processed = True
        db.commit()
        logger.info("Processed Stripe event: %s (%s)", event_type, event_id)
        return {"status": "processed", "event_type": event_type}

    # Unhandled event types are acknowledged but not processed
    stripe_event.processed = True
    db.commit()
    logger.info("Acknowledged unhandled Stripe event: %s (%s)", event_type, event_id)
    return {"status": "ignored", "event_type": event_type}
