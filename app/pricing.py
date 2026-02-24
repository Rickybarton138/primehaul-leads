"""
Simplified estimate calculator using fixed platform rates.
Not per-company - uses UK average removal pricing.
"""
from decimal import Decimal
from app.geo import calculate_distance_miles

# Fixed platform pricing (UK averages)
BASE_FEE = 250
PRICE_PER_CBM = 35
BULKY_ITEM_FEE = 25
FRAGILE_ITEM_FEE = 15
WEIGHT_THRESHOLD_KG = 1000
PRICE_PER_KG_OVER = 0.50
PRICE_PER_MILE = 1.50
FREE_MILES = 10

# Access difficulty fees
PRICE_PER_FLOOR = 15
NO_LIFT_SURCHARGE = 50
PARKING_FEES = {"driveway": 0, "street": 25, "permit": 40, "limited": 60}
PARKING_DISTANCE_PER_50M = 10
NARROW_ACCESS_FEE = 35
TIME_RESTRICTION_FEE = 25
BOOKING_REQUIRED_FEE = 20
OUTDOOR_STEPS_PER_5 = 15
OUTDOOR_PATH_FEE = 20

# Estimate range multipliers
LOW_MULTIPLIER = 0.85
HIGH_MULTIPLIER = 1.25


def _access_cost(access_data: dict) -> float:
    """Calculate access difficulty surcharges from JSONB access data."""
    if not access_data:
        return 0.0

    cost = 0.0
    floors = access_data.get("floors", 0) or 0
    cost += floors * PRICE_PER_FLOOR

    if floors > 0 and not access_data.get("has_lift", False):
        cost += NO_LIFT_SURCHARGE

    parking = access_data.get("parking_type", "driveway")
    cost += PARKING_FEES.get(parking, 0)

    parking_distance = access_data.get("parking_distance_m", 0) or 0
    if parking_distance > 0:
        increments = max(1, parking_distance // 50)
        cost += increments * PARKING_DISTANCE_PER_50M

    if access_data.get("narrow_access"):
        cost += NARROW_ACCESS_FEE
    if access_data.get("time_restriction"):
        cost += TIME_RESTRICTION_FEE
    if access_data.get("booking_required"):
        cost += BOOKING_REQUIRED_FEE

    outdoor_steps = access_data.get("outdoor_steps", 0) or 0
    if outdoor_steps > 0:
        cost += (outdoor_steps // 5 + (1 if outdoor_steps % 5 else 0)) * OUTDOOR_STEPS_PER_5

    if access_data.get("outdoor_path"):
        cost += OUTDOOR_PATH_FEE

    return cost


def calculate_lead_estimate(lead) -> dict:
    """
    Calculate a consumer-facing price estimate range.
    Returns dict with estimate_low, estimate_high, and breakdown.
    """
    total_cbm = float(lead.total_cbm or 0)
    total_weight = float(lead.total_weight_kg or 0)
    bulky_count = lead.bulky_items or 0
    fragile_count = lead.fragile_items or 0

    # Base fee
    base = BASE_FEE

    # CBM pricing
    cbm_cost = total_cbm * PRICE_PER_CBM

    # Bulky/fragile surcharges
    bulky_cost = bulky_count * BULKY_ITEM_FEE
    fragile_cost = fragile_count * FRAGILE_ITEM_FEE

    # Weight overage
    weight_cost = 0.0
    if total_weight > WEIGHT_THRESHOLD_KG:
        weight_cost = (total_weight - WEIGHT_THRESHOLD_KG) * PRICE_PER_KG_OVER

    # Distance pricing
    distance_cost = 0.0
    if lead.pickup and lead.dropoff:
        pickup_lat = lead.pickup.get("lat")
        pickup_lng = lead.pickup.get("lng")
        dropoff_lat = lead.dropoff.get("lat")
        dropoff_lng = lead.dropoff.get("lng")
        if all([pickup_lat, pickup_lng, dropoff_lat, dropoff_lng]):
            miles = calculate_distance_miles(pickup_lat, pickup_lng, dropoff_lat, dropoff_lng)
            if miles > FREE_MILES:
                distance_cost = (miles - FREE_MILES) * PRICE_PER_MILE

    # Access difficulty
    pickup_access_cost = _access_cost(lead.pickup_access)
    dropoff_access_cost = _access_cost(lead.dropoff_access)
    access_cost = pickup_access_cost + dropoff_access_cost

    total = base + cbm_cost + bulky_cost + fragile_cost + weight_cost + distance_cost + access_cost
    estimate_low = max(int(total * LOW_MULTIPLIER), 150)
    estimate_high = int(total * HIGH_MULTIPLIER)

    return {
        "estimate_low": estimate_low,
        "estimate_high": estimate_high,
        "breakdown": {
            "base_fee": base,
            "cbm_cost": round(cbm_cost, 2),
            "bulky_surcharge": bulky_cost,
            "fragile_surcharge": fragile_cost,
            "weight_surcharge": round(weight_cost, 2),
            "distance_cost": round(distance_cost, 2),
            "access_cost": round(access_cost, 2),
            "total_before_range": round(total, 2),
        },
    }


def calculate_lead_price_pence(total_cbm: float, db) -> int:
    """Determine lead price in pence based on CBM and pricing tiers."""
    from app.models import LeadPricingTier

    tiers = (
        db.query(LeadPricingTier)
        .filter(LeadPricingTier.is_active == True)
        .order_by(LeadPricingTier.min_cbm)
        .all()
    )

    for tier in tiers:
        max_cbm = float(tier.max_cbm) if tier.max_cbm else 99999
        if float(tier.min_cbm) <= total_cbm <= max_cbm:
            return tier.price_pence

    return 1000  # Default GBP 10.00
