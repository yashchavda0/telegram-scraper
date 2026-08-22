"""
Job Scraper — Real-time Telethon Edition (Batch Mode)
─────────────────────────────────────────────────────
Logs in as YOUR Telegram account, monitors specific groups/channels,
uses Azure OpenAI GPT-4.1 in BATCHES to match Data/AI/ML jobs,
then notifies via Email (instant or digest mode).

Batch buffer flushes when:
  - Buffer reaches LLM_BATCH_SIZE messages, OR
  - 60 seconds since first buffered message (whichever comes first)
"""

import os
import logging
import asyncio
from datetime import datetime

from telethon import TelegramClient, events
from dotenv import load_dotenv

from llm import BatchAnalyzer, LLM_BATCH_SIZE
from email_templates import send_instant_match_email, send_digest_email

load_dotenv()

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
API_ID       = int(os.environ["TELEGRAM_API_ID"])
API_HASH     = os.environ["TELEGRAM_API_HASH"]
SESSION_NAME = "job_scraper"

# Email mode: "instant" (per-match) or "digest" (batched every N minutes)
EMAIL_MODE = os.environ.get("EMAIL_MODE", "instant").lower()
EMAIL_DIGEST_INTERVAL_MINUTES = int(os.environ.get("EMAIL_DIGEST_INTERVAL_MINUTES", "30"))

# Buffer flush timeout in seconds (flush buffered messages after this even if batch isn't full)
BUFFER_FLUSH_TIMEOUT = 60

# ─── Groups / Channels to Monitor ────────────────────────────────────────────
WATCH_GROUPS = [
    "tcs_nqt_2026",
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
    "jobsandinternshipdaily",
]

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


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start()

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

    # ─── Batch Buffer State ───────────────────────────────────────────
    analyzer = BatchAnalyzer()
    batch_buffer: list[dict] = []
    buffer_lock = asyncio.Lock()
    flush_timer_task: asyncio.Task | None = None

    # Digest mode: accumulate matches and send periodically
    digest_buffer: list[dict] = []
    digest_lock = asyncio.Lock()

    async def flush_batch():
        """Process the current batch buffer through LLM."""
        nonlocal batch_buffer, flush_timer_task

        async with buffer_lock:
            if not batch_buffer:
                return
            current_batch = batch_buffer[:]
            batch_buffer = []
            flush_timer_task = None

        log.info("📦 Flushing batch of %d messages for analysis...", len(current_batch))

        # Run LLM analysis in thread pool (it's synchronous)
        loop = asyncio.get_event_loop()
        matches = await loop.run_in_executor(
            None, analyzer.analyze_batch, current_batch, "realtime"
        )

        if not matches:
            log.info("❌ No matches in this batch.")
            return

        log.info("🎯 %d match(es) found in batch!", len(matches))

        if EMAIL_MODE == "digest":
            async with digest_lock:
                digest_buffer.extend(matches)
                log.info("  → Added to digest buffer (%d total pending)", len(digest_buffer))
        else:
            # Instant mode: send email for each match immediately
            for job in matches:
                log.info("  🎯 Match: %s @ %s", job["title"], job["company"])
                send_instant_match_email(job)

    async def schedule_flush():
        """Wait BUFFER_FLUSH_TIMEOUT then flush."""
        await asyncio.sleep(BUFFER_FLUSH_TIMEOUT)
        await flush_batch()

    async def send_digest():
        """Periodically send digest email if there are accumulated matches."""
        nonlocal digest_buffer
        while True:
            await asyncio.sleep(EMAIL_DIGEST_INTERVAL_MINUTES * 60)
            async with digest_lock:
                if not digest_buffer:
                    continue
                jobs_to_send = digest_buffer[:]
                digest_buffer = []

            period = f"Last {EMAIL_DIGEST_INTERVAL_MINUTES} min"
            log.info("📧 Sending digest email with %d match(es)...", len(jobs_to_send))
            send_digest_email(jobs_to_send, period)

    # ─── Message Handler ──────────────────────────────────────────────
    @client.on(events.NewMessage(chats=watch_entities))
    async def handler(event):
        nonlocal flush_timer_task

        text = event.message.message
        if not text or not looks_like_job(text):
            return

        chat = await event.get_chat()
        source = getattr(chat, "title", str(chat.id))
        username = getattr(chat, "username", None) or str(chat.id)
        msg_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        log.info("📩 Possible job in '%s' — buffering...", source)

        async with buffer_lock:
            batch_buffer.append({
                "text": text,
                "source": source,
                "msg_time": msg_time,
                "msg_id": event.message.id,
                "group_username": username,
            })

            # Flush immediately if batch is full
            if len(batch_buffer) >= LLM_BATCH_SIZE:
                asyncio.create_task(flush_batch())
                return

            # Start timer for time-based flush (if not already running)
            if flush_timer_task is None or flush_timer_task.done():
                flush_timer_task = asyncio.create_task(schedule_flush())

    # Start digest sender if in digest mode
    if EMAIL_MODE == "digest":
        asyncio.create_task(send_digest())
        log.info("📧 Digest mode active — emails every %d minutes", EMAIL_DIGEST_INTERVAL_MINUTES)
    else:
        log.info("📧 Instant mode — emails sent per match (after batch analysis)")

    log.info(
        "👀 Listening for new messages in %d group(s) (batch size: %d, flush timeout: %ds)...",
        len(watch_entities), LLM_BATCH_SIZE, BUFFER_FLUSH_TIMEOUT,
    )
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
