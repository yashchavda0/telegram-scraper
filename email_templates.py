"""
email_templates.py — HTML Email Templates
──────────────────────────────────────────
Centralized email rendering with improved UI/UX.
Handles multi-job grouping from single messages.
"""

import html
import re
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

# Shared <head> boilerplate. Declares real light+dark support (not a light-only
# lock) so Gmail renders our explicit dark palette instead of running its own
# blind auto-invert heuristic on an undeclared email, plus a mobile breakpoint
# that collapses/compacts multi-column tables for narrow screens.
_HEAD_STYLE = """<meta name="color-scheme" content="light dark">
  <meta name="supported-color-schemes" content="light dark">
  <style>
    :root { color-scheme: light dark; supported-color-schemes: light dark; }
    @media (prefers-color-scheme: dark) {
      body, .email-bg { background:#020617 !important; }
      .card { background:#0f172a !important; }
      .card-highlight { background:#241f0c !important; border-color:#a16207 !important; }
      .text-ink { color:#f1f5f9 !important; }
      .text-body { color:#cbd5e1 !important; }
      .text-muted { color:#94a3b8 !important; }
      .bg-surface-soft { background:#1e293b !important; }
      .border-hairline { border-color:#334155 !important; }
      .border-dashed { border-color:#475569 !important; }
      .accent-blue-text { color:#60a5fa !important; }
      .accent-amber-text { color:#fbbf24 !important; }
      .accent-green-bg { background:#052e1f !important; }
      .accent-green-border { border-color:#34d399 !important; }
      .accent-green-text { color:#6ee7b7 !important; }
      .badge-purple-bg { background:#2e1a47 !important; }
      .badge-purple-text { color:#d8b4fe !important; }
      .kpi-diagnostic-value { color:#94a3b8 !important; }
    }
    @media screen and (max-width:600px) {
      .container { width:100% !important; padding:12px !important; }
      .kpi-table { border-spacing:4px !important; }
      .kpi-cell { padding:8px 3px !important; border-radius:8px !important; }
      .kpi-value { font-size:15px !important; }
      .kpi-hero-value { font-size:20px !important; }
      .kpi-label { font-size:7.5px !important; line-height:1.25 !important; letter-spacing:0.1px !important; white-space:normal !important; margin-top:2px !important; }
      .detail-td { display:block !important; width:100% !important; }
      .detail-spacer { display:none !important; }
      .btn-cell { display:block !important; width:100% !important; padding-right:0 !important; }
    }
  </style>"""

_HEADER_BACKGROUNDS = {
    "solid-blue": "background:#2563eb;",
    "gradient-green": "background:linear-gradient(135deg,#059669 0%,#0d9488 100%);",
    "solid-indigo": "background:#3730a3;",
}


def _escape(text: str) -> str:
    """HTML-escape user content to prevent XSS."""
    return html.escape(str(text)) if text else ""


def _minify(rendered_html: str) -> str:
    """Collapse whitespace between tags to keep messages under Gmail's ~102KB clip limit.

    Safe because all dynamic content is HTML-escaped before insertion, so any
    literal '<'/'>' left in the string only ever belongs to structural markup —
    never to job text — meaning whitespace strictly between '>' and '<' is
    always insignificant layout whitespace, not content.
    """
    return re.sub(r">\s+<", "><", rendered_html.strip())


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


def _build_quoted_post(original: str, limit: int = 800) -> str:
    """Scrollable original-post excerpt. <details> collapses on clients that support it
    (Apple Mail, Outlook.com); Gmail (the primary target, mobile and web) doesn't implement
    the toggle and simply renders it always-expanded — which is the behavior that tested
    well on real mobile Gmail."""
    excerpt, truncated = _truncate_then_escape(original, limit)
    if not excerpt:
        return ""
    ellipsis = "…" if truncated else ""
    return f"""
      <details style="margin-top:14px;">
        <summary class="text-muted" style="cursor:pointer;color:#64748b;font-size:12px;font-weight:500;padding:6px 0;">📋 View Original Post</summary>
        <pre class="bg-surface-soft border-hairline text-body" style="background:#f8fafc;padding:14px;border-radius:8px;font-size:12px;line-height:1.5;
             white-space:pre-wrap;word-break:break-word;color:#475569;margin-top:8px;
             border:1px solid #e2e8f0;max-height:300px;overflow-y:auto;">{excerpt}{ellipsis}</pre>
      </details>"""


def _build_cta_row(link: str, tg_link: str | None) -> str:
    """Apply Now / View on Telegram button row."""
    has_apply = bool(link) and link.lower() not in ("not found", "none", "n/a")
    if not has_apply and not tg_link:
        return ""

    apply_cell = ""
    if has_apply:
        apply_cell = f"""
        <td class="btn-cell" style="padding-right:8px;padding-bottom:8px;">
          <a href="{link}" style="display:inline-block;padding:11px 22px;background:#2563eb;color:#ffffff;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;line-height:1;">Apply Now →</a>
        </td>"""

    tg_cell = ""
    if tg_link:
        tg_cell = f"""
        <td class="btn-cell" style="padding-bottom:8px;">
          <a href="{tg_link}" style="display:inline-block;padding:9px 18px;background:#0f7fb5;color:#ffffff;border-radius:8px;text-decoration:none;font-size:12px;font-weight:600;">View on Telegram</a>
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
          <td align="left" class="text-body" style="font-size:12px;color:#475569;">
            <span class="bg-surface-soft" style="background:#f1f5f9;padding:4px 10px;border-radius:20px;">📢 {source}</span>
          </td>
          <td align="right" class="text-muted" style="font-size:12px;color:#64748b;white-space:nowrap;">🕐 {time_str}</td>
        </tr>
      </table>"""


def _build_empty_state(stats: dict) -> str:
    """Informative empty state for the report email when no jobs matched."""
    scanned = stats.get("total_scanned", 0)
    posts = stats.get("job_posts", 0)
    return f"""
    <div class="card border-dashed" style="background:#ffffff;border:1px dashed #cbd5e1;border-radius:12px;padding:40px 24px;text-align:center;">
      <div style="font-size:32px;margin-bottom:8px;">🔍</div>
      <div class="text-ink" style="font-size:16px;font-weight:700;color:#0f172a;margin-bottom:4px;">No matches this time</div>
      <div class="text-muted" style="font-size:13px;color:#64748b;">We scanned {scanned} message(s) and found {posts} job post(s), but none matched your profile.</div>
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
          <td class="border-hairline" style="padding:10px 8px;border-bottom:1px solid #f1f5f9;vertical-align:top;">
            <div class="text-ink" style="font-size:13px;font-weight:600;color:#0f172a;">{title}</div>
            <div class="text-muted" style="font-size:12px;color:#64748b;">{company} • {location} • {salary}</div>
          </td>
          <td align="right" class="border-hairline" style="padding:10px 8px;border-bottom:1px solid #f1f5f9;vertical-align:top;white-space:nowrap;">
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
    <div class="card border-hairline" style="background:#ffffff;border-radius:12px;padding:24px;margin-bottom:12px;
                border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <!-- Header -->
      <div style="margin-bottom:14px;">
        <h3 class="text-ink" style="margin:0 0 4px;color:#0f172a;font-size:18px;font-weight:700;">{title}</h3>
        <p class="text-body" style="margin:0;color:#475569;font-size:14px;">{company}</p>
      </div>

      <!-- CTA -->
      {cta_html}

      <!-- Details Grid -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:14px 0;">
        <tr>
          <td class="detail-td bg-surface-soft" width="50%" valign="top" style="padding:10px 12px;background:#f8fafc;border-radius:8px;">
            <span class="text-muted" style="display:block;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;font-weight:600;">Location</span>
            <span class="text-ink" style="font-size:14px;color:#0f172a;font-weight:600;">{location}</span>
          </td>
          <td class="detail-spacer" width="8"></td>
          <td class="detail-td bg-surface-soft" width="50%" valign="top" style="padding:10px 12px;background:#f8fafc;border-radius:8px;">
            <span class="text-muted" style="display:block;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;font-weight:600;">Salary</span>
            <span class="text-ink" style="font-size:14px;color:#0f172a;font-weight:600;">{salary}</span>
          </td>
        </tr>
      </table>

      <!-- Match Reason -->
      <div class="accent-green-bg accent-green-border" style="background:#ecfdf5;border-radius:8px;padding:10px 14px;margin-bottom:2px;border-left:3px solid #10b981;">
        <span class="accent-green-text" style="font-size:13px;color:#065f46;">✅ {reason}</span>
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
            <div class="card border-hairline" style="background:#ffffff;border-radius:8px;padding:16px;margin-bottom:8px;border:1px solid #e2e8f0;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
                <td valign="top">
                  <h4 class="text-ink" style="margin:0 0 4px;color:#0f172a;font-size:15px;">{title}</h4>
                  <p class="text-body" style="margin:0 0 8px;color:#475569;font-size:13px;">{company} • {location} • {salary}</p>
                </td>
                <td valign="top" align="right" style="white-space:nowrap;padding-left:8px;">{apply_html}</td>
              </tr></table>
              <div class="accent-green-bg" style="background:#ecfdf5;border-radius:6px;padding:8px 12px;">
                <span class="accent-green-text" style="font-size:12px;color:#065f46;">✅ {reason}</span>
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
    <div class="card-highlight" style="background:#fefce8;border-radius:12px;padding:20px;margin-bottom:16px;
                border:1px solid #fde047;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <!-- Group Header -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
        <tr>
          <td valign="middle" style="white-space:nowrap;">
            <span style="background:#b45309;color:#fff;font-size:11px;font-weight:700;padding:4px 10px;
                   border-radius:20px;text-transform:uppercase;letter-spacing:0.3px;">{count} Matches · 1 Message</span>
          </td>
          <td valign="middle" class="text-muted" style="padding-left:10px;font-size:12px;color:#64748b;">📢 {source} &nbsp;·&nbsp; 🕐 {time_str}</td>
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


def _group_jobs_by_channel(job_groups: list[list[dict]]) -> list[tuple[str, list[list[dict]]]]:
    """Bucket message-groups by source channel, busiest channel first.

    Within a channel, message-groups keep the chronological-ascending order
    they already arrive in from `_group_jobs_by_message` — no secondary sort.
    """
    buckets: dict[str, list[list[dict]]] = {}
    for group in job_groups:
        source = group[0].get("source", "Unknown Source")
        buckets.setdefault(source, []).append(group)

    def sort_key(item: tuple[str, list[list[dict]]]) -> tuple[int, str]:
        source, groups = item
        return (-sum(len(g) for g in groups), source.lower())

    return sorted(buckets.items(), key=sort_key)


def _build_channel_section_header(source: str, match_count: int, is_first: bool = False) -> str:
    """Section divider introducing a channel's block of matches."""
    label = _escape(source)
    plural = "" if match_count == 1 else "es"
    top_margin = "12px" if is_first else "28px"
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:{top_margin} 0 14px;">
      <tr>
        <td class="border-hairline" style="border-bottom:2px solid #e2e8f0;padding-bottom:9px;">
          <table role="presentation" cellpadding="0" cellspacing="0"><tr>
            <td valign="middle" style="font-size:14px;padding-right:8px;">📢</td>
            <td valign="middle">
              <span class="text-ink" style="font-size:16px;font-weight:800;color:#0f172a;">{label}</span>
            </td>
            <td valign="middle" style="padding-left:10px;">
              <span class="badge-purple-bg badge-purple-text" style="background:#f5f3ff;color:#7c3aed;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;white-space:nowrap;">{match_count} match{plural}</span>
            </td>
          </tr></table>
        </td>
      </tr>
    </table>"""


def render_report_email(jobs: list[dict], from_date: str, stats: dict) -> str:
    """Render the full historical scan report HTML email."""
    job_groups = _group_jobs_by_message(jobs)

    total_matches = len(jobs)
    total_messages_with_matches = len(job_groups)
    batches_used = stats.get("total_batches", 0)
    tokens_used = stats.get("total_tokens", 0)

    if job_groups:
        channel_sections = _group_jobs_by_channel(job_groups)
        channel_count = len(channel_sections)
        summary_html = f"""
    <div style="margin:0 0 4px;padding:0 2px;">
      <p class="text-muted" style="margin:0;color:#64748b;font-size:13px;font-weight:600;">
        {total_matches} match{'es' if total_matches != 1 else ''} across {channel_count} channel{'s' if channel_count != 1 else ''} · {total_messages_with_matches} message{'s' if total_messages_with_matches != 1 else ''}
      </p>
    </div>"""
        cards_html = ""
        group_counter = 0
        for idx, (source, groups) in enumerate(channel_sections):
            channel_total = sum(len(g) for g in groups)
            cards_html += _build_channel_section_header(source, channel_total, is_first=(idx == 0))
            for group in groups:
                group_counter += 1
                cards_html += _build_message_group(group, group_counter)
    else:
        summary_html = ""
        cards_html = _build_empty_state(stats)

    header_html = _email_header(
        "📊 SCAN REPORT",
        "Job Scan Report",
        f"Scanned since <strong>{_escape(from_date)}</strong>",
        "solid-indigo",
    )

    return _minify(f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">{_HEAD_STYLE}</head>
<body class="email-bg" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;padding:0;margin:0;">
  <div class="container" style="max-width:700px;margin:0 auto;padding:24px;">

    {header_html}

    <!-- KPI Stats Row -->
    <div style="margin-bottom:20px;">
      <table role="presentation" class="kpi-table" width="100%" style="border-collapse:separate;border-spacing:8px;" cellpadding="0" cellspacing="0">
        <tr>
          <td class="kpi-cell accent-green-bg accent-green-border" style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;padding:18px;text-align:center;width:40%;">
            <div class="kpi-value kpi-hero-value accent-green-text" style="font-size:30px;font-weight:800;color:#065f46;">{total_matches}</div>
            <div class="kpi-label accent-green-text" style="font-size:12px;color:#059669;font-weight:700;text-transform:uppercase;letter-spacing:0.4px;margin-top:4px;">✅ Jobs Found</div>
          </td>
          <td class="kpi-cell card" style="background:#fff;border-radius:10px;padding:16px;text-align:center;width:30%;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <div class="kpi-value accent-blue-text" style="font-size:20px;font-weight:800;color:#2563eb;">{stats.get('total_scanned', 0)}</div>
            <div class="kpi-label text-muted" style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.4px;margin-top:4px;">🔍 Scanned</div>
          </td>
          <td class="kpi-cell card" style="background:#fff;border-radius:10px;padding:16px;text-align:center;width:30%;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <div class="kpi-value accent-amber-text" style="font-size:20px;font-weight:800;color:#f59e0b;">{stats.get('job_posts', 0)}</div>
            <div class="kpi-label text-muted" style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.4px;margin-top:4px;">📝 Job Posts</div>
          </td>
        </tr>
      </table>
    </div>

    <!-- Summary Caption -->
    {summary_html}

    <!-- Job Cards (grouped by channel) -->
    {cards_html}

    <!-- Footer -->
    <div class="border-hairline" style="text-align:center;padding:24px 0 8px;border-top:1px solid #e2e8f0;margin-top:24px;">
      <p class="text-muted" style="margin:0;color:#64748b;font-size:12px;">
        Generated by Job Scraper Bot • {datetime.now().strftime("%Y-%m-%d %H:%M")}
      </p>
      <p class="text-muted" style="margin:6px 0 0;color:#94a3b8;font-size:10px;">
        Analyzed via {batches_used} LLM batch{'es' if batches_used != 1 else ''} · {tokens_used:,} tokens
      </p>
    </div>

  </div>
</body>
</html>""")


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

    return _minify(f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">{_HEAD_STYLE}</head>
<body class="email-bg" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;padding:0;margin:0;">
  <div class="container" style="max-width:700px;margin:0 auto;padding:24px;">

    {header_html}

    <!-- Job Cards -->
    {cards_html}

    <!-- Footer -->
    <div class="border-hairline" style="text-align:center;padding:20px 0 8px;border-top:1px solid #e2e8f0;margin-top:20px;">
      <p class="text-muted" style="margin:0;color:#64748b;font-size:12px;">
        Real-time Telegram Job Scanner • {datetime.now().strftime("%Y-%m-%d %H:%M")}
      </p>
    </div>

  </div>
</body>
</html>""")


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

    return _minify(f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">{_HEAD_STYLE}</head>
<body class="email-bg" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;padding:0;margin:0;">
  <div class="container" style="max-width:700px;margin:0 auto;padding:24px;">

    {header_html}

    {card}

    <!-- Footer -->
    <div style="text-align:center;padding:16px 0 8px;">
      <p class="text-muted" style="margin:0;color:#64748b;font-size:12px;">
        Real-time Telegram Job Scanner • {datetime.now().strftime("%Y-%m-%d %H:%M")}
      </p>
    </div>

  </div>
</body>
</html>""")


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
