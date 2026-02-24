"""
PrimeHaul Leads -- Email notification system.

Sends transactional emails to customers and removal companies
via SMTP. Silently degrades when SMTP is not configured (dev mode).
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger("primehaul.notifications")

# ---------------------------------------------------------------------------
# Brand constants
# ---------------------------------------------------------------------------
BRAND_COLOR = "#1a73e8"
BRAND_BG = "#f4f6f8"
TEXT_COLOR = "#333333"
MUTED_COLOR = "#777777"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _base_style() -> str:
    """Shared inline CSS preamble for all emails."""
    return (
        "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
        "Helvetica, Arial, sans-serif; color: {text}; line-height: 1.6;"
    ).format(text=TEXT_COLOR)


def _wrap_html(inner_html: str) -> str:
    """Wrap content in a branded email shell with header and footer."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0; padding:0; background-color:{BRAND_BG}; {_base_style()}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{BRAND_BG};">
  <tr><td align="center" style="padding: 32px 16px;">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0"
           style="background-color:#ffffff; border-radius:8px; overflow:hidden;
                  box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
      <!-- Header -->
      <tr>
        <td style="background-color:{BRAND_COLOR}; padding:24px 32px;">
          <h1 style="margin:0; color:#ffffff; font-size:22px; font-weight:600;">
            PrimeHaul Leads
          </h1>
        </td>
      </tr>
      <!-- Body -->
      <tr>
        <td style="padding: 32px;">
          {inner_html}
        </td>
      </tr>
      <!-- Footer -->
      <tr>
        <td style="padding: 20px 32px; border-top: 1px solid #e8e8e8;
                    font-size: 12px; color: {MUTED_COLOR}; text-align: center;">
          &copy; PrimeHaul Leads &mdash; Connecting movers with trusted removal companies.<br>
          You received this email because of activity on primehaul.co.uk.
        </td>
      </tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def _cta_button(url: str, label: str) -> str:
    """Generate an inline-styled call-to-action button."""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="margin: 24px 0;"><tr><td style="border-radius:6px; '
        f"background-color:{BRAND_COLOR};\">"
        f'<a href="{url}" target="_blank" '
        f'style="display:inline-block; padding:14px 32px; color:#ffffff; '
        f"text-decoration:none; font-size:16px; font-weight:600; "
        f'border-radius:6px;">{label}</a>'
        f"</td></tr></table>"
    )


def _info_row(label: str, value: str) -> str:
    """A single key-value row for data tables in emails."""
    return (
        f'<tr><td style="padding:6px 12px 6px 0; font-weight:600; '
        f'color:{MUTED_COLOR}; white-space:nowrap; vertical-align:top;">'
        f'{label}</td><td style="padding:6px 0;">{value}</td></tr>'
    )


def _format_price_pounds(pence: int) -> str:
    """Convert pence to a GBP display string."""
    if pence is None:
        return "N/A"
    return f"\u00a3{pence / 100:,.2f}"


def _pickup_area(lead) -> str:
    """Extract the redacted pickup area from the lead."""
    if lead.pickup and isinstance(lead.pickup, dict):
        return lead.pickup.get("city") or lead.pickup.get("postcode", "Unknown")
    return "Unknown"


def _dropoff_area(lead) -> str:
    """Extract the redacted dropoff area from the lead."""
    if lead.dropoff and isinstance(lead.dropoff, dict):
        return lead.dropoff.get("city") or lead.dropoff.get("postcode", "Unknown")
    return "Unknown"


# ---------------------------------------------------------------------------
# Core email sender
# ---------------------------------------------------------------------------
def _send_email(to_email: str, subject: str, html_body: str):
    """Send an email via SMTP.  Silently fails if SMTP is not configured."""
    if not settings.SMTP_HOST or not settings.SMTP_USERNAME:
        logger.info(
            "[EMAIL] SMTP not configured. Would send to %s: %s", to_email, subject
        )
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("[EMAIL] Sent to %s: %s", to_email, subject)
    except Exception:
        logger.exception("[EMAIL] Failed to send to %s: %s", to_email, subject)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def send_customer_confirmation(lead):
    """Send confirmation email to the customer after they submit their survey.

    Provides a reassuring summary with pickup/dropoff areas, move date,
    and the estimated price range.
    """
    if not lead.customer_email:
        return

    move_date_str = (
        lead.move_date.strftime("%A %d %B %Y") if lead.move_date else "Not specified"
    )
    estimate_str = (
        f"\u00a3{lead.estimate_low:,} &ndash; \u00a3{lead.estimate_high:,}"
        if lead.estimate_low and lead.estimate_high
        else "Pending"
    )

    inner = f"""\
<h2 style="margin:0 0 16px 0; font-size:20px; color:{TEXT_COLOR};">
  Thanks for your moving quote request!
</h2>
<p style="margin:0 0 16px 0; font-size:15px;">
  Hi {lead.customer_name or "there"},
</p>
<p style="margin:0 0 20px 0; font-size:15px;">
  We&rsquo;ve received your details and local removal companies in your area
  will be in touch within <strong>24 hours</strong> with competitive quotes.
</p>
<table role="presentation" cellpadding="0" cellspacing="0"
       style="width:100%; border:1px solid #e8e8e8; border-radius:6px;
              margin-bottom:20px;">
  {_info_row("Pickup area", _pickup_area(lead))}
  {_info_row("Drop-off area", _dropoff_area(lead))}
  {_info_row("Move date", move_date_str)}
  {_info_row("Estimated cost", estimate_str)}
  {_info_row("Total volume", f"{lead.total_cbm or 0} CBM")}
  {_info_row("Total items", str(lead.total_items or 0))}
</table>
<p style="margin:0 0 8px 0; font-size:14px; color:{MUTED_COLOR};">
  You don&rsquo;t need to do anything else. Sit back and wait for quotes
  from verified removal professionals.
</p>"""

    _send_email(
        to_email=lead.customer_email,
        subject="Your PrimeHaul moving quote request has been received",
        html_body=_wrap_html(inner),
    )


def send_lead_alert_email(company, lead):
    """Send an email to a removal company about a new lead in their area.

    Shows redacted information (area-level, not full address) so the
    company must purchase the lead to get full contact details.
    """
    notification_email = company.pref_notification_email or company.email
    if not notification_email:
        return

    move_date_str = (
        lead.move_date.strftime("%A %d %B %Y") if lead.move_date else "Flexible"
    )
    estimate_str = (
        f"\u00a3{lead.estimate_low:,} &ndash; \u00a3{lead.estimate_high:,}"
        if lead.estimate_low and lead.estimate_high
        else "Pending"
    )
    lead_price_str = _format_price_pounds(lead.lead_price_pence)
    app_url = settings.APP_URL.rstrip("/")
    preview_url = f"{app_url}/company/leads/{lead.id}/preview"

    inner = f"""\
<h2 style="margin:0 0 16px 0; font-size:20px; color:{TEXT_COLOR};">
  New moving lead in your area!
</h2>
<p style="margin:0 0 20px 0; font-size:15px;">
  Hi {company.company_name},<br>
  A new lead matching your service area has just been submitted.
</p>
<table role="presentation" cellpadding="0" cellspacing="0"
       style="width:100%; border:1px solid #e8e8e8; border-radius:6px;
              margin-bottom:20px;">
  {_info_row("Pickup area", _pickup_area(lead))}
  {_info_row("Drop-off area", _dropoff_area(lead))}
  {_info_row("Property type", lead.property_type or "Not specified")}
  {_info_row("Volume", f"{lead.total_cbm or 0} CBM")}
  {_info_row("Total items", str(lead.total_items or 0))}
  {_info_row("Estimated value", estimate_str)}
  {_info_row("Move date", move_date_str)}
  {_info_row("Distance", f"{lead.distance_miles or 0:.1f} miles")}
</table>
<div style="background-color:{BRAND_BG}; border-radius:6px; padding:16px;
            text-align:center; margin-bottom:20px;">
  <p style="margin:0 0 4px 0; font-size:14px; color:{MUTED_COLOR};">Lead price</p>
  <p style="margin:0; font-size:28px; font-weight:700; color:{BRAND_COLOR};">
    {lead_price_str}
  </p>
</div>
{_cta_button(preview_url, "View &amp; Buy This Lead")}
<p style="margin:0; font-size:13px; color:{MUTED_COLOR};">
  Full customer details (name, phone, address) are revealed after purchase.
</p>"""

    _send_email(
        to_email=notification_email,
        subject=f"New lead: {_pickup_area(lead)} to {_dropoff_area(lead)} ({lead.total_cbm or 0} CBM)",
        html_body=_wrap_html(inner),
    )


def send_purchase_confirmation(company, lead):
    """Send confirmation to a company after they purchase a lead.

    Includes full customer contact details and addresses now that the
    lead has been paid for.
    """
    notification_email = company.pref_notification_email or company.email
    if not notification_email:
        return

    move_date_str = (
        lead.move_date.strftime("%A %d %B %Y") if lead.move_date else "Flexible"
    )
    pickup_label = (
        lead.pickup.get("label", "N/A") if isinstance(lead.pickup, dict) else "N/A"
    )
    dropoff_label = (
        lead.dropoff.get("label", "N/A") if isinstance(lead.dropoff, dict) else "N/A"
    )
    app_url = settings.APP_URL.rstrip("/")
    purchased_url = f"{app_url}/company/leads/{lead.id}/purchased"

    inner = f"""\
<h2 style="margin:0 0 16px 0; font-size:20px; color:{TEXT_COLOR};">
  Lead purchased successfully!
</h2>
<p style="margin:0 0 20px 0; font-size:15px;">
  Hi {company.company_name},<br>
  Here are the full details for your purchased lead. We recommend
  reaching out within a few hours for the best chance of winning the job.
</p>
<h3 style="margin:0 0 12px 0; font-size:16px; color:{BRAND_COLOR};">
  Customer Details
</h3>
<table role="presentation" cellpadding="0" cellspacing="0"
       style="width:100%; border:1px solid #e8e8e8; border-radius:6px;
              margin-bottom:20px;">
  {_info_row("Name", lead.customer_name or "N/A")}
  {_info_row("Email", lead.customer_email or "N/A")}
  {_info_row("Phone", lead.customer_phone or "N/A")}
</table>
<h3 style="margin:0 0 12px 0; font-size:16px; color:{BRAND_COLOR};">
  Move Details
</h3>
<table role="presentation" cellpadding="0" cellspacing="0"
       style="width:100%; border:1px solid #e8e8e8; border-radius:6px;
              margin-bottom:20px;">
  {_info_row("Pickup address", pickup_label)}
  {_info_row("Drop-off address", dropoff_label)}
  {_info_row("Property type", lead.property_type or "N/A")}
  {_info_row("Move date", move_date_str)}
  {_info_row("Volume", f"{lead.total_cbm or 0} CBM")}
  {_info_row("Total items", str(lead.total_items or 0))}
  {_info_row("Distance", f"{lead.distance_miles or 0:.1f} miles")}
</table>
{_cta_button(purchased_url, "View Full Lead Details")}
<p style="margin:0; font-size:13px; color:{MUTED_COLOR};">
  Tip: Contacting the customer promptly greatly increases your
  conversion rate.
</p>"""

    _send_email(
        to_email=notification_email,
        subject=f"Lead purchased: {lead.customer_name or 'Customer'} - {_pickup_area(lead)} to {_dropoff_area(lead)}",
        html_body=_wrap_html(inner),
    )
