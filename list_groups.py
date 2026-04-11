"""
list_groups.py
Run this FIRST to see all groups/channels you're a member of.
Copy the usernames or IDs into WATCH_GROUPS in scraper.py
"""

import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

API_ID   = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]

async def main():
    client = TelegramClient("job_scraper", API_ID, API_HASH)
    await client.start()

    print("\n" + "="*65)
    print(f"{'ID':<20} {'TYPE':<12} {'TITLE'}")
    print("="*65)

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        kind = type(entity).__name__
        title = dialog.name or "—"

        # show username if public
        username = getattr(entity, "username", None)
        display = f"@{username}" if username else str(entity.id)

        if kind in ("Channel", "Chat", "ChatForbidden", "ChannelForbidden"):
            print(f"{display:<20} {kind:<12} {title}")

    print("="*65)
    print("\nCopy the @username or numeric ID into WATCH_GROUPS in scraper.py\n")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
