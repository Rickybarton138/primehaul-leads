"""Tests for company registration and dashboard."""

from app.models import Company, Lead
from app.auth import hash_password


def _create_company(db, **kwargs):
    defaults = {
        "company_name": "Test Removals Ltd",
        "slug": "test-removals",
        "email": "info@testremovals.co.uk",
        "password_hash": hash_password("company123"),
        "base_postcode": "SW1A 1AA",
        "base_lat": 51.5014,
        "base_lng": -0.1419,
        "service_radius_miles": 30,
    }
    defaults.update(kwargs)
    company = Company(**defaults)
    db.add(company)
    db.commit()
    return company


def test_company_registration_page(client):
    resp = client.get("/company/register")
    assert resp.status_code == 200


def test_company_login_page(client):
    resp = client.get("/company/login")
    assert resp.status_code == 200


def test_company_login_invalid(client, db):
    _create_company(db)
    resp = client.post(
        "/company/login",
        data={"email": "info@testremovals.co.uk", "password": "wrongpass"},
    )
    assert resp.status_code == 200  # re-renders login


def test_company_login_success(client, db):
    _create_company(db)
    resp = client.post(
        "/company/login",
        data={"email": "info@testremovals.co.uk", "password": "company123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_company_dashboard_requires_auth(client):
    resp = client.get("/company/dashboard", follow_redirects=False)
    assert resp.status_code in (303, 401, 403, 302)
