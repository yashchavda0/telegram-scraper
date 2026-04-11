"""
Job Scraper — Telethon Edition
Logs in as YOUR Telegram account, monitors specific groups/channels,
uses Azure OpenAI GPT-4o to match Data/AI/ML jobs, then notifies via WhatsApp + Email.
"""

import os
import re
import logging
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from openai import AzureOpenAI
from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat
from twilio.rest import Client as TwilioClient
from dotenv import load_dotenv

load_dotenv()

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
API_ID            = int(os.environ["TELEGRAM_API_ID"])
API_HASH          = os.environ["TELEGRAM_API_HASH"]
SESSION_NAME      = "job_scraper"            # saves login session locally

# Azure OpenAI
AZURE_OPENAI_KEY      = os.environ["AZURE_OPENAI_KEY"]
AZURE_OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]   # e.g. https://your-resource.openai.azure.com/
AZURE_DEPLOYMENT_NAME = os.environ["AZURE_DEPLOYMENT_NAME"]   # e.g. gpt-4o
AZURE_API_VERSION     = os.environ.get("AZURE_API_VERSION", "2024-02-01")

# TWILIO_SID        = os.environ["TWILIO_ACCOUNT_SID"]
# TWILIO_AUTH       = os.environ["TWILIO_AUTH_TOKEN"]
# TWILIO_WA_FROM    = os.environ["TWILIO_WHATSAPP_FROM"]
# YOUR_WA_NUMBER    = os.environ["YOUR_WHATSAPP_NUMBER"]

SMTP_HOST         = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT         = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER         = os.environ["SMTP_USER"]
SMTP_PASSWORD     = os.environ["SMTP_PASSWORD"]
YOUR_EMAIL        = os.environ["YOUR_EMAIL"]

# ─── Groups / Channels to Monitor ────────────────────────────────────────────
# Add usernames (without @) or invite links or numeric IDs
# Examples:
#   "python_jobs"          → public channel @python_jobs
#   "https://t.me/aijobs"  → public link
#   -1001234567890         → private group numeric ID (get via list_groups.py)
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
    "gocareers"
    # add as many as you want
]

# ─── Your Profile ────────────────────────────────────────────────────────────
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
    t = text.lower()
    return any(kw in t for kw in JOB_KEYWORDS)

# ─── Azure OpenAI GPT-4o Matching ────────────────────────────────────────────
azure_client = AzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version=AZURE_API_VERSION,
)

def analyze_job(text: str, source: str) -> dict | None:
    """Returns a dict with job details if it's a match, else None."""
    prompt = f"""
You are a job-matching assistant. Analyze this Telegram message.

CANDIDATE PROFILE:
{MY_PROFILE}

SOURCE GROUP: {source}

MESSAGE:
\"\"\"
{text[:3000]}
\"\"\"

Tasks:
1. Is this message a job posting? (yes/no)
2. If yes, does it match the candidate's Data/AI/ML profile? (yes/no)
3. Extract: job title, company name, location, salary (if mentioned), application link or contact.
4. One-sentence match reason.

Reply ONLY in this exact format:
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
        log.info("GPT-4o:\n%s", raw)

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
            "time":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    except Exception as e:
        log.error("GPT-4o error: %s", e)
        return None

# ─── Notifications ────────────────────────────────────────────────────────────
# def send_whatsapp(job: dict):
#     try:
#         twilio = TwilioClient(TWILIO_SID, TWILIO_AUTH)
#         body = (
#             f"🎯 *Job Match!*\n\n"
#             f"💼 *{job['title']}* at *{job['company']}*\n"
#             f"📍 {job['location']}\n"
#             f"💰 {job['salary']}\n"
#             f"🔗 {job['link']}\n\n"
#             f"✅ _{job['reason']}_\n\n"
#             f"📢 Source: {job['source']}\n"
#             f"🕐 {job['time']}"
#         )
#         twilio.messages.create(body=body, from_=TWILIO_WA_FROM, to=YOUR_WA_NUMBER)
#         log.info("✅ WhatsApp sent")
#     except Exception as e:
#         log.error("WhatsApp error: %s", e)


def send_email(job: dict):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🎯 Job Match: {job['title']} at {job['company']}"
        msg["From"]    = SMTP_USER
        msg["To"]      = YOUR_EMAIL

        snippet = job["original"][:2000] + ("..." if len(job["original"]) > 2000 else "")

        html = f"""
<html><body style="font-family:'Segoe UI',Arial,sans-serif;max-width:620px;margin:auto;background:#f4f7fb;padding:20px;">
  <div style="background:#fff;border-radius:12px;padding:28px;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <h2 style="color:#1d4ed8;margin-top:0;">🎯 Job Match Found</h2>
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
      <tr style="background:#eff6ff;"><td style="padding:10px 14px;font-weight:600;color:#374151;width:130px;">Role</td>
          <td style="padding:10px 14px;color:#1e40af;font-weight:700;">{job['title']}</td></tr>
      <tr><td style="padding:10px 14px;font-weight:600;color:#374151;">Company</td>
          <td style="padding:10px 14px;">{job['company']}</td></tr>
      <tr style="background:#eff6ff;"><td style="padding:10px 14px;font-weight:600;color:#374151;">Location</td>
          <td style="padding:10px 14px;">{job['location']}</td></tr>
      <tr><td style="padding:10px 14px;font-weight:600;color:#374151;">Salary</td>
          <td style="padding:10px 14px;">{job['salary']}</td></tr>
      <tr style="background:#eff6ff;"><td style="padding:10px 14px;font-weight:600;color:#374151;">Apply / Contact</td>
          <td style="padding:10px 14px;"><a href="{job['link']}" style="color:#2563eb;">{job['link']}</a></td></tr>
      <tr><td style="padding:10px 14px;font-weight:600;color:#374151;">Why it matches</td>
          <td style="padding:10px 14px;color:#059669;">{job['reason']}</td></tr>
      <tr style="background:#eff6ff;"><td style="padding:10px 14px;font-weight:600;color:#374151;">Source</td>
          <td style="padding:10px 14px;">{job['source']}</td></tr>
      <tr><td style="padding:10px 14px;font-weight:600;color:#374151;">Time</td>
          <td style="padding:10px 14px;color:#6b7280;">{job['time']}</td></tr>
    </table>
    <h3 style="color:#374151;">📋 Original Post</h3>
    <pre style="background:#f9fafb;padding:14px;border-radius:8px;border-left:4px solid #3b82f6;
         white-space:pre-wrap;font-size:13px;color:#374151;">{snippet}</pre>
  </div>
</body></html>
"""
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.sendmail(SMTP_USER, YOUR_EMAIL, msg.as_string())
        log.info("✅ Email sent")
    except Exception as e:
        log.error("Email error: %s", e)

# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()        # prompts phone + OTP on first run, then saves session

    log.info("✅ Logged in as: %s", (await client.get_me()).username)

    # Resolve group entities once
    watch_entities = []
    for g in WATCH_GROUPS:
        try:
            entity = await client.get_entity(g)
            name = getattr(entity, "title", str(g))
            watch_entities.append(entity)
            log.info("📡 Watching: %s", name)
        except Exception as e:
            log.warning("Could not resolve group '%s': %s", g, e)

    if not watch_entities:
        log.error("No valid groups found. Check WATCH_GROUPS in config.")
        return

    @client.on(events.NewMessage(chats=watch_entities))
    async def handler(event):
        text = event.message.message
        if not text or not looks_like_job(text):
            return

        chat = await event.get_chat()
        source = getattr(chat, "title", str(chat.id))
        log.info("📩 Possible job in '%s' — analyzing...", source)

        job = analyze_job(text, source)
        if job:
            log.info("🎯 Match: %s @ %s", job["title"], job["company"])
            # send_whatsapp(job)
            send_email(job)
        else:
            log.info("❌ Not a match.")

    log.info("👀 Listening for new messages in %d group(s)...", len(watch_entities))
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())