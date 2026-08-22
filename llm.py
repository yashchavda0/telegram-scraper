"""
llm.py — Batch LLM Analyzer
────────────────────────────
Handles batched Azure OpenAI calls with:
- Strict JSON validation via Pydantic
- Retry mechanism (3 attempts) with exponential backoff
- Graceful fallback to 1-by-1 processing
- JSONL batch tracking log
"""

import os
import json
import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from openai import AzureOpenAI
from pydantic import BaseModel, field_validator
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
AZURE_OPENAI_KEY      = os.environ["AZURE_OPENAI_KEY"]
AZURE_OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
AZURE_DEPLOYMENT_NAME = os.environ["AZURE_DEPLOYMENT_NAME"]
AZURE_API_VERSION     = os.environ.get("AZURE_API_VERSION", "2024-02-01")

LLM_BATCH_SIZE    = int(os.environ.get("LLM_BATCH_SIZE", "25"))
LLM_MAX_RETRIES   = int(os.environ.get("LLM_MAX_RETRIES", "3"))
BATCH_LOG_FILE    = os.environ.get("BATCH_LOG_FILE", "batch_log.jsonl")

MY_PROFILE = """
I am a Data / AI / ML / Software Engineer / Junior Software Developer / SDE / AI Architect professional seeking new opportunities.
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


# ─── Pydantic Models ──────────────────────────────────────────────────────────
class JobResult(BaseModel):
    title: str
    company: str
    location: str
    salary: str
    link: str
    reason: str


class MessageAnalysis(BaseModel):
    message_index: int
    is_job: bool
    is_match: bool
    jobs: list[JobResult] = []

    @field_validator("jobs", mode="before")
    @classmethod
    def empty_jobs_if_no_match(cls, v, info):
        """Allow empty jobs list when is_match is False."""
        if v is None:
            return []
        return v


class BatchResponse(BaseModel):
    results: list[MessageAnalysis]


# ─── Batch Analyzer ──────────────────────────────────────────────────────────
class BatchAnalyzer:
    """Sends batches of messages to Azure OpenAI and returns validated results."""

    def __init__(self):
        self.client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_version=AZURE_API_VERSION,
        )
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_batches = 0

    def analyze_batch(
        self,
        messages: list[dict],
        scraper_name: str = "historical",
    ) -> list[dict]:
        """
        Analyze a batch of messages. Each message dict must have:
          - text: str (the message content)
          - source: str (group/channel name)
          - msg_time: str (timestamp)
          - msg_id: int (optional, for deep links)
          - group_username: str (optional, for deep links)

        Returns a list of matched job dicts (can be multiple per message).
        """
        if not messages:
            return []

        batch_id = str(uuid.uuid4())
        prompt = self._build_batch_prompt(messages)
        raw_response = None
        attempts = 0
        token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        # ─── Retry loop ───────────────────────────────────────────────
        for attempt in range(1, LLM_MAX_RETRIES + 1):
            attempts = attempt
            try:
                raw_response, usage = self._call_llm(prompt, attempt)
                token_usage = {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                }
                self.total_prompt_tokens += usage.prompt_tokens
                self.total_completion_tokens += usage.completion_tokens

                # Validate JSON
                parsed = self._validate_response(raw_response, len(messages))
                self.total_batches += 1

                # Log success
                self._log_batch(batch_id, scraper_name, messages, parsed, token_usage, attempts, True)

                # Extract matched jobs
                return self._extract_matches(parsed, messages)

            except (json.JSONDecodeError, ValueError) as e:
                log.warning(
                    "Batch %s attempt %d/%d: validation failed — %s",
                    batch_id[:8], attempt, LLM_MAX_RETRIES, e,
                )
                if attempt < LLM_MAX_RETRIES:
                    # Append corrective instruction for retry
                    prompt = self._build_batch_prompt(messages, retry_hint=True)
                    time.sleep(2 ** attempt)  # exponential backoff: 2s, 4s
                continue

            except Exception as e:
                log.warning(
                    "Batch %s attempt %d/%d: API error — %s",
                    batch_id[:8], attempt, LLM_MAX_RETRIES, e,
                )
                if attempt < LLM_MAX_RETRIES:
                    time.sleep(2 ** attempt)
                continue

        # ─── All retries failed → fallback to 1-by-1 ─────────────────
        log.warning("Batch %s: all retries failed. Falling back to 1-by-1 processing.", batch_id[:8])
        self._log_batch(batch_id, scraper_name, messages, None, token_usage, attempts, False)
        return self._fallback_one_by_one(messages, scraper_name)

    def _build_batch_prompt(self, messages: list[dict], retry_hint: bool = False) -> str:
        """Build the batch analysis prompt with all messages numbered."""
        msg_blocks = []
        for i, msg in enumerate(messages):
            msg_blocks.append(
                f"--- MESSAGE {i} ---\n"
                f"Source: {msg['source']}\n"
                f"Time: {msg['msg_time']}\n"
                f"Text:\n{msg['text'][:2500]}\n"
            )

        messages_text = "\n".join(msg_blocks)

        hint = ""
        if retry_hint:
            hint = (
                "\n\nIMPORTANT: Your previous response was NOT valid JSON. "
                "You MUST respond with ONLY a valid JSON object. No markdown, no explanation, no code fences."
            )

        return f"""You are a job-matching assistant. Analyze the following {len(messages)} Telegram messages in batch.

CANDIDATE PROFILE:
{MY_PROFILE}

MESSAGES TO ANALYZE:
{messages_text}

INSTRUCTIONS:
1. For each message, determine if it contains job posting(s).
2. If yes, check if any job matches the candidate's Data/AI/ML/Software Engineer profile.
3. A single message may contain MULTIPLE job listings — extract each matching job separately.
4. Extract: job title, company, location, salary, application link/contact, and one-sentence match reason.

RESPOND WITH ONLY A VALID JSON OBJECT (no markdown fences, no extra text):
{{
  "results": [
    {{
      "message_index": 0,
      "is_job": true,
      "is_match": true,
      "jobs": [
        {{
          "title": "Data Scientist",
          "company": "TechCorp",
          "location": "Remote",
          "salary": "15-20 LPA",
          "link": "https://apply.example.com",
          "reason": "Matches ML and Python skills with 2+ years experience requirement"
        }}
      ]
    }},
    {{
      "message_index": 1,
      "is_job": false,
      "is_match": false,
      "jobs": []
    }}
  ]
}}

Rules:
- "results" array MUST have exactly {len(messages)} items, one per message, in order.
- message_index must match the message number (0-indexed).
- If is_job=false or is_match=false, set jobs to an empty array [].
- If a message has multiple matching jobs, include all in the jobs array.
- Use "Unknown" for missing company/location, "Not mentioned" for salary, "Not found" for link.{hint}"""

    def _call_llm(self, prompt: str, attempt: int) -> tuple:
        """Make the Azure OpenAI API call. Returns (raw_content, usage)."""
        # Scale max_tokens on retry (in case previous response was cut off)
        max_tokens = 4000 + (attempt - 1) * 1000

        res = self.client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME,
            max_tokens=max_tokens,
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a precise job-matching assistant. "
                        "You MUST respond with ONLY valid JSON. "
                        "No markdown code fences, no explanatory text, no comments. "
                        "Just the raw JSON object."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw = res.choices[0].message.content.strip()
        # Strip markdown fences if model wraps them despite instructions
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3].strip()

        return raw, res.usage

    def _validate_response(self, raw: str, expected_count: int) -> list[MessageAnalysis]:
        """Parse and validate the JSON response via Pydantic."""
        parsed = json.loads(raw)

        # Handle both {"results": [...]} and bare [...] formats
        if isinstance(parsed, list):
            parsed = {"results": parsed}

        batch_resp = BatchResponse.model_validate(parsed)

        if len(batch_resp.results) != expected_count:
            raise ValueError(
                f"Expected {expected_count} results, got {len(batch_resp.results)}"
            )

        return batch_resp.results

    def _extract_matches(
        self, results: list[MessageAnalysis], messages: list[dict]
    ) -> list[dict]:
        """Convert validated results into the job dict format used by the pipeline."""
        matched_jobs = []
        for analysis in results:
            if not analysis.is_job or not analysis.is_match:
                continue
            if analysis.message_index >= len(messages):
                continue

            msg = messages[analysis.message_index]
            for job in analysis.jobs:
                matched_jobs.append({
                    "title": job.title or "Unknown Role",
                    "company": job.company or "Unknown",
                    "location": job.location or "Unknown",
                    "salary": job.salary or "Not mentioned",
                    "link": job.link or "Not found",
                    "reason": job.reason or "",
                    "source": msg["source"],
                    "original": msg["text"],
                    "time": msg["msg_time"],
                    "msg_id": msg.get("msg_id"),
                    "group_username": msg.get("group_username"),
                    # Track multi-job grouping
                    "jobs_in_message": len(analysis.jobs),
                    "message_index": analysis.message_index,
                })
        return matched_jobs

    def _fallback_one_by_one(self, messages: list[dict], scraper_name: str) -> list[dict]:
        """Process messages individually as fallback when batch fails."""
        all_matches = []
        for i, msg in enumerate(messages):
            try:
                single_batch = [msg]
                prompt = self._build_batch_prompt(single_batch)
                raw, usage = self._call_llm(prompt, 1)
                self.total_prompt_tokens += usage.prompt_tokens
                self.total_completion_tokens += usage.completion_tokens

                parsed = self._validate_response(raw, 1)
                matches = self._extract_matches(parsed, single_batch)
                all_matches.extend(matches)
            except Exception as e:
                log.error("Fallback failed for message %d: %s", i, e)
                continue
            time.sleep(1.5)  # rate limit buffer for fallback
        return all_matches

    def _log_batch(
        self,
        batch_id: str,
        scraper_name: str,
        messages: list[dict],
        results: Optional[list[MessageAnalysis]],
        token_usage: dict,
        attempts: int,
        success: bool,
    ):
        """Append batch record to JSONL tracking log."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "batch_id": batch_id,
            "scraper": scraper_name,
            "message_count": len(messages),
            "messages_sent": [
                {
                    "index": i,
                    "source": m["source"],
                    "msg_time": m["msg_time"],
                    "text_preview": m["text"][:100],
                }
                for i, m in enumerate(messages)
            ],
            "results_summary": (
                [
                    {
                        "message_index": r.message_index,
                        "is_job": r.is_job,
                        "is_match": r.is_match,
                        "matched_jobs_count": len(r.jobs),
                    }
                    for r in results
                ]
                if results
                else None
            ),
            "token_usage": token_usage,
            "attempts": attempts,
            "success": success,
        }
        try:
            with open(BATCH_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.error("Failed to write batch log: %s", e)

    def get_stats(self) -> dict:
        """Return accumulated token/batch stats for this session."""
        return {
            "total_batches": self.total_batches,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
        }
