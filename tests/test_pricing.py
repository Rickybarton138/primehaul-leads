"""Unit tests for the pricing module."""

from types import SimpleNamespace
from app.pricing import calculate_lead_estimate, _access_cost


def _make_lead(**kwargs):
    """Build a minimal lead-like object for pricing tests."""
    defaults = {
        "total_cbm": 0,
        "total_weight_kg": 0,
        "bulky_items": 0,
        "fragile_items": 0,
        "pickup": None,
        "dropoff": None,
        "pickup_access": None,
        "dropoff_access": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestCalculateLeadEstimate:
    def test_base_fee_only(self):
        lead = _make_lead()
        result = calculate_lead_estimate(lead)
        assert result["estimate_low"] <= result["estimate_high"]
        assert result["estimate_low"] >= 150  # minimum floor

    def test_cbm_increases_estimate(self):
        small = calculate_lead_estimate(_make_lead(total_cbm=5))
        large = calculate_lead_estimate(_make_lead(total_cbm=50))
        assert large["estimate_high"] > small["estimate_high"]

    def test_bulky_items_add_surcharge(self):
        none_ = calculate_lead_estimate(_make_lead())
        bulky = calculate_lead_estimate(_make_lead(bulky_items=4))
        assert bulky["estimate_high"] > none_["estimate_high"]

    def test_distance_adds_cost(self):
        lead = _make_lead(
            pickup={"lat": 51.5074, "lng": -0.1278},
            dropoff={"lat": 53.4808, "lng": -2.2426},
        )
        result = calculate_lead_estimate(lead)
        assert result["breakdown"]["distance_cost"] > 0


class TestAccessCost:
    def test_empty_access(self):
        assert _access_cost({}) == 0.0
        assert _access_cost(None) == 0.0

    def test_floor_surcharge(self):
        cost = _access_cost({"floors": 3, "has_lift": False})
        assert cost > 0

    def test_lift_reduces_surcharge(self):
        no_lift = _access_cost({"floors": 3, "has_lift": False})
        with_lift = _access_cost({"floors": 3, "has_lift": True})
        assert no_lift > with_lift
