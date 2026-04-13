# 🚀 EC2 Telegram Scraper – Complete Setup & Operations Guide

This README contains everything you need to:

* Launch & connect to EC2
* Deploy your scraper
* Manage cron jobs
* Monitor logs
* Setup alerts (Telegram + Healthchecks)
* Safely update / stop your system

---

# 🟢 1. CREATE NEW EC2 INSTANCE

### Step 1: Launch Instance

* Go to AWS Console → EC2 → Launch Instance
* Name: `telegram-scraper`
* AMI: Ubuntu 22.04
* Instance type: `t2.micro`
* Key pair: Create `.pem` file
* Security Group:

  * Allow SSH (port 22) from your IP

---

# 🔑 2. CONNECT TO EC2

```bash
chmod 400 your-key.pem
ssh -i your-key.pem ubuntu@YOUR_PUBLIC_IP
```

---

# ⚙️ 3. SETUP SERVER

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git curl -y
```

---

# 📦 4. UPLOAD YOUR PROJECT

## Option A (Recommended)

```bash
git clone YOUR_REPO_URL
cd telegram-scraper
```

## Option B (Local Upload)

```bash
scp -i your-key.pem -r ./telegram-scraper ubuntu@IP:/home/ubuntu/
```

---

# 🐍 5. SETUP PYTHON ENVIRONMENT

```bash
cd /home/ubuntu/scraper/telegram-scraper

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

---

# 🔐 6. TELEGRAM CONFIG (IMPORTANT)

You need:

### API Credentials

* API_ID
* API_HASH

### Session File

* Generated automatically after first login

---

## 🔵 Get Telegram Bot Token

1. Open Telegram
2. Search: `@BotFather`
3. Run:

```
/start
/newbot
```

👉 Save:

```
BOT_TOKEN
```

---

## 🔵 Get Chat ID

1. Send message to your bot
2. Open in browser:

```
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```

Find:

```
result → message → chat → id
```

👉 That is your `CHAT_ID`

---

# 🧪 7. TEST SCRAPER

```bash
python historical_scraper.py
```

---

# 🛑 8. STOP CURRENT SCRIPT

If running manually:

```bash
Ctrl + C
```

If running in background:

```bash
ps aux | grep python
kill -9 <PID>
```

---

# 🔁 9. CREATE CRON JOB (WITH RANDOM TIME)

## Step 1: Create Script

```bash
nano /home/ubuntu/run_scraper.sh
```

Paste:

```bash
#!/bin/bash

LOG_FILE="/home/ubuntu/scraper.log"

BOT_TOKEN="YOUR_BOT_TOKEN"
CHAT_ID="YOUR_CHAT_ID"
HEALTHCHECK_URL="https://hc-ping.com/YOUR_ID"

send_msg () {
  curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
  -d chat_id="$CHAT_ID" \
  -d text="$1"
}

# Start ping
curl -fsS $HEALTHCHECK_URL/start > /dev/null 2>&1

DELAY=$(shuf -i 0-3599 -n 1)

echo "[$(date)] Sleeping for $DELAY sec" >> $LOG_FILE
sleep $DELAY

echo "[$(date)] Running scraper..." >> $LOG_FILE

/home/ubuntu/scraper/telegram-scraper/venv/bin/python \
/home/ubuntu/scraper/telegram-scraper/historical_scraper.py \
>> $LOG_FILE 2>&1

STATUS=$?

if [ $STATUS -eq 0 ]; then
  send_msg "✅ Scraper SUCCESS at $(date)"
  curl -fsS $HEALTHCHECK_URL > /dev/null 2>&1
else
  send_msg "❌ Scraper FAILED at $(date)"
  curl -fsS $HEALTHCHECK_URL/fail > /dev/null 2>&1
fi

echo "[$(date)] Finished with status $STATUS" >> $LOG_FILE
```

---

## Step 2: Make Executable

```bash
chmod +x /home/ubuntu/run_scraper.sh
```

---

## Step 3: Add Cron

```bash
crontab -e
```

Add:

```bash
0 23 * * * /home/ubuntu/run_scraper.sh
```

---

# ⏱️ 10. MODIFY / STOP CRON JOB

## View cron

```bash
crontab -l
```

## Edit cron

```bash
crontab -e
```

## Remove cron

Delete the line and save

---

# 🧪 11. TEST CRON

Temporary test:

```bash
* * * * * /home/ubuntu/run_scraper.sh
```

Then check logs.

⚠️ Revert back after testing

---

# 📊 12. CHECK LOGS

```bash
tail -f /home/ubuntu/scraper.log
```

---

# 📡 13. HEALTH MONITORING (Healthchecks)

Setup:

* Name: tele-scraper
* Period: 1 day
* Grace Time: 2 hours

---

# 🔁 14. UPDATE YOUR CODE

```bash
cd telegram-scraper
git pull
```

OR re-upload via SCP

---

# 🔄 15. RESTART FLOW AFTER UPDATE

```bash
source venv/bin/activate
python historical_scraper.py
```

---

# 🛑 16. STOP INSTANCE (SAVE COST)

From AWS Console:

* EC2 → Instance → Stop

---

# 🚀 17. START INSTANCE AGAIN

* EC2 → Start Instance
* Connect again using SSH

---

# ⚠️ IMPORTANT BEST PRACTICES

* Always use virtual environment
* Never expose API keys in code
* Use full paths in cron
* Backup `.session` file
* Monitor logs regularly

---

# 🧠 FINAL SYSTEM ARCHITECTURE

```
EC2 Instance
   ↓
Cron (11 PM)
   ↓
Random Delay
   ↓
Scraper Runs
   ↓
 ├── Logs → file
 ├── Telegram Alerts
 └── Healthchecks Dashboard
```

---

# 🎯 YOU NOW HAVE

✅ Automated scraping
✅ Random execution timing
✅ Telegram alerts
✅ Health monitoring
✅ Log tracking
✅ Easy update system

---
# 🚀 EC2 Telegram Scraper – Complete Setup & Operations Guide (Extended)

This version includes:

* Logs (including last N logs)
* Instance type change (scale up/down EC2)
* Full operational control

---

# 📊 12. LOG MANAGEMENT (VERY IMPORTANT)

## 🔵 View Live Logs

```bash
tail -f /home/ubuntu/scraper.log
```

---

## 🔵 View Last N Lines

### Last 50 lines:

```bash
tail -n 50 /home/ubuntu/scraper.log
```

### Last 100 lines:

```bash
tail -n 100 /home/ubuntu/scraper.log
```

---

## 🔵 View Logs with Scroll (Best UX)

```bash
less /home/ubuntu/scraper.log
```

Controls:

* `↑ ↓` → scroll
* `q` → quit

---

## 🔵 Search Inside Logs

```bash
grep "ERROR" /home/ubuntu/scraper.log
```

```bash
grep "SUCCESS" /home/ubuntu/scraper.log
```

---

## 🔵 Real-time Filtering

```bash
tail -f /home/ubuntu/scraper.log | grep "FAILED"
```

---

## 🔵 Clear Logs (if too large)

```bash
> /home/ubuntu/scraper.log
```

---

# 🛠️ 13. CHANGE EC2 INSTANCE TYPE (SCALE UP/DOWN)

This is how you upgrade from `t2.micro` → `t3.medium` or similar.

---

## ⚠️ IMPORTANT

👉 You MUST stop instance before changing type

---

## 🟢 Step 1: Stop Instance

AWS Console:

* EC2 → Instances
* Select instance
* Click **Stop**

---

## 🟢 Step 2: Change Instance Type

* Select instance
* Actions → Instance Settings → Change Instance Type
* Choose:

  * `t3.micro` (cheap)
  * `t3.small`
  * `t3.medium` (recommended for scraping)

---

## 🟢 Step 3: Start Instance

* Click **Start**

---

## 🟢 Step 4: Reconnect

```bash
ssh -i your-key.pem ubuntu@YOUR_IP
```

---

# ⚡ Alternative (CLI Way)

```bash
aws ec2 stop-instances --instance-ids i-xxxx

aws ec2 modify-instance-attribute \
  --instance-id i-xxxx \
  --instance-type "{\"Value\": \"t3.medium\"}"

aws ec2 start-instances --instance-ids i-xxxx
```

---

# 🧠 WHEN SHOULD YOU SCALE?

| Symptom           | Action           |
| ----------------- | ---------------- |
| Script slow       | Upgrade CPU      |
| Memory error      | Increase RAM     |
| Multiple channels | Scale up         |
| Heavy AI usage    | Use GPU instance |

---

# 🧪 CHECK SYSTEM USAGE

```bash
htop
```

If not installed:

```bash
sudo apt install htop
```

---

# 🔄 RESTART SERVICES AFTER REBOOT

Cron usually auto-starts, but verify:

```bash
systemctl status cron
```

If stopped:

```bash
sudo systemctl start cron
```

---

# 🧩 BONUS: RUN SCRIPT AS BACKGROUND SERVICE (OPTIONAL)

Instead of cron, you can use:

## 🔵 Using `nohup`

```bash
nohup /home/ubuntu/run_scraper.sh &
```

---

## 🔵 Kill Background Job

```bash
ps aux | grep run_scraper
kill -9 <PID>
```

---

# 🧠 FULL CONTROL CHECKLIST

## ✅ Check running processes

```bash
ps aux | grep python
```

---

## ✅ Check cron jobs

```bash
crontab -l
```

---

## ✅ Check logs

```bash
tail -n 100 /home/ubuntu/scraper.log
```

---

## ✅ Restart scraper manually

```bash
/home/ubuntu/run_scraper.sh
```

---

## ✅ Stop everything

```bash
pkill -f historical_scraper.py
```

---

# 🧠 FINAL SYSTEM (COMPLETE CONTROL)

```text
EC2 Instance
   ↓
Cron Scheduler
   ↓
Random Delay Script
   ↓
Python Scraper
   ↓
 ├── Logs → /home/ubuntu/scraper.log
 ├── Telegram Alerts
 └── Healthchecks Monitoring
```

---

# 🚀 YOU ARE NOW PRODUCTION READY

You can now:

✅ Scale instance
✅ Debug using logs
✅ Monitor failures
✅ Control cron jobs
✅ Run/stop system anytime
✅ Maintain uptime visibility

---

# 🔥 NEXT LEVEL (If You Want)

* Dockerize scraper
* Auto deploy via GitHub Actions
* Add queue system (Redis)
* Multi-instance scaling
* Central logging (CloudWatch)

---
