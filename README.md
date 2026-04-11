# 🔍 Job Scraper (Telethon) — Setup Guide

Logs into **your own Telegram account**, monitors groups/channels you choose,
and sends matching Data/AI/ML jobs to your **WhatsApp + Email** via Claude AI.

---

## 📁 Files

```
scraper/
├── scraper.py        ← Main listener (runs continuously)
├── list_groups.py    ← Helper: shows all your groups with IDs
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🔑 Step 1 — Get Telegram API Credentials

> This is different from BotFather. You need developer credentials for your account.

1. Go to **[my.telegram.org](https://my.telegram.org)** — log in with your phone number
2. Click **API Development Tools**
3. Create a new app (any name/description is fine)
4. Copy your **API ID** (number) and **API Hash** (long string)

---

## ⚙️ Step 2 — Configure

```bash
cp .env.example .env
# Fill in all values in .env
```

---

## 📦 Step 3 — Install

```bash
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## 📋 Step 4 — Find Your Groups

Run this first to see all groups/channels you're a member of:

```bash
python list_groups.py
```

Output example:
```
=================================================================
ID                   TYPE         TITLE
=================================================================
@DataScienceJobs     Channel      Data Science Jobs
@AIMLHiring          Channel      AI/ML Hiring
-1001234567890       Chat         Private Job Group
=================================================================
```

Copy the usernames or IDs into `WATCH_GROUPS` in `scraper.py`:

```python
WATCH_GROUPS = [
    "DataScienceJobs",      # public channel (no @)
    "AIMLHiring",
    -1001234567890,         # private group by numeric ID
    "https://t.me/somechannel",   # or full link
]
```

---

## 🚀 Step 5 — Run

```bash
python scraper.py
```

**First run:** Telegram will ask for your phone number and an OTP code.
After that, a `job_scraper.session` file saves your login — no OTP needed again.

---

## 🧠 How It Works

```
New message in watched group
         │
         ▼
  Keyword pre-filter
  (hiring/job/vacancy...)
         │ passes
         ▼
  Claude AI Analysis
  ├─ Is this a real job post?
  ├─ Does it match Data/AI/ML?
  ├─ Extract: title, company,
  │   location, salary, link
  └─ Generate match reason
         │ match!
         ▼
  ┌──────────────┐  ┌─────────────┐
  │  WhatsApp    │  │   Email     │
  │  (Twilio)    │  │  (Gmail)    │
  └──────────────┘  └─────────────┘
```

---

## 🌐 Public Channels (No Membership Needed)

You can also add public channels directly — even ones you haven't joined:

```python
WATCH_GROUPS = [
    "https://t.me/python_jobs",
    "remotejobs",
    "mlengineerjobs",
]
```

Telethon will join/peek them automatically using your account.

---

## 🔄 Run 24/7

```bash
# Keep alive with screen (Linux/Mac)
screen -S scraper
source venv/bin/activate && python scraper.py
# Ctrl+A then D to detach

# Reattach later
screen -r scraper
```

---

## ⚠️ Notes

- **Your account** is used — not a bot. Telegram sees this as normal app usage.
- Don't monitor hundreds of groups simultaneously — keep it reasonable (10–20 max).
- The `.session` file contains your login — keep it private, don't share it.
- Twilio sandbox requires your phone to join once (send a message to their number).
