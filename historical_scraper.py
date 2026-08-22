"""
historical_scraper.py
─────────────────────
Scrapes PAST messages from your chosen Telegram groups/channels.
Finds Data/AI/ML job matches using Azure OpenAI in BATCHES.
Sends all matches in one summary Email with multi-job grouping.

Usage:
  python historical_scraper.py              → scrape today's messages
  python historical_scraper.py --days 3     → scrape last 3 days
  python historical_scraper.py --date 2024-12-01  → scrape from a specific date
"""

import os
import logging
import asyncio
import argparse
import json
from datetime import datetime, timezone, timedelta

from telethon import TelegramClient
from dotenv import load_dotenv

from llm import BatchAnalyzer, LLM_BATCH_SIZE
from email_templates import send_report_email

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
API_ID       = int(os.environ["TELEGRAM_API_ID"])
API_HASH     = os.environ["TELEGRAM_API_HASH"]
SESSION_NAME = "job_scraper"

# ─── Groups to Scrape ─────────────────────────────────────────────────────────
WATCH_GROUPS = [
    "tcs_nqt_2026",
    "freshers_it_jobs",
    "talentdin",
    "bnydiscussion2020",
    "seekerasjobs",
    "foundthejob",
    "onlinelearning2025",
    "way2freshers",
    "OffCampus_Campus_Jobs_Internship",
    "TechUprise_Updates",
    "Fresherjobsadda",
    "jobs_and_internships_updates",
    "tcshyderabadregion",
    "Internshipupdatesfreveryone",
    "uber_solutions",
    "goyalarsh",
    "gocareers",
    "jobsandinternshipsupdates",
    "PLACEMENTLELO",
    "off_campus_jobs_and_internships",
    "jobsandinternshipdaily",
    "fresher_tech_job",
    "campusdriveupdates",
    "fresher_jobs2",
]

# ─── Keyword pre-filter ───────────────────────────────────────────────────────
JOB_KEYWORDS = [
    "hiring", "job", "vacancy", "position", "role", "opportunity",
    "apply", "career", "recruitment", "opening", "we are looking",
    "join us", "join our", "work with us", "urgent", "required",
    "experience required", "salary", "ctc", "lpa", "remote",
]


def looks_like_job(text: str) -> bool:
    return any(kw in text.lower() for kw in JOB_KEYWORDS)


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

    analyzer = BatchAnalyzer()
    all_jobs = []
    total_msgs = 0
    total_job_posts = 0

    for group in WATCH_GROUPS:
        try:
            entity = await client.get_entity(group)
            name = getattr(entity, "title", str(group))
            username = getattr(entity, "username", None) or group
            log.info("📡 Scraping: %s (since %s)", name, from_label)
        except Exception as e:
            log.warning("Could not resolve '%s': %s", group, e)
            continue

        # ─── Collect messages and batch-analyze ───────────────────────
        group_count = 0
        batch_buffer = []

        async for message in client.iter_messages(entity, reverse=True, offset_date=since_utc):
            if message.date < since_utc:
                continue

            text = message.message
            if not text or not text.strip():
                continue

            total_msgs += 1
            group_count += 1

            if group_count % 100 == 0:
                log.info("  ...processed %d messages in %s", group_count, name)

            if not looks_like_job(text):
                continue

            total_job_posts += 1
            msg_time = message.date.strftime("%Y-%m-%d %H:%M")

            batch_buffer.append({
                "text": text,
                "source": name,
                "msg_time": msg_time,
                "msg_id": message.id,
                "group_username": username,
            })

            # ─── Flush batch when full ────────────────────────────────
            if len(batch_buffer) >= LLM_BATCH_SIZE:
                log.info("  📦 Analyzing batch of %d messages from %s...", len(batch_buffer), name)
                matches = analyzer.analyze_batch(batch_buffer, scraper_name="historical")
                if matches:
                    for m in matches:
                        log.info("    🎯 Match: %s @ %s", m["title"], m["company"])
                    all_jobs.extend(matches)
                batch_buffer = []

        # ─── Flush remaining buffer for this group ────────────────────
        if batch_buffer:
            log.info("  📦 Analyzing final batch of %d messages from %s...", len(batch_buffer), name)
            matches = analyzer.analyze_batch(batch_buffer, scraper_name="historical")
            if matches:
                for m in matches:
                    log.info("    🎯 Match: %s @ %s", m["title"], m["company"])
                all_jobs.extend(matches)

        log.info("  ✅ Done with %s — %d messages scanned", name, group_count)

    await client.disconnect()

    # ─── Stats ────────────────────────────────────────────────────────
    llm_stats = analyzer.get_stats()
    stats = {
        "total_scanned": total_msgs,
        "job_posts": total_job_posts,
        "matches": len(all_jobs),
        "total_batches": llm_stats["total_batches"],
        "total_tokens": llm_stats["total_tokens"],
        "prompt_tokens": llm_stats["total_prompt_tokens"],
        "completion_tokens": llm_stats["total_completion_tokens"],
    }

    log.info("\n" + "=" * 60)
    log.info("📊 SCAN COMPLETE")
    log.info("   Messages scanned  : %d", total_msgs)
    log.info("   Job posts found   : %d", total_job_posts)
    log.info("   Matches for you   : %d", len(all_jobs))
    log.info("   LLM batches used  : %d", llm_stats["total_batches"])
    log.info("   Total tokens used : %d", llm_stats["total_tokens"])
    log.info("=" * 60)

    if all_jobs:
        send_report_email(all_jobs, from_label, stats)
        save_results(all_jobs, from_label)
    else:
        log.info("No matching jobs found for this period.")
        send_report_email([], from_label, stats)

    return all_jobs


# ─── CLI Entry Point ───────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="Scrape historical Telegram job posts")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--days", type=int, default=None,
        help="Scrape messages from the last N days (e.g. --days 3)",
    )
    group.add_argument(
        "--date", type=str, default=None,
        help="Scrape messages from a specific date onward (YYYY-MM-DD)",
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
        since = datetime.now(timezone.utc) - timedelta(days=args.days)
        log.info("📅 Scraping last %d day(s)", args.days)
    else:
        now = datetime.now(timezone.utc)
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        log.info("📅 Scraping today's messages (since midnight UTC)")

    asyncio.run(scrape_history(since))


if __name__ == "__main__":
    main()
