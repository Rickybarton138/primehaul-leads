"""Integration tests for the consumer survey flow."""

import uuid

import pytest
from app.models import Lead, LeadRoom, LeadItem, LeadPhoto


def test_landing_page_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_start_survey_creates_lead(client, db):
    resp = client.get("/start", follow_redirects=False)
    assert resp.status_code == 303
    assert "/survey/" in resp.headers["location"]
    assert "/map" in resp.headers["location"]

    # Lead should exist in DB
    lead = db.query(Lead).first()
    assert lead is not None
    assert lead.status == "in_progress"
    assert lead.ref_code is not None
    assert lead.share_token is not None


def test_start_survey_captures_ref_code(client, db):
    resp = client.get("/start?ref=ABC12345", follow_redirects=False)
    assert resp.status_code == 303

    lead = db.query(Lead).first()
    assert lead.referred_by == "ABC12345"


def test_start_survey_captures_utm_params(client, db):
    resp = client.get("/start?utm_source=google&utm_medium=cpc&utm_campaign=test", follow_redirects=False)
    assert resp.status_code == 303

    lead = db.query(Lead).first()
    assert lead.utm_source == "google"
    assert lead.utm_medium == "cpc"
    assert lead.utm_campaign == "test"


def test_map_page_requires_valid_token(client):
    resp = client.get("/survey/invalidtoken123/map")
    assert resp.status_code == 404


def test_survey_flow_map_page(client, db):
    # Create a lead first
    lead = Lead(token="test123abc", ref_code="TESTREF1", share_token="testsharetoken1")
    db.add(lead)
    db.commit()

    resp = client.get("/survey/test123abc/map")
    assert resp.status_code == 200


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


def test_privacy_page(client):
    resp = client.get("/privacy")
    assert resp.status_code == 200


def test_terms_page(client):
    resp = client.get("/terms")
    assert resp.status_code == 200


def test_share_card_invalid_token(client):
    resp = client.get("/share/nonexistenttoken")
    assert resp.status_code == 404


def test_share_card_valid_token(client, db):
    lead = Lead(
        token="testlead01",
        ref_code="REFCODE1",
        share_token="sharetoken001",
        estimate_low=300,
        estimate_high=500,
        total_cbm=15,
        pickup={"city": "London", "postcode": "SW1A"},
        dropoff={"city": "Manchester", "postcode": "M1"},
    )
    db.add(lead)
    db.commit()

    resp = client.get("/share/sharetoken001")
    assert resp.status_code == 200
