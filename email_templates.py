"""
email_templates.py — HTML Email Templates
──────────────────────────────────────────
Centralized email rendering with improved UI/UX.
Handles multi-job grouping from single messages.
"""

import html
import smtplib
import logging
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from itertools import groupby
from operator import itemgetter

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
RECIPIENT_EMAILS = [e.strip() for e in os.environ["YOUR_EMAIL"].split(",") if e.strip()]

# Shared <head> boilerplate: locks clients out of auto-dark-mode inversion,
# with a defensive re-assert for clients that ignore the meta tag, plus a
# mobile breakpoint that collapses multi-column tables to stacked rows.
_HEAD_STYLE = """<meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <style>
    :root { color-scheme: light; supported-color-schemes: light; }
    @media (prefers-color-scheme: dark) {
      body, .email-bg { background:#f1f5f9 !important; }
      .card { background:#ffffff !important; }
    }
    @media screen and (max-width:600px) {
      .container { width:100% !important; padding:12px !important; }
      .kpi-table td { display:block !important; width:100% !important; margin-bottom:8px !important; }
      .detail-td { display:block !important; width:100% !important; }
      .detail-spacer { display:none !important; }
      .btn-cell { display:block !important; width:100% !important; padding-right:0 !important; }
    }
  </style>"""

_HEADER_BACKGROUNDS = {
    "solid-blue": "background:#2563eb;",
    "gradient-green": "background:linear-gradient(135deg,#059669 0%,#0d9488 100%);",
    "gradient-purple": "background:linear-gradient(135deg,#1e40af 0%,#7c3aed 50%,#db2777 100%);",
}


def _escape(text: str) -> str:
    """HTML-escape user content to prevent XSS."""
    return html.escape(str(text)) if text else ""


def _telegram_link(group_username: str | None, msg_id: int | None) -> str | None:
    """Generate Telegram deep link for public groups."""
    if group_username and msg_id:
        return f"https://t.me/{group_username}/{msg_id}"
    return None


def _truncate_then_escape(text: str, limit: int) -> tuple[str, bool]:
    """Slice raw text to `limit` chars, then escape — avoids cutting an HTML entity in half."""
    text = str(text) if text else ""
    truncated = len(text) > limit
    return _escape(text[:limit]), truncated


def _email_header(eyebrow: str, title: str, subtitle: str, style: str) -> str:
    """Render the gradient/solid header block shared by all templates."""
    bg = _HEADER_BACKGROUNDS.get(style, _HEADER_BACKGROUNDS["solid-blue"])
    return f"""
    <div style="{bg}border-radius:16px;padding:28px 32px;margin-bottom:24px;color:#ffffff;text-align:center;">
      <div style="font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;opacity:0.85;margin-bottom:8px;">{eyebrow}</div>
      <h1 style="margin:0 0 6px;font-size:24px;font-weight:800;">{title}</h1>
      <p style="margin:0;opacity:0.92;font-size:14px;">{subtitle}</p>
    </div>"""


def _build_quoted_post(original: str, limit: int = 350) -> str:
    """Always-visible quoted excerpt of the raw Telegram post (replaces the unreliable <details> toggle)."""
    excerpt, truncated = _truncate_then_escape(original, limit)
    if not excerpt:
        return ""
    ellipsis = "…" if truncated else ""
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;">
        <tr><td style="border-left:3px solid #cbd5e1;padding:10px 14px;background:#f8fafc;border-radius:0 8px 8px 0;">
          <div style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Original post</div>
          <div style="font-size:12px;line-height:1.6;color:#475569;white-space:pre-wrap;word-break:break-word;">{excerpt}{ellipsis}</div>
        </td></tr>
      </table>"""


def _build_cta_row(link: str, tg_link: str | None) -> str:
    """Apply Now / View on Telegram button row, with MSO bulletproof-button fallback for Outlook."""
    has_apply = bool(link) and link.lower() not in ("not found", "none", "n/a")
    if not has_apply and not tg_link:
        return ""

    apply_cell = ""
    if has_apply:
        apply_cell = f"""
        <td class="btn-cell" style="padding-right:8px;padding-bottom:8px;">
          <!--[if mso]>
          <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" href="{link}" style="height:40px;v-text-anchor:middle;width:160px;" arcsize="20%" fillcolor="#2563eb" stroke="f">
          <center style="color:#ffffff;font-family:sans-serif;font-size:14px;font-weight:600;">Apply Now &rarr;</center>
          </v:roundrect>
          <![endif]-->
          <!--[if !mso]><!-->
          <a href="{link}" style="display:inline-block;padding:11px 22px;background:#2563eb;color:#ffffff;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;line-height:1;">Apply Now →</a>
          <!--<![endif]-->
        </td>"""

    tg_cell = ""
    if tg_link:
        tg_cell = f"""
        <td class="btn-cell" style="padding-bottom:8px;">
          <!--[if mso]>
          <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" href="{tg_link}" style="height:36px;v-text-anchor:middle;width:150px;" arcsize="20%" fillcolor="#0f7fb5" stroke="f">
          <center style="color:#ffffff;font-family:sans-serif;font-size:12px;font-weight:600;">View on Telegram</center>
          </v:roundrect>
          <![endif]-->
          <!--[if !mso]><!-->
          <a href="{tg_link}" style="display:inline-block;padding:9px 18px;background:#0f7fb5;color:#ffffff;border-radius:8px;text-decoration:none;font-size:12px;font-weight:600;">View on Telegram</a>
          <!--<![endif]-->
        </td>"""

    return f"""
      <table role="presentation" cellpadding="0" cellspacing="0" style="margin-bottom:2px;">
        <tr>{apply_cell}{tg_cell}</tr>
      </table>"""


def _build_meta_row(source: str, time_str: str) -> str:
    """Source + time row — table-based equivalent of justify-content:space-between."""
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:12px 0;">
        <tr>
          <td align="left" style="font-size:12px;color:#475569;">
            <span style="background:#f1f5f9;padding:4px 10px;border-radius:20px;">📢 {source}</span>
          </td>
          <td align="right" style="font-size:12px;color:#64748b;white-space:nowrap;">🕐 {time_str}</td>
        </tr>
      </table>"""


def _build_empty_state(stats: dict) -> str:
    """Informative empty state for the report email when no jobs matched."""
    scanned = stats.get("total_scanned", 0)
    posts = stats.get("job_posts", 0)
    return f"""
    <div style="background:#ffffff;border:1px dashed #cbd5e1;border-radius:12px;padding:40px 24px;text-align:center;">
      <div style="font-size:32px;margin-bottom:8px;">🔍</div>
      <div style="font-size:16px;font-weight:700;color:#0f172a;margin-bottom:4px;">No matches this time</div>
      <div style="font-size:13px;color:#64748b;">We scanned {scanned} message(s) and found {posts} job post(s), but none matched your profile.</div>
    </div>"""


def _build_compact_job_rows(jobs: list[dict]) -> str:
    """Dense one-row-per-job rendering for large message groups (>5 jobs in one post)."""
    rows = ""
    for job in jobs:
        title = _escape(job.get("title", "Unknown Role"))
        company = _escape(job.get("company", "Unknown"))
        location = _escape(job.get("location", "Unknown"))
        salary = _escape(job.get("salary", "Not mentioned"))
        link = _escape(job.get("link", ""))

        apply_cell = ""
        if link and link.lower() not in ("not found", "none", "n/a"):
            apply_cell = (
                f'<a href="{link}" style="display:inline-block;padding:5px 12px;'
                f'background:#2563eb;color:#fff;border-radius:6px;text-decoration:none;'
                f'font-weight:600;font-size:12px;white-space:nowrap;">Apply →</a>'
            )

        rows += f"""
        <tr>
          <td style="padding:10px 8px;border-bottom:1px solid #f1f5f9;vertical-align:top;">
            <div style="font-size:13px;font-weight:600;color:#0f172a;">{title}</div>
            <div style="font-size:12px;color:#64748b;">{company} • {location} • {salary}</div>
          </td>
          <td align="right" style="padding:10px 8px;border-bottom:1px solid #f1f5f9;vertical-align:top;white-space:nowrap;">
            {apply_cell}
          </td>
        </tr>"""

    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        {rows}
      </table>"""


def _build_job_card(job: dict, index: int, show_message_header: bool = False, group_count: int = 1) -> str:
    """Render a single job match card. CTA is promoted right under the header for scannability."""
    title = _escape(job.get("title", "Unknown Role"))
    company = _escape(job.get("company", "Unknown"))
    location = _escape(job.get("location", "Unknown"))
    salary = _escape(job.get("salary", "Not mentioned"))
    link = _escape(job.get("link", ""))
    reason = _escape(job.get("reason", ""))
    source = _escape(job.get("source", ""))
    time_str = _escape(job.get("time", ""))

    tg_link = _telegram_link(job.get("group_username"), job.get("msg_id"))
    cta_html = _build_cta_row(link, tg_link)
    meta_html = _build_meta_row(source, time_str)
    quoted_html = _build_quoted_post(job.get("original", ""))

    return f"""
    <div class="card" style="background:#ffffff;border-radius:12px;padding:24px;margin-bottom:12px;
                border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <!-- Header -->
      <div style="margin-bottom:14px;">
        <h3 style="margin:0 0 4px;color:#0f172a;font-size:18px;font-weight:700;">{title}</h3>
        <p style="margin:0;color:#475569;font-size:14px;">{company}</p>
      </div>

      <!-- CTA -->
      {cta_html}

      <!-- Details Grid -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:14px 0;">
        <tr>
          <td class="detail-td" width="50%" valign="top" style="padding:10px 12px;background:#f8fafc;border-radius:8px;">
            <span style="display:block;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;font-weight:600;">Location</span>
            <span style="font-size:14px;color:#0f172a;font-weight:600;">{location}</span>
          </td>
          <td class="detail-spacer" width="8"></td>
          <td class="detail-td" width="50%" valign="top" style="padding:10px 12px;background:#f8fafc;border-radius:8px;">
            <span style="display:block;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;font-weight:600;">Salary</span>
            <span style="font-size:14px;color:#0f172a;font-weight:600;">{salary}</span>
          </td>
        </tr>
      </table>

      <!-- Match Reason -->
      <div style="background:#ecfdf5;border-radius:8px;padding:10px 14px;margin-bottom:2px;border-left:3px solid #10b981;">
        <span style="font-size:13px;color:#065f46;">✅ {reason}</span>
      </div>

      <!-- Meta -->
      {meta_html}

      <!-- Original Post -->
      {quoted_html}
    </div>"""


def _build_message_group(jobs: list[dict], group_num: int) -> str:
    """Render a group of jobs from the same message."""
    count = len(jobs)
    if count <= 1:
        return _build_job_card(jobs[0], group_num)

    source = _escape(jobs[0].get("source", ""))
    time_str = _escape(jobs[0].get("time", ""))
    tg_link = _telegram_link(jobs[0].get("group_username"), jobs[0].get("msg_id"))

    if count > 5:
        # Bulk-hiring post: drop per-job reason callouts, use dense rows to stay scannable.
        body_html = _build_compact_job_rows(jobs)
    else:
        cards = ""
        for job in jobs:
            title = _escape(job.get("title", "Unknown Role"))
            company = _escape(job.get("company", "Unknown"))
            location = _escape(job.get("location", "Unknown"))
            salary = _escape(job.get("salary", "Not mentioned"))
            link = _escape(job.get("link", ""))
            reason = _escape(job.get("reason", ""))

            apply_html = ""
            if link and link.lower() not in ("not found", "none", "n/a"):
                apply_html = (
                    f'<a href="{link}" style="display:inline-block;padding:6px 14px;'
                    f'background:#2563eb;color:#fff;border-radius:6px;text-decoration:none;'
                    f'font-weight:600;font-size:12px;white-space:nowrap;">Apply →</a>'
                )

            cards += f"""
            <div style="background:#ffffff;border-radius:8px;padding:16px;margin-bottom:8px;border:1px solid #e2e8f0;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
                <td valign="top">
                  <h4 style="margin:0 0 4px;color:#0f172a;font-size:15px;">{title}</h4>
                  <p style="margin:0 0 8px;color:#475569;font-size:13px;">{company} • {location} • {salary}</p>
                </td>
                <td valign="top" align="right" style="white-space:nowrap;padding-left:8px;">{apply_html}</td>
              </tr></table>
              <div style="background:#ecfdf5;border-radius:6px;padding:8px 12px;">
                <span style="font-size:12px;color:#065f46;">✅ {reason}</span>
              </div>
            </div>"""
        body_html = cards

    tg_link_html = ""
    if tg_link:
        tg_link_html = (
            f'<a href="{tg_link}" style="display:inline-block;margin-top:8px;padding:5px 12px;'
            f'background:#0f7fb5;color:#fff;border-radius:5px;text-decoration:none;font-size:11px;'
            f'font-weight:600;">View on Telegram</a>'
        )

    quoted_html = _build_quoted_post(jobs[0].get("original", ""))

    return f"""
    <div class="card" style="background:#fefce8;border-radius:12px;padding:20px;margin-bottom:16px;
                border:1px solid #fde047;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <!-- Group Header -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
        <tr>
          <td valign="middle" style="white-space:nowrap;">
            <span style="background:#b45309;color:#fff;font-size:11px;font-weight:700;padding:4px 10px;
                   border-radius:20px;text-transform:uppercase;letter-spacing:0.3px;">{count} Matches · 1 Message</span>
          </td>
          <td valign="middle" style="padding-left:10px;font-size:12px;color:#64748b;">📢 {source} &nbsp;·&nbsp; 🕐 {time_str}</td>
        </tr>
      </table>

      <!-- Individual Jobs -->
      {body_html}

      <!-- Shared Original Post -->
      {quoted_html}
      {tg_link_html}
    </div>"""


def _group_jobs_by_message(jobs: list[dict]) -> list[list[dict]]:
    """Group jobs that come from the same message (same original text + source + time)."""
    if not jobs:
        return []

    # Create a grouping key from source + time + first 200 chars of original
    def group_key(job):
        return (job.get("source", ""), job.get("time", ""), job.get("original", "")[:200])

    sorted_jobs = sorted(jobs, key=group_key)
    groups = []
    for _, group_iter in groupby(sorted_jobs, key=group_key):
        groups.append(list(group_iter))
    return groups


def render_report_email(jobs: list[dict], from_date: str, stats: dict) -> str:
    """Render the full historical scan report HTML email."""
    job_groups = _group_jobs_by_message(jobs)

    if job_groups:
        cards_html = ""
        for i, group in enumerate(job_groups, 1):
            cards_html += _build_message_group(group, i)
    else:
        cards_html = _build_empty_state(stats)

    total_matches = len(jobs)
    total_messages_with_matches = len(job_groups)
    batches_used = stats.get("total_batches", 0)
    tokens_used = stats.get("total_tokens", 0)

    header_html = _email_header(
        "📊 SCAN REPORT",
        "Job Scan Report",
        f"Scanned since <strong>{_escape(from_date)}</strong>",
        "gradient-purple",
    )

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">{_HEAD_STYLE}</head>
<body class="email-bg" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;padding:0;margin:0;">
  <div class="container" style="max-width:700px;margin:0 auto;padding:24px;">

    {header_html}

    <!-- KPI Stats Row -->
    <div style="margin-bottom:24px;">
      <table role="presentation" class="kpi-table" width="100%" style="border-collapse:separate;border-spacing:8px;" cellpadding="0" cellspacing="0">
        <tr>
          <td class="kpi-cell" style="background:#fff;border-radius:10px;padding:16px;text-align:center;width:20%;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <div style="font-size:22px;font-weight:800;color:#2563eb;">{stats.get('total_scanned', 0)}</div>
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.4px;margin-top:4px;">Scanned</div>
          </td>
          <td class="kpi-cell" style="background:#fff;border-radius:10px;padding:16px;text-align:center;width:20%;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <div style="font-size:22px;font-weight:800;color:#f59e0b;">{stats.get('job_posts', 0)}</div>
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.4px;margin-top:4px;">Job Posts</div>
          </td>
          <td class="kpi-cell" style="background:#fff;border-radius:10px;padding:16px;text-align:center;width:20%;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <div style="font-size:22px;font-weight:800;color:#10b981;">{total_matches}</div>
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.4px;margin-top:4px;">Matches</div>
          </td>
          <td class="kpi-cell" style="background:#fff;border-radius:10px;padding:16px;text-align:center;width:20%;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <div style="font-size:22px;font-weight:800;color:#8b5cf6;">{batches_used}</div>
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.4px;margin-top:4px;">LLM Batches</div>
          </td>
          <td class="kpi-cell" style="background:#fff;border-radius:10px;padding:16px;text-align:center;width:20%;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <div style="font-size:22px;font-weight:800;color:#ec4899;">{tokens_used:,}</div>
            <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.4px;margin-top:4px;">Tokens</div>
          </td>
        </tr>
      </table>
    </div>

    <!-- Section Header -->
    <div style="margin-bottom:16px;">
      <h2 style="margin:0;color:#0f172a;font-size:20px;font-weight:700;">
        Matched Jobs
        <span style="font-size:13px;font-weight:500;color:#64748b;margin-left:8px;">
          ({total_matches} jobs from {total_messages_with_matches} messages)
        </span>
      </h2>
    </div>

    <!-- Job Cards -->
    {cards_html}

    <!-- Footer -->
    <div style="text-align:center;padding:24px 0 8px;border-top:1px solid #e2e8f0;margin-top:24px;">
      <p style="margin:0;color:#64748b;font-size:12px;">
        Generated by Job Scraper Bot • {datetime.now().strftime("%Y-%m-%d %H:%M")}
      </p>
    </div>

  </div>
</body>
</html>"""


def render_digest_email(jobs: list[dict], period_label: str) -> str:
    """Render a real-time digest email with accumulated matches."""
    job_groups = _group_jobs_by_message(jobs)

    cards_html = ""
    for i, group in enumerate(job_groups, 1):
        cards_html += _build_message_group(group, i)

    total_matches = len(jobs)

    header_html = _email_header(
        "🔔 LIVE DIGEST",
        "Live Job Matches",
        f"{total_matches} new match(es) • {_escape(period_label)}",
        "gradient-green",
    )

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">{_HEAD_STYLE}</head>
<body class="email-bg" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;padding:0;margin:0;">
  <div class="container" style="max-width:700px;margin:0 auto;padding:24px;">

    {header_html}

    <!-- Job Cards -->
    {cards_html}

    <!-- Footer -->
    <div style="text-align:center;padding:20px 0 8px;border-top:1px solid #e2e8f0;margin-top:20px;">
      <p style="margin:0;color:#64748b;font-size:12px;">
        Real-time Telegram Job Scanner • {datetime.now().strftime("%Y-%m-%d %H:%M")}
      </p>
    </div>

  </div>
</body>
</html>"""


def render_instant_email(job: dict) -> str:
    """Render a single-job instant notification email."""
    card = _build_job_card(job, 1)
    title = _escape(job.get("title", "New Role"))
    company = _escape(job.get("company", "Unknown"))

    header_html = _email_header(
        "🎯 INSTANT MATCH",
        "New Job Match Found",
        f"{title} at {company}",
        "solid-blue",
    )

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">{_HEAD_STYLE}</head>
<body class="email-bg" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;padding:0;margin:0;">
  <div class="container" style="max-width:700px;margin:0 auto;padding:24px;">

    {header_html}

    {card}

    <!-- Footer -->
    <div style="text-align:center;padding:16px 0 8px;">
      <p style="margin:0;color:#64748b;font-size:12px;">
        Real-time Telegram Job Scanner • {datetime.now().strftime("%Y-%m-%d %H:%M")}
      </p>
    </div>

  </div>
</body>
</html>"""


def send_email(subject: str, html_body: str):
    """Send an HTML email to configured recipients."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = ", ".join(RECIPIENT_EMAILS)
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.sendmail(SMTP_USER, RECIPIENT_EMAILS, msg.as_string())
        log.info("✅ Email sent to %d recipient(s)", len(RECIPIENT_EMAILS))
    except Exception as e:
        log.error("Email error: %s", e)


def send_report_email(jobs: list[dict], from_date: str, stats: dict):
    """Send the historical scan report email."""
    html_body = render_report_email(jobs, from_date, stats)
    subject = f"📊 Job Scan Report — {len(jobs)} matches since {from_date}"
    send_email(subject, html_body)


def send_digest_email(jobs: list[dict], period_label: str):
    """Send a real-time digest email."""
    html_body = render_digest_email(jobs, period_label)
    subject = f"🎯 {len(jobs)} New Job Match(es) — {period_label}"
    send_email(subject, html_body)


def send_instant_match_email(job: dict):
    """Send a single instant match notification."""
    html_body = render_instant_email(job)
    subject = f"🎯 Job Match: {job.get('title', 'New Role')} at {job.get('company', 'Unknown')}"
    send_email(subject, html_body)
