"""
historical_scraper.py
─────────────────────
Scrapes PAST messages from your chosen Telegram groups/channels.
Finds Data/AI/ML job matches using Azure OpenAI GPT-4o.
Sends all matches in one summary Email + individual WhatsApp alerts.

Usage:
  python historical_scraper.py              → scrape today's messages
  python historical_scraper.py --days 3     → scrape last 3 days
  python historical_scraper.py --date 2024-12-01  → scrape from a specific date
"""

import os
import re
import logging
import asyncio
import smtplib
import argparse
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

from openai import AzureOpenAI
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
API_ID            = int(os.environ["TELEGRAM_API_ID"])
API_HASH          = os.environ["TELEGRAM_API_HASH"]
SESSION_NAME      = "job_scraper"   # reuses same session as scraper.py

AZURE_OPENAI_KEY      = os.environ["AZURE_OPENAI_KEY"]
AZURE_OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
AZURE_DEPLOYMENT_NAME = os.environ["AZURE_DEPLOYMENT_NAME"]
AZURE_API_VERSION     = os.environ.get("AZURE_API_VERSION", "2024-02-01")

# TWILIO_SID     = os.environ["TWILIO_ACCOUNT_SID"]
# TWILIO_AUTH    = os.environ["TWILIO_AUTH_TOKEN"]
# TWILIO_WA_FROM = os.environ["TWILIO_WHATSAPP_FROM"]
# YOUR_WA_NUMBER = os.environ["YOUR_WHATSAPP_NUMBER"]

SMTP_HOST      = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT      = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER      = os.environ["SMTP_USER"]
SMTP_PASSWORD  = os.environ["SMTP_PASSWORD"]
YOUR_EMAIL     = os.environ["YOUR_EMAIL"]
RECIPIENT_EMAILS = [e.strip() for e in YOUR_EMAIL.split(",") if e.strip()]

# ─── Groups to Scrape ─────────────────────────────────────────────────────────
WATCH_GROUPS = [
    "tcs_nqt_2026",        # replace with real group usernames
    "bnydiscussion2020",
    "tcshyderabadregion",
    "talentdin",
    "onlinelearning2025",
    "Fresherjobsadda",
    "seekerasjobs",
    "uber_solutions",
    "foundthejob",
    "TechUprise_Updates",
    "gocareers",
    "fresher_jobs2",
    "campusdriveupdates",
    "fresher_tech_job",
    "jobsandinternshipdaily"
    # add as many as you want
]

# ─── Rate limiting: pause between GPT-4o calls to avoid throttling ────────────
GPT_DELAY_SECONDS = 1.5

# ─── Your Profile ─────────────────────────────────────────────────────────────
MY_PROFILE = """
I am a Data / AI / ML professional seeking new opportunities.
Core skills:
- Machine Learning & Deep Learning (PyTorch, TensorFlow, scikit-learn)
- Data Science & Analytics (Python, Pandas, NumPy, SQL)
- AI/LLM applications (LangChain, RAG, fine-tuning, prompt engineering)
- Data Engineering (Spark, Airflow, dbt, ETL pipelines)
- MLOps (Docker, Kubernetes, MLflow, CI/CD for ML)
- Cloud (AWS SageMaker, GCP Vertex AI, Azure ML)
- Visualization (Power BI, Tableau, Matplotlib)
Open to: Remote, Hybrid, On-site | Worldwide
"""

# ─── Keyword pre-filter ───────────────────────────────────────────────────────
JOB_KEYWORDS = [
    "hiring", "job", "vacancy", "position", "role", "opportunity",
    "apply", "career", "recruitment", "opening", "we are looking",
    "join us", "join our", "work with us", "urgent", "required",
    "experience required", "salary", "ctc", "lpa", "remote",
]

def looks_like_job(text: str) -> bool:
    return any(kw in text.lower() for kw in JOB_KEYWORDS)

# ─── Azure OpenAI ─────────────────────────────────────────────────────────────
azure_client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version=AZURE_API_VERSION,
)

def analyze_job(text: str, source: str, msg_time: str) -> dict | None:
    prompt = f"""
You are a job-matching assistant. Analyze this Telegram message.

CANDIDATE PROFILE:
{MY_PROFILE}

SOURCE GROUP: {source}
MESSAGE TIME: {msg_time}

MESSAGE:
\"\"\"
{text[:3000]}
\"\"\"

Tasks:
1. Is this message a job posting? (yes/no)
2. If yes, does it match the candidate's Data/AI/ML profile? (yes/no)
3. Extract: job title, company name, location, salary (if mentioned), application link or contact.
4. One-sentence match reason.

Reply ONLY in this exact format (no extra text):
IS_JOB: yes|no
IS_MATCH: yes|no
TITLE: <title>
COMPANY: <company or Unknown>
LOCATION: <location or Remote/Unknown>
SALARY: <salary or Not mentioned>
LINK: <url or contact or Not found>
REASON: <one sentence>
"""
    try:
        res = azure_client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME,
            max_tokens=400,
            messages=[
                {"role": "system", "content": "You are a precise job-matching assistant. Follow the exact output format requested."},
                {"role": "user", "content": prompt},
            ],
        )
        raw = res.choices[0].message.content.strip()

        def get(key):
            m = re.search(rf"^{key}:\s*(.+)$", raw, re.MULTILINE | re.IGNORECASE)
            return m.group(1).strip() if m else ""

        if get("IS_JOB").lower() != "yes" or get("IS_MATCH").lower() != "yes":
            return None

        return {
            "title":    get("TITLE") or "Unknown Role",
            "company":  get("COMPANY") or "Unknown",
            "location": get("LOCATION") or "Unknown",
            "salary":   get("SALARY") or "Not mentioned",
            "link":     get("LINK") or "Not found",
            "reason":   get("REASON"),
            "source":   source,
            "original": text,
            "time":     msg_time,
        }
    except Exception as e:
        log.error("GPT-4o error: %s", e)
        return None

# ─── Notifications ─────────────────────────────────────────────────────────────
def send_whatsapp_summary(jobs: list, from_date: str):
    """Send a compact summary of all matches via WhatsApp."""
    try:
        twilio = TwilioClient(TWILIO_SID, TWILIO_AUTH)
        lines = [f"🎯 *Job Scan Complete* — {len(jobs)} match(es) since {from_date}\n"]
        for i, job in enumerate(jobs, 1):
            lines.append(
                f"*{i}. {job['title']}* @ {job['company']}\n"
                f"   📍 {job['location']} | 💰 {job['salary']}\n"
                f"   🔗 {job['link']}\n"
                f"   📢 {job['source']} | 🕐 {job['time']}\n"
            )
        body = "\n".join(lines)[:1500]   # WhatsApp limit
        twilio.messages.create(body=body, from_=TWILIO_WA_FROM, to=YOUR_WA_NUMBER)
        log.info("✅ WhatsApp summary sent (%d jobs)", len(jobs))
    except Exception as e:
        log.error("WhatsApp error: %s", e)


def send_email_report(jobs: list, from_date: str, stats: dict):
    """Send a full HTML report of all matched jobs via Email."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"📊 Job Scan Report — {len(jobs)} matches since {from_date}"
        msg["From"]    = SMTP_USER
        msg["To"]      = ", ".join(RECIPIENT_EMAILS)

        # Build job cards
        cards = ""
        for i, job in enumerate(jobs, 1):
            snippet = job["original"][:600] + ("..." if len(job["original"]) > 600 else "")
            cards += f"""
            <div style="background:#fff;border-radius:10px;padding:20px;margin-bottom:16px;
                        border-left:5px solid #2563eb;box-shadow:0 1px 6px rgba(0,0,0,0.07);">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <h3 style="margin:0;color:#1e40af;">#{i} {job['title']}</h3>
                <span style="font-size:12px;color:#6b7280;">{job['time']}</span>
              </div>
              <p style="margin:6px 0 12px;color:#374151;">
                🏢 {job['company']} &nbsp;|&nbsp; 📍 {job['location']} &nbsp;|&nbsp; 💰 {job['salary']}
              </p>
              <p style="margin:0 0 8px;color:#059669;font-style:italic;">✅ {job['reason']}</p>
              <p style="margin:0 0 10px;">
                🔗 <a href="{job['link']}" style="color:#2563eb;">{job['link']}</a>
              </p>
              <p style="margin:0 0 8px;font-size:12px;color:#9ca3af;">📢 Source: {job['source']}</p>
              <details>
                <summary style="cursor:pointer;color:#6b7280;font-size:13px;">View original post</summary>
                <pre style="background:#f9fafb;padding:12px;border-radius:6px;font-size:12px;
                            white-space:pre-wrap;color:#374151;margin-top:8px;">{snippet}</pre>
              </details>
            </div>"""

        html = f"""
<html><body style="font-family:'Segoe UI',Arial,sans-serif;background:#f1f5f9;padding:24px;margin:0;">
  <div style="max-width:680px;margin:auto;">

    <div style="background:linear-gradient(135deg,#1d4ed8,#0ea5e9);border-radius:12px;
                padding:28px;margin-bottom:20px;color:#fff;">
      <h1 style="margin:0 0 8px;">📊 Job Scan Report</h1>
      <p style="margin:0;opacity:0.85;">Messages scanned since: <strong>{from_date}</strong></p>
    </div>

    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px;">
      <div style="background:#fff;border-radius:8px;padding:16px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
        <div style="font-size:28px;font-weight:700;color:#2563eb;">{stats['total_scanned']}</div>
        <div style="font-size:13px;color:#6b7280;">Messages Scanned</div>
      </div>
      <div style="background:#fff;border-radius:8px;padding:16px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
        <div style="font-size:28px;font-weight:700;color:#f59e0b;">{stats['job_posts']}</div>
        <div style="font-size:13px;color:#6b7280;">Job Posts Found</div>
      </div>
      <div style="background:#fff;border-radius:8px;padding:16px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,0.06);">
        <div style="font-size:28px;font-weight:700;color:#059669;">{len(jobs)}</div>
        <div style="font-size:13px;color:#6b7280;">Matches for You</div>
      </div>
    </div>

    <h2 style="color:#1e293b;margin:0 0 12px;">🎯 Matched Jobs</h2>
    {cards if cards else '<p style="color:#6b7280;">No matches found for this period.</p>'}

    <p style="text-align:center;color:#94a3b8;font-size:12px;margin-top:24px;">
      Generated by Job Scraper Bot • {datetime.now().strftime("%Y-%m-%d %H:%M")}
    </p>
  </div>
</body></html>
"""
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.sendmail(SMTP_USER, RECIPIENT_EMAILS, msg.as_string())
        log.info("✅ Email report sent to %d recipient(s)", len(RECIPIENT_EMAILS))
    except Exception as e:
        log.error("Email error: %s", e)


def save_results(jobs: list, from_date: str):
    """Save matched jobs to a JSON file for records."""
    filename = f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump({"from_date": from_date, "matches": jobs}, f, indent=2, ensure_ascii=False)
    log.info("💾 Results saved to %s", filename)
    return filename

# ─── Core Scraper ─────────────────────────────────────────────────────────────
async def scrape_history(since: datetime):
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    await client.connect()

    if not await client.is_user_authorized():
        raise Exception("❌ Session not authorized. Run script manually once to login.")

    me = await client.get_me()
    log.info("✅ Logged in as: %s", me.username or me.phone)

    since_utc = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since
    from_label = since_utc.strftime("%Y-%m-%d %H:%M UTC")

    all_jobs    = []
    total_msgs  = 0
    total_job_posts = 0

    for group in WATCH_GROUPS:
        try:
            entity = await client.get_entity(group)
            name   = getattr(entity, "title", str(group))
            log.info("📡 Scraping: %s (since %s)", name, from_label)
        except Exception as e:
            log.warning("Could not resolve '%s': %s", group, e)
            continue

        group_count = 0
        async for message in client.iter_messages(entity, reverse=True, offset_date=since_utc):
            # Stop once we go past our date window (iter_messages with offset_date can overshoot)
            if message.date < since_utc:
                continue

            text = message.message
            if not text or not text.strip():
                continue

            total_msgs += 1
            group_count += 1

            if group_count % 50 == 0:
                log.info("  ...processed %d messages in %s", group_count, name)

            if not looks_like_job(text):
                continue

            total_job_posts += 1
            msg_time = message.date.strftime("%Y-%m-%d %H:%M")
            log.info("  🔍 Analyzing job post from %s in %s...", msg_time, name)

            await asyncio.sleep(GPT_DELAY_SECONDS)   # avoid rate limits
            job = analyze_job(text, name, msg_time)
            if job:
                log.info("  🎯 Match: %s @ %s", job["title"], job["company"])
                all_jobs.append(job)
            else:
                log.info("  ❌ Not a match")

        log.info("  ✅ Done with %s — %d messages scanned", name, group_count)

    await client.disconnect()

    stats = {
        "total_scanned": total_msgs,
        "job_posts":     total_job_posts,
        "matches":       len(all_jobs),
    }

    log.info("\n" + "="*50)
    log.info("📊 SCAN COMPLETE")
    log.info("   Messages scanned : %d", total_msgs)
    log.info("   Job posts found  : %d", total_job_posts)
    log.info("   Matches for you  : %d", len(all_jobs))
    log.info("="*50)

    if all_jobs:
        send_whatsapp_summary(all_jobs, from_label)
        send_email_report(all_jobs, from_label, stats)
        save_results(all_jobs, from_label)
    else:
        log.info("No matching jobs found for this period.")
        # Still send a summary email so you know the scan ran
        send_email_report([], from_label, stats)

    return all_jobs

# ─── CLI Entry Point ───────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="Scrape historical Telegram job posts")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--days", type=int, default=None,
        help="Scrape messages from the last N days (e.g. --days 3)"
    )
    group.add_argument(
        "--date", type=str, default=None,
        help="Scrape messages from a specific date onward (YYYY-MM-DD, e.g. --date 2024-12-01)"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.date:
        try:
            since = datetime.strptime(args.date, "%Y-%m-%d")
            log.info("📅 Scraping from date: %s", args.date)
        except ValueError:
            log.error("Invalid date format. Use YYYY-MM-DD (e.g. 2024-12-01)")
            return
    elif args.days:
        since = datetime.utcnow() - timedelta(days=args.days)
        log.info("📅 Scraping last %d day(s)", args.days)
    else:
        # Default: today from midnight UTC
        now = datetime.now(timezone.utc)
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        log.info("📅 Scraping today's messages (since midnight UTC)")

    asyncio.run(scrape_history(since))


if __name__ == "__main__":
    main()