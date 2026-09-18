"""
linkedin_poller.py

Checks LinkedIn job postings via a third-party Apify scraper
(curious_coder/linkedin-jobs-scraper) and feeds any new matches into the
same email + dashboard pipeline as job_poller.py (shared seen_jobs.json
and docs/jobs_log.json).

READ THIS BEFORE ENABLING:

- This is NOT an official LinkedIn API. It scrapes LinkedIn's public job
  search results page, which is against LinkedIn's Terms of Service. It
  does not use your LinkedIn login or cookies, so there's no direct risk
  to your personal LinkedIn account — but you should know the mechanism
  isn't sanctioned by LinkedIn before you turn it on.
- It costs real money on your Apify account (~$0.002 per job result).
  It's disabled by default. Turn it on by setting
  config.json -> "linkedin" -> "enabled": true and adding an APIFY_TOKEN
  secret (free at console.apify.com/settings/integrations).
- This runs on its OWN schedule (.github/workflows/linkedin_poll.yml),
  separate and much less frequent than the free poller, specifically to
  stay inside Apify's $5/month free platform credit. Don't lower that
  schedule's interval without checking your Apify usage dashboard first
  — going more often than every ~4 hours will likely exceed the free tier.
"""

import os
from datetime import datetime, timezone

import requests

from job_poller import (
    load_json,
    save_json,
    matches_keywords,
    send_email,
    CONFIG_PATH,
    SEEN_PATH,
    LOG_PATH,
    MAX_LOG_ENTRIES,
)

APIFY_ACTOR = "curious_coder~linkedin-jobs-scraper"
APIFY_API_BASE = "https://api.apify.com/v2"


def fetch_linkedin(token, li_config):
    if not token:
        print("WARNING: APIFY_TOKEN not set — skipping LinkedIn check")
        return []

    payload = {
        "keywords": li_config.get("keywords", ""),
        "location": li_config.get("location", "United States"),
        "datePosted": li_config.get("datePosted", "past24Hours"),
        "limitPerSource": li_config.get("limitPerSource", 15),
        "scrapeCompany": False,
        "autoConvertToAiSearch": True,
    }
    params = {
        "token": token,
        # Hard cost ceiling for this one run, regardless of config mistakes.
        "maxTotalChargeUsd": li_config.get("maxChargeUsd", 0.10),
        "timeout": 120,
    }
    url = f"{APIFY_API_BASE}/actors/{APIFY_ACTOR}/run-sync-get-dataset-items"

    r = requests.post(url, params=params, json=payload, timeout=150)
    if r.status_code != 200:
        print(f"WARNING: LinkedIn actor call returned {r.status_code}: {r.text[:300]}")
        return []

    jobs = []
    for j in r.json():
        job_id = j.get("id") or j.get("trackingId") or j.get("link")
        jobs.append({
            "id": f"linkedin:{job_id}",
            "title": j.get("title", ""),
            "company": j.get("companyName", ""),
            "location": j.get("location", ""),
            "url": j.get("link", ""),
            "source": "LinkedIn",
        })
    return jobs


def main():
    config = load_json(CONFIG_PATH, {})
    li_config = config.get("linkedin", {})
    if not li_config.get("enabled"):
        print("LinkedIn check is disabled in config.json — skipping")
        return

    keywords = config.get("keywords", [])
    exclude_keywords = config.get("exclude_keywords", [])

    seen = load_json(SEEN_PATH, {})
    log = load_json(LOG_PATH, [])
    now = datetime.now(timezone.utc).isoformat()

    try:
        raw_jobs = fetch_linkedin(os.environ.get("APIFY_TOKEN"), li_config)
    except Exception as e:
        print(f"WARNING: LinkedIn fetch failed: {e}")
        raw_jobs = []

    new_jobs = []
    for j in raw_jobs:
        if not matches_keywords(j.get("title"), keywords, exclude_keywords):
            continue
        if j["id"] in seen:
            continue
        seen[j["id"]] = now
        j["found_at"] = now
        new_jobs.append(j)

    print(f"LinkedIn: checked {len(raw_jobs)} postings, {len(new_jobs)} new match(es)")

    save_json(SEEN_PATH, seen)

    if new_jobs:
        log = new_jobs + log
        log = log[:MAX_LOG_ENTRIES]
        save_json(LOG_PATH, log)
        try:
            send_email(
                new_jobs,
                os.environ.get("SMTP_SERVER"),
                os.environ.get("SMTP_PORT"),
                os.environ.get("SMTP_USER"),
                os.environ.get("SMTP_PASS"),
                os.environ.get("NOTIFY_EMAIL"),
            )
        except Exception as e:
            print(f"WARNING: email send failed: {e}")


if __name__ == "__main__":
    main()
