import uuid
from datetime import datetime, timedelta

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
    Numeric, String, Text, func
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ---------------------------------------------------------------------------
# Lead (the core survey/quote record)
# ---------------------------------------------------------------------------
class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("idx_leads_status_submitted", "status", "submitted_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token = Column(String(50), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Location (JSONB: label, lat, lng, city, postcode)
    pickup = Column(JSONB)
    dropoff = Column(JSONB)
    distance_miles = Column(Float)

    # Property info
    property_type = Column(String(100))
    dropoff_property_type = Column(String(100))
    move_date = Column(DateTime(timezone=True))

    # Access parameters (JSONB: floors, has_lift, parking_type, etc.)
    pickup_access = Column(JSONB)
    dropoff_access = Column(JSONB)

    # Customer contact (collected last)
    customer_name = Column(String(255))
    customer_email = Column(String(255), index=True)
    customer_phone = Column(String(50))

    # Inventory totals
    total_cbm = Column(Numeric(10, 2), default=0)
    total_weight_kg = Column(Numeric(10, 2), default=0)
    total_items = Column(Integer, default=0)
    bulky_items = Column(Integer, default=0)
    fragile_items = Column(Integer, default=0)

    # Estimate
    estimate_low = Column(Integer)
    estimate_high = Column(Integer)

    # Status: in_progress -> submitted -> active -> expired
    status = Column(String(50), default="in_progress", index=True)
    submitted_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))

    # Lead pricing
    lead_price_pence = Column(Integer)

    # UTM tracking for ad attribution
    utm_source = Column(String(100))
    utm_medium = Column(String(100))
    utm_campaign = Column(String(100))

    # Viral / referral tracking
    ref_code = Column(String(8), unique=True, index=True)
    referred_by = Column(String(8), index=True)
    share_token = Column(String(16), unique=True, index=True)

    # Relationships
    rooms = relationship("LeadRoom", back_populates="lead", cascade="all, delete-orphan")
    purchases = relationship("LeadPurchase", back_populates="lead")
    notifications = relationship("LeadNotification", back_populates="lead")


# ---------------------------------------------------------------------------
# Lead Rooms
# ---------------------------------------------------------------------------
class LeadRoom(Base):
    __tablename__ = "lead_rooms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    name = Column(String(100), nullable=False)
    summary = Column(Text)

    lead = relationship("Lead", back_populates="rooms")
    items = relationship("LeadItem", back_populates="room", cascade="all, delete-orphan")
    photos = relationship("LeadPhoto", back_populates="room", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Lead Items
# ---------------------------------------------------------------------------
class LeadItem(Base):
    __tablename__ = "lead_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("lead_rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    name = Column(String(255), nullable=False)
    qty = Column(Integer, default=1)
    length_cm = Column(Numeric(10, 2))
    width_cm = Column(Numeric(10, 2))
    height_cm = Column(Numeric(10, 2))
    weight_kg = Column(Numeric(10, 2))
    cbm = Column(Numeric(10, 4))
    bulky = Column(Boolean, default=False)
    fragile = Column(Boolean, default=False)
    item_category = Column(String(50))
    packing_requirement = Column(String(50))
    notes = Column(Text)

    room = relationship("LeadRoom", back_populates="items")


# ---------------------------------------------------------------------------
# Lead Photos
# ---------------------------------------------------------------------------
class LeadPhoto(Base):
    __tablename__ = "lead_photos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id = Column(UUID(as_uuid=True), ForeignKey("lead_rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255))
    storage_path = Column(Text, nullable=False)
    file_size_bytes = Column(Integer)
    mime_type = Column(String(100))

    room = relationship("LeadRoom", back_populates="photos")


# ---------------------------------------------------------------------------
# Company (removal companies that buy leads)
# ---------------------------------------------------------------------------
class Company(Base):
    __tablename__ = "companies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company_name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    phone = Column(String(50))
    password_hash = Column(String(255), nullable=False)

    # Service area
    base_postcode = Column(String(10))
    base_lat = Column(Float)
    base_lng = Column(Float)
    service_radius_miles = Column(Integer, default=30)

    # Preferences
    pref_min_cbm = Column(Numeric(10, 2))
    pref_max_cbm = Column(Numeric(10, 2))
    pref_property_types = Column(JSONB)  # e.g. ["House", "Flat"]
    pref_notification_email = Column(String(255))
    pref_notification_phone = Column(String(50))

    # Stripe
    stripe_customer_id = Column(String(255), unique=True, index=True)

    # Status
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    last_login_at = Column(DateTime(timezone=True))

    # Relationships
    purchases = relationship("LeadPurchase", back_populates="company")
    notifications = relationship("LeadNotification", back_populates="company")


# ---------------------------------------------------------------------------
# Lead Purchase (revenue table)
# ---------------------------------------------------------------------------
class LeadPurchase(Base):
    __tablename__ = "lead_purchases"
    __table_args__ = (
        Index("idx_purchase_company_lead", "company_id", "lead_id", unique=True),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False, index=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    price_pence = Column(Integer, nullable=False)
    stripe_payment_intent_id = Column(String(255), unique=True)
    stripe_checkout_session_id = Column(String(255))
    payment_status = Column(String(50), default="pending", index=True)
    paid_at = Column(DateTime(timezone=True))

    lead = relationship("Lead", back_populates="purchases")
    company = relationship("Company", back_populates="purchases")


# ---------------------------------------------------------------------------
# Lead Notification (tracks which leads were sent to which companies)
# ---------------------------------------------------------------------------
class LeadNotification(Base):
    __tablename__ = "lead_notifications"
    __table_args__ = (
        Index("idx_notification_company_lead", "company_id", "lead_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False, index=True)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    notification_method = Column(String(20), default="email")

    # Funnel tracking
    opened_at = Column(DateTime(timezone=True))
    purchased_at = Column(DateTime(timezone=True))

    lead = relationship("Lead", back_populates="notifications")
    company = relationship("Company", back_populates="notifications")


# ---------------------------------------------------------------------------
# Lead Pricing Tiers (admin-configurable)
# ---------------------------------------------------------------------------
class LeadPricingTier(Base):
    __tablename__ = "lead_pricing_tiers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    min_cbm = Column(Numeric(10, 2), default=0)
    max_cbm = Column(Numeric(10, 2))
    price_pence = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Admin Users
# ---------------------------------------------------------------------------
class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Stripe Events (webhook audit log)
# ---------------------------------------------------------------------------
class StripeEvent(Base):
    __tablename__ = "stripe_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stripe_event_id = Column(String(255), nullable=False, unique=True, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    payload = Column(JSONB, nullable=False)
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
