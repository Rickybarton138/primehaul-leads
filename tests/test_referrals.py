"""Tests for the referral reward system."""

from app.models import Lead


def test_referral_fields_default_to_zero(db):
    lead = Lead(token="ref01", ref_code="CODE0001", share_token="share00000001")
    db.add(lead)
    db.commit()
    db.refresh(lead)

    assert lead.referral_count == 0 or lead.referral_count is None
    assert lead.referral_discount_pct == 0 or lead.referral_discount_pct is None


def test_start_survey_captures_referral(client, db):
    # Create the referrer lead
    referrer = Lead(token="referrer01", ref_code="REF00001", share_token="share_referrer1")
    db.add(referrer)
    db.commit()

    # New user starts survey via referral link
    resp = client.get("/start?ref=REF00001", follow_redirects=False)
    assert resp.status_code == 303

    # Check the new lead has referred_by set
    new_lead = db.query(Lead).filter(Lead.token != "referrer01").first()
    assert new_lead is not None
    assert new_lead.referred_by == "REF00001"


def test_unique_ref_codes(db):
    lead1 = Lead(token="unique01", ref_code="UNIQ0001", share_token="share_unique01")
    lead2 = Lead(token="unique02", ref_code="UNIQ0002", share_token="share_unique02")
    db.add_all([lead1, lead2])
    db.commit()

    assert lead1.ref_code != lead2.ref_code


def test_share_token_unique(db):
    lead1 = Lead(token="stok01", ref_code="STREF001", share_token="sharetoken_001")
    lead2 = Lead(token="stok02", ref_code="STREF002", share_token="sharetoken_002")
    db.add_all([lead1, lead2])
    db.commit()

    assert lead1.share_token != lead2.share_token
