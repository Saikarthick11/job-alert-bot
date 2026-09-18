"""
job_poller.py

Checks a wide set of job sources for new postings matching your keywords,
emails you the moment it finds any, and logs them for the dashboard
(docs/jobs_log.json, served by GitHub Pages).

Meant to be run every 5 minutes by .github/workflows/job_poll.yml. Not every
source is actually hit on every run — see "RATE TIERS" below.

RATE TIERS
----------
Free public APIs are not all equally free-to-hammer. Some publish hard caps,
some just deserve politeness. So sources are split into three tiers, gated
by the current UTC time INSIDE this one script (no extra workflow files
needed):

- FAST (every run, ~every 5 min): Greenhouse, Lever, Ashby, SmartRecruiters,
  Recruitee, Workable (per-company), Arbeitnow. These are single-company or
  simple community endpoints with no documented daily cap.
- MODERATE (only when minute % 15 == 0, i.e. 4x/hour, 96x/day): RemoteOK,
  Workable's cross-company search, The Muse, and Adzuna. Adzuna's free plan
  is hard-capped at 250 calls/day — 96/day leaves comfortable headroom, and
  Adzuna is now queried with ONE combined "OR" search instead of one call
  per keyword (the old per-keyword-loop version would have blown through
  250/day by mid-morning).
- SLOW (only at 00:00 / 06:00 / 12:00 / 18:00 UTC, i.e. 4x/day): Remotive.
  Remotive's API terms explicitly ask for no more than ~4 checks/day, so
  this hits that ceiling exactly and no harder.

If you add a new free source later, pick a tier based on whether it
publishes a rate limit (respect it) or is just a shared community endpoint
(default to MODERATE unless it's genuinely one-employer-at-a-time like
Greenhouse/Lever).
"""

import os
import json
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone

import requests

CONFIG_PATH = "config.json"
SEEN_PATH = "seen_jobs.json"
LOG_PATH = "docs/jobs_log.json"
MAX_LOG_ENTRIES = 1000
REQUEST_TIMEOUT = 20
USER_AGENT = "job-alert-bot/1.0 (personal use)"


# ---------- storage helpers ----------

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"WARNING: could not read {path}: {e}")
    return default


def save_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------- filtering ----------

def matches_keywords(title, keywords, exclude_keywords):
    t = (title or "").lower()
    if keywords and not any(k.lower() in t for k in keywords):
        return False
    if exclude_keywords and any(k.lower() in t for k in exclude_keywords):
        return False
    return True


def safe_fetch(name, fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        print(f"WARNING: {name} failed: {e}")
        return []


# ============================================================
# FAST TIER — single-employer ATS boards, hit every run
# ============================================================

def fetch_greenhouse(token):
    jobs = []
    r = requests.get(
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT},
    )
    if r.status_code != 200:
        print(f"WARNING: greenhouse '{token}' returned {r.status_code} — check the token")
        return jobs
    for j in r.json().get("jobs", []):
        jobs.append({
            "id": f"greenhouse:{token}:{j.get('id')}",
            "title": j.get("title", ""), "company": token,
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""), "source": "Greenhouse",
        })
    return jobs


def fetch_lever(token):
    jobs = []
    r = requests.get(
        f"https://api.lever.co/v0/postings/{token}?mode=json",
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT},
    )
    if r.status_code != 200:
        print(f"WARNING: lever '{token}' returned {r.status_code} — check the token")
        return jobs
    for j in r.json():
        jobs.append({
            "id": f"lever:{token}:{j.get('id')}",
            "title": j.get("text", ""), "company": token,
            "location": (j.get("categories") or {}).get("location", ""),
            "url": j.get("hostedUrl", ""), "source": "Lever",
        })
    return jobs


def fetch_ashby(token):
    jobs = []
    r = requests.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{token}",
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT},
    )
    if r.status_code != 200:
        print(f"WARNING: ashby '{token}' returned {r.status_code} — check the token")
        return jobs
    for j in r.json().get("jobs", []):
        jobs.append({
            "id": f"ashby:{token}:{j.get('id')}",
            "title": j.get("title", ""), "company": token,
            "location": j.get("location", ""),
            "url": j.get("jobUrl", ""), "source": "Ashby",
        })
    return jobs


def fetch_smartrecruiters(company_id):
    jobs = []
    r = requests.get(
        f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings",
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT},
    )
    if r.status_code != 200:
        print(f"WARNING: smartrecruiters '{company_id}' returned {r.status_code} — check the company id")
        return jobs
    for j in r.json().get("content", []):
        loc = j.get("location") or {}
        location = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
        jobs.append({
            "id": f"smartrecruiters:{company_id}:{j.get('id')}",
            "title": j.get("name", ""), "company": company_id,
            "location": location,
            "url": j.get("ref", "") or f"https://jobs.smartrecruiters.com/{company_id}/{j.get('id')}",
            "source": "SmartRecruiters",
        })
    return jobs


def fetch_recruitee(company_slug):
    jobs = []
    r = requests.get(
        f"https://{company_slug}.recruitee.com/api/offers/",
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT},
    )
    if r.status_code != 200:
        print(f"WARNING: recruitee '{company_slug}' returned {r.status_code} — check the slug")
        return jobs
    for j in r.json().get("offers", []):
        jobs.append({
            "id": f"recruitee:{company_slug}:{j.get('id')}",
            "title": j.get("title", ""), "company": company_slug,
            "location": j.get("location", ""),
            "url": j.get("careers_url", ""), "source": "Recruitee",
        })
    return jobs


def fetch_workable_company(slug):
    jobs = []
    r = requests.get(
        f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=false",
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT},
    )
    if r.status_code != 200:
        print(f"WARNING: workable '{slug}' returned {r.status_code} — check the slug")
        return jobs
    for j in r.json().get("jobs", []):
        jobs.append({
            "id": f"workable:{slug}:{j.get('shortcode') or j.get('id')}",
            "title": j.get("title", ""), "company": slug,
            "location": j.get("location", {}).get("location_str", "") if isinstance(j.get("location"), dict) else "",
            "url": j.get("url", ""), "source": "Workable",
        })
    return jobs


def fetch_arbeitnow():
    jobs = []
    r = requests.get(
        "https://www.arbeitnow.com/api/job-board-api",
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT},
    )
    if r.status_code != 200:
        print(f"WARNING: arbeitnow returned {r.status_code}")
        return jobs
    for j in r.json().get("data", []):
        jobs.append({
            "id": f"arbeitnow:{j.get('slug')}",
            "title": j.get("title", ""), "company": j.get("company_name", ""),
            "location": j.get("location", ""),
            "url": j.get("url", ""), "source": "Arbeitnow",
        })
    return jobs


# ============================================================
# MODERATE TIER — shared aggregators, checked 4x/hour
# ============================================================

def fetch_remoteok():
    jobs = []
    r = requests.get(
        "https://remoteok.com/api",
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT},
    )
    if r.status_code != 200:
        print(f"WARNING: remoteok returned {r.status_code}")
        return jobs
    for j in r.json():
        if "id" not in j:
            continue  # first item is a legal notice, not a job
        jobs.append({
            "id": f"remoteok:{j['id']}",
            "title": j.get("position", ""), "company": j.get("company", ""),
            "location": j.get("location") or "Remote",
            "url": j.get("url", ""), "source": "RemoteOK",
        })
    return jobs


def fetch_workable_search(query, location):
    jobs = []
    r = requests.get(
        "https://jobs.workable.com/api/v1/jobs",
        params={"query": query, "location": location},
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT},
    )
    if r.status_code != 200:
        print(f"WARNING: workable search returned {r.status_code}")
        return jobs
    for j in r.json().get("results", []):
        jobs.append({
            "id": f"workable-search:{j.get('id') or j.get('uuid')}",
            "title": j.get("title", ""), "company": j.get("companyName", ""),
            "location": (j.get("location") or {}).get("fullLocation", ""),
            "url": j.get("url", ""), "source": "Workable",
        })
    return jobs


def fetch_themuse(categories):
    jobs = []
    for category in categories:
        r = requests.get(
            "https://www.themuse.com/api/public/jobs",
            params={"category": category, "page": 0},
            timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT},
        )
        if r.status_code != 200:
            print(f"WARNING: themuse '{category}' returned {r.status_code}")
            continue
        for j in r.json().get("results", []):
            locations = ", ".join(loc.get("name", "") for loc in j.get("locations", []))
            jobs.append({
                "id": f"themuse:{j.get('id')}",
                "title": j.get("name", ""),
                "company": (j.get("company") or {}).get("name", ""),
                "location": locations,
                "url": j.get("refs", {}).get("landing_page", ""),
                "source": "The Muse",
            })
    return jobs


def fetch_adzuna(app_id, app_key, keywords, country="us"):
    """One combined OR-search instead of one call per keyword — Adzuna's
    free plan caps out at 250 calls/day, so this matters."""
    jobs = []
    if not app_id or not app_key:
        return jobs
    r = requests.get(
        f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
        params={
            "app_id": app_id, "app_key": app_key,
            "what_or": " ".join(keywords),
            "max_days_old": 1, "results_per_page": 50,
            "content-type": "application/json",
        },
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code != 200:
        print(f"WARNING: adzuna returned {r.status_code}")
        return jobs
    for j in r.json().get("results", []):
        jobs.append({
            "id": f"adzuna:{j.get('id')}",
            "title": j.get("title", ""),
            "company": (j.get("company") or {}).get("display_name", ""),
            "location": (j.get("location") or {}).get("display_name", ""),
            "url": j.get("redirect_url", ""), "source": "Adzuna",
        })
    return jobs


# ============================================================
# SLOW TIER — 4x/day, per the source's own stated terms
# ============================================================

def fetch_remotive(query):
    jobs = []
    r = requests.get(
        "https://remotive.com/api/remote-jobs",
        params={"search": query} if query else {},
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT},
    )
    if r.status_code != 200:
        print(f"WARNING: remotive returned {r.status_code}")
        return jobs
    for j in r.json().get("jobs", []):
        jobs.append({
            "id": f"remotive:{j.get('id')}",
            "title": j.get("title", ""), "company": j.get("company_name", ""),
            "location": j.get("candidate_required_location", "Remote"),
            # Remotive's terms require linking back to them as the source.
            "url": j.get("url", ""), "source": "Remotive",
        })
    return jobs


# ---------- notification ----------

def send_email(new_jobs, smtp_server, smtp_port, smtp_user, smtp_pass, to_addr):
    if not all([smtp_server, smtp_port, smtp_user, smtp_pass, to_addr]):
        print("WARNING: email secrets are not fully set — skipping send (see README)")
        return

    subject = f"{len(new_jobs)} new job posting{'s' if len(new_jobs) != 1 else ''} matched"
    rows = []
    for j in new_jobs:
        rows.append(
            f"<p><b>{j['title']}</b> — {j['company']} "
            f"({j['location'] or 'location n/a'})<br>"
            f"Source: {j['source']}<br>"
            f"<a href='{j['url']}'>{j['url']}</a></p>"
        )
    body_html = "<html><body>" + "".join(rows) + "</body></html>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_addr
    msg.attach(MIMEText(body_html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
        server.starttls(context=context)
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_addr, msg.as_string())
    print(f"Sent email with {len(new_jobs)} new job(s)")


# ---------- main ----------

def main():
    config = load_json(CONFIG_PATH, {})
    keywords = config.get("keywords", [])
    exclude_keywords = config.get("exclude_keywords", [])

    seen = load_json(SEEN_PATH, {})
    log = load_json(LOG_PATH, [])

    now_utc = datetime.now(timezone.utc)
    run_moderate = now_utc.minute % 15 == 0
    run_slow = now_utc.hour % 6 == 0 and now_utc.minute == 0

    all_jobs = []

    # --- FAST tier: every run ---
    for token in config.get("greenhouse_companies", []):
        all_jobs += safe_fetch(f"greenhouse:{token}", fetch_greenhouse, token)
    for token in config.get("lever_companies", []):
        all_jobs += safe_fetch(f"lever:{token}", fetch_lever, token)
    for token in config.get("ashby_companies", []):
        all_jobs += safe_fetch(f"ashby:{token}", fetch_ashby, token)
    for cid in config.get("smartrecruiters_companies", []):
        all_jobs += safe_fetch(f"smartrecruiters:{cid}", fetch_smartrecruiters, cid)
    for slug in config.get("recruitee_companies", []):
        all_jobs += safe_fetch(f"recruitee:{slug}", fetch_recruitee, slug)
    for slug in config.get("workable_companies", []):
        all_jobs += safe_fetch(f"workable:{slug}", fetch_workable_company, slug)
    if config.get("use_arbeitnow"):
        all_jobs += safe_fetch("arbeitnow", fetch_arbeitnow)

    # --- MODERATE tier: 4x/hour ---
    if run_moderate:
        if config.get("use_remoteok"):
            all_jobs += safe_fetch("remoteok", fetch_remoteok)
        ws = config.get("workable_search", {})
        if ws.get("enabled"):
            all_jobs += safe_fetch(
                "workable-search", fetch_workable_search,
                ws.get("query", ""), ws.get("location", "United States"),
            )
        tm = config.get("themuse", {})
        if tm.get("enabled"):
            all_jobs += safe_fetch("themuse", fetch_themuse, tm.get("categories", []))
        if config.get("use_adzuna"):
            all_jobs += safe_fetch(
                "adzuna", fetch_adzuna,
                os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY"),
                keywords, config.get("adzuna_country", "us"),
            )
        print("Moderate-tier sources checked this run (RemoteOK/Workable search/The Muse/Adzuna)")

    # --- SLOW tier: 4x/day ---
    if run_slow:
        rm = config.get("remotive", {})
        if rm.get("enabled"):
            all_jobs += safe_fetch("remotive", fetch_remotive, rm.get("query", ""))
        print("Slow-tier sources checked this run (Remotive)")

    new_jobs = []
    now = now_utc.isoformat()
    for j in all_jobs:
        if not matches_keywords(j.get("title"), keywords, exclude_keywords):
            continue
        if j["id"] in seen:
            continue
        seen[j["id"]] = now
        j["found_at"] = now
        new_jobs.append(j)

    print(f"Checked {len(all_jobs)} postings across all sources this run, {len(new_jobs)} new match(es)")

    # Always persist "seen" so we don't re-notify next run even if email fails
    save_json(SEEN_PATH, seen)

    if new_jobs:
        log = new_jobs + log
        log = log[:MAX_LOG_ENTRIES]
        save_json(LOG_PATH, log)
        try:
            send_email(
                new_jobs,
                os.environ.get("SMTP_SERVER"), os.environ.get("SMTP_PORT"),
                os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS"),
                os.environ.get("NOTIFY_EMAIL"),
            )
        except Exception as e:
            print(f"WARNING: email send failed: {e}")


if __name__ == "__main__":
    main()
