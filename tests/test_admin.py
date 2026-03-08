"""Tests for admin panel routes."""

from app.models import AdminUser, Lead, Company
from app.auth import hash_password


def _create_admin(db):
    admin = AdminUser(
        email="admin@test.com",
        password_hash=hash_password("testpass123"),
        full_name="Test Admin",
    )
    db.add(admin)
    db.commit()
    return admin


def _login(client):
    resp = client.post(
        "/admin/login",
        data={"email": "admin@test.com", "password": "testpass123"},
        follow_redirects=False,
    )
    return resp


def test_admin_login_page(client):
    resp = client.get("/admin/login")
    assert resp.status_code == 200


def test_admin_login_invalid_credentials(client, db):
    _create_admin(db)
    resp = client.post(
        "/admin/login",
        data={"email": "admin@test.com", "password": "wrongpass"},
    )
    assert resp.status_code == 200  # re-renders login page
    assert b"Invalid" in resp.content


def test_admin_login_success(client, db):
    _create_admin(db)
    resp = _login(client)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/dashboard"


def test_admin_dashboard_requires_auth(client):
    resp = client.get("/admin/dashboard", follow_redirects=False)
    # Should redirect to login or return 401/403
    assert resp.status_code in (303, 401, 403, 302)


def test_admin_dashboard_with_auth(client, db):
    _create_admin(db)
    _login(client)
    resp = client.get("/admin/dashboard")
    assert resp.status_code == 200


def test_admin_leads_page(client, db):
    _create_admin(db)
    _login(client)
    resp = client.get("/admin/leads")
    assert resp.status_code == 200


def test_admin_companies_page(client, db):
    _create_admin(db)
    _login(client)
    resp = client.get("/admin/companies")
    assert resp.status_code == 200


def test_admin_pricing_page(client, db):
    _create_admin(db)
    _login(client)
    resp = client.get("/admin/pricing")
    assert resp.status_code == 200


def test_admin_revenue_page(client, db):
    _create_admin(db)
    _login(client)
    resp = client.get("/admin/revenue")
    assert resp.status_code == 200


def test_admin_analytics_page(client, db):
    _create_admin(db)
    _login(client)
    resp = client.get("/admin/analytics")
    assert resp.status_code == 200


def test_admin_analytics_period_filter(client, db):
    _create_admin(db)
    _login(client)
    for days in [7, 30, 90]:
        resp = client.get(f"/admin/analytics?days={days}")
        assert resp.status_code == 200


def test_admin_errors_page(client, db):
    _create_admin(db)
    _login(client)
    resp = client.get("/admin/errors")
    assert resp.status_code == 200


def test_admin_email_page(client, db):
    _create_admin(db)
    _login(client)
    resp = client.get("/admin/email")
    assert resp.status_code == 200


def test_admin_social_page(client, db):
    _create_admin(db)
    _login(client)
    resp = client.get("/admin/social")
    assert resp.status_code == 200


def test_admin_logout(client, db):
    _create_admin(db)
    _login(client)
    resp = client.post("/admin/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"
