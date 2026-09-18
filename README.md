# Job Alert Bot

Checks job postings on a schedule, emails you the moment something new
matches, and logs everything to a dashboard. Runs for free on GitHub Actions
— it keeps working whether your laptop is on or not.

**What it actually covers, and how often:**

| Source | What it is | How often checked |
|---|---|---|
| Greenhouse | Per-employer ATS board | Every ~5 min |
| Lever | Per-employer ATS board | Every ~5 min |
| Ashby | Per-employer ATS board | Every ~5 min |
| SmartRecruiters | Per-employer ATS board | Every ~5 min |
| Recruitee | Per-employer ATS board | Every ~5 min |
| Workable (per-company) | Per-employer ATS board | Every ~5 min |
| Arbeitnow | Community job board | Every ~5 min |
| RemoteOK | Community job board | Every 15 min |
| Workable search | Cross-company search across every Workable-hosted employer | Every 15 min |
| The Muse | Curated tech/professional job board | Every 15 min |
| Adzuna | Broad aggregator | Every 15 min |
| Remotive | Remote-jobs board | 4x/day |

Not every source is hit every run — see **"Why the different speeds"**
in step 6. Some of these free APIs publish real rate limits (Adzuna: 250
calls/day; Remotive: please check ≤4x/day) and this respects them; others
are just shared community endpoints that don't need hammering every 5
minutes to be useful.

**What it doesn't cover:** LinkedIn, Indeed, or Workday-based companies
(e.g. Amazon, Capital One) — none of those expose a public API. Set up
their own native alerts as a backup (see the bottom of this file) — those
are batched daily, not instant, so this bot is still your fast channel.
LinkedIn coverage exists as a separate, optional, paid add-on
(`linkedin_poller.py`) — see step 7.

---

## 1. Create the GitHub repo

- Create a new repo on GitHub, e.g. `job-alert-bot`.
- **Make it public.** GitHub Actions minutes are unlimited for public repos;
  on a private repo you'd blow through the free 2,000 min/month quota in
  about a week at a 5-minute polling interval. Nothing sensitive lives in
  the code — your email password and API keys go in encrypted GitHub
  Secrets (step 3), never in a file.
- Push these files to it:
  ```bash
  cd job-alert-bot
  git init
  git add .
  git commit -m "Initial job alert bot"
  git branch -M main
  git remote add origin https://github.com/<your-username>/job-alert-bot.git
  git push -u origin main
  ```

## 2. Turn on GitHub Pages (this is your dashboard)

- Repo → **Settings → Pages**
- Source: **Deploy from a branch**
- Branch: **main**, folder: **/docs**
- Save. After a minute or two your dashboard is live at:
  `https://<your-username>.github.io/job-alert-bot/`

## 3. Add your secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**.
Add each of these:

| Secret | Value |
|---|---|
| `SMTP_SERVER` | `smtp.office365.com` (Outlook) or `smtp.gmail.com` (Gmail) |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | your email address |
| `SMTP_PASS` | an **app password** (see below — not your regular password) |
| `NOTIFY_EMAIL` | the email address you want alerts sent *to* (can be the same as `SMTP_USER`) |
| `ADZUNA_APP_ID` | from developer.adzuna.com (step 4) |
| `ADZUNA_APP_KEY` | from developer.adzuna.com (step 4) |

**Getting an app password:**
- **Outlook/Microsoft:** turn on 2-step verification first (account.microsoft.com
  → Security), then go to Security → Advanced security options → App passwords
  → create one. Use that as `SMTP_PASS`.
- **Gmail:** turn on 2-step verification, then visit
  myaccount.google.com/apppasswords, create an app password, use that.

## 4. Get free Adzuna keys (2 minutes)

- Sign up at developer.adzuna.com/signup — free, no card needed.
- Your dashboard shows `app_id` and `app_key` immediately. Paste them into
  the two Adzuna secrets above.

## 5. Test it

- Repo → **Actions** tab → **Job Poll** workflow → **Run workflow** button.
- Check the run log to confirm it found postings without errors.
- If any new matches turned up, check your email and the dashboard.

Once that works, the schedule in `.github/workflows/job_poll.yml` takes over
and runs it automatically every 5 minutes — no more manual runs needed.

## 6. Customize it

**Keywords** — edit `config.json`:
```json
"keywords": ["software engineer", "devops", "cloud engineer", ...],
"exclude_keywords": ["senior", "staff", "principal", ...]
```
A posting must match at least one keyword and none of the excludes.

**Adding companies** — the starter Greenhouse list in `config.json` is a
small, unverified guess. To add any employer to any of the five per-employer
sources:
1. Go to the company's careers page.
2. Look at the URL, and add the identifier to the matching list:
   - `boards.greenhouse.io/<token>` or `job-boards.greenhouse.io/<token>` → `greenhouse_companies`
   - `jobs.lever.co/<token>` → `lever_companies`
   - `jobs.ashbyhq.com/<token>` → `ashby_companies`
   - `jobs.smartrecruiters.com/<id>` → `smartrecruiters_companies`
   - `<company>.recruitee.com` → `recruitee_companies`
   - `apply.workable.com/<slug>` or `<slug>.workable.com` → `workable_companies`
3. Commit the change. A wrong token just gets skipped with a warning in the
   Actions log — it won't break anything else.

You don't have to hunt down individual companies for **Workable, The Muse,
Adzuna, RemoteOK, Arbeitnow, or Remotive** — those search or list broadly on
their own; `workable_search.query`, `themuse.categories`, and
`remotive.query` in `config.json` control what they look for.

Companies on Workday, iCIMS, SuccessFactors, or their own custom ATS (most
large enterprises: Amazon, Capital One, most banks) can't be added this way
— there's no public API for any of those. Adzuna picks up some of these
secondhand; otherwise rely on native alerts (below).

**Why the different speeds** — `job_poller.py` checks its time on every run
and only calls some sources when the clock lines up (minute is a multiple of
15, or it's exactly 00:00/06:00/12:00/18:00 UTC). This is deliberate, not a
bug: Adzuna's free plan hard-caps at 250 calls/day (checking every 5 min
would blow through that by mid-morning), and Remotive's API terms ask for
no more than about 4 checks/day. Nothing needs configuring for this — the
tiers are handled inside the script.

## 7. LinkedIn (optional — stays free, but read this first)

LinkedIn has no public API, so the only way to check it automatically is a
third-party scraper. Know what you're turning on:

- It scrapes LinkedIn's **public** job search results — no login, no
  cookies, so there's no risk to your personal LinkedIn account. But it's
  still a scraper, not an official feed, and it breaches LinkedIn's Terms
  of Service on the scraping side.
- It costs real money on **your Apify account** (~$0.002 per job pulled).
  It runs on its own schedule — `.github/workflows/linkedin_poll.yml`,
  every 4 hours by default — specifically so it stays inside Apify's
  **$5/month free platform credit**. At that cadence it typically runs
  around $3–4/month in usage, comfortably inside the free tier. Going much
  more often (hourly or faster) will likely exceed it — check your usage
  at console.apify.com before tightening the schedule.
- It's **off by default**.

**To turn it on:**
1. Get a free Apify API token: console.apify.com/settings/integrations
   (no card required — the free plan includes $5/month of usage).
2. Add it as a repo secret: `APIFY_TOKEN`.
3. In `config.json`, set `"linkedin": { "enabled": true, ... }`.
4. Test it: Actions tab → **LinkedIn Poll** → Run workflow.

The `keywords`, `location`, and `datePosted` fields in that config block
feed LinkedIn's own search directly — edit them like you would a manual
LinkedIn search.

## 8. Back it up with native alerts (for what the bot can't reach)

These are genuinely useful as a second channel, but note they're **batched**
(usually once a day), not instant — the bot above is your fast path:

- **LinkedIn:** Jobs → search → "Create job alert" → set frequency to
  daily (LinkedIn's fastest option).
- **Indeed:** run a search → "Get new jobs for this search by email" → set
  frequency.
- **Google:** search e.g. `site:boards.greenhouse.io "cloud engineer"` and
  set up a Google Alert on the query for a second net.

---

### A note on the "seen" file

`seen_jobs.json` just remembers which postings you've already been notified
about, so you don't get re-pinged every 5 minutes for the same job. It grows
over time; if it gets unwieldy after a few months, you can safely delete
entries older than ~60 days.
