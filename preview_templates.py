"""
preview_templates.py — Render sample emails to static HTML for local preview.

Does not send any email (no SMTP). Run this after tweaking email_templates.py
to check the visual result in a browser: `python preview_templates.py`
"""

import glob
import json
import os

import email_templates as et

OUT_DIR = os.path.join(os.path.dirname(__file__), "previews")


def _load_sample_jobs():
    job_files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "jobs_*.json")))
    if not job_files:
        raise SystemExit("No jobs_*.json sample file found in the project root.")
    with open(job_files[-1], encoding="utf-8") as f:
        data = json.load(f)
    return data["matches"], data.get("from_date", "unknown")


def _make_large_group(base_job: dict, count: int = 7) -> list[dict]:
    jobs = []
    for i in range(count):
        job = dict(base_job)
        job["title"] = f"Role Variant {i + 1}"
        jobs.append(job)
    return jobs


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    jobs, from_date = _load_sample_jobs()

    stats = {
        "total_scanned": 120,
        "job_posts": 45,
        "total_batches": 5,
        "total_tokens": 38210,
    }

    previews = {
        "instant.html": et.render_instant_email(jobs[0]),
        "digest.html": et.render_digest_email(jobs, "last 2 hours"),
        "report.html": et.render_report_email(jobs, from_date, stats),
        "report_empty.html": et.render_report_email([], from_date, stats),
        "large_group.html": et.render_digest_email(_make_large_group(jobs[0]), "bulk test"),
    }

    for filename, html in previews.items():
        path = os.path.join(OUT_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
