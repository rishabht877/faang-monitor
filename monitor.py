#!/usr/bin/env python3
"""
Job Monitor v2 - Simplify feeds + direct Amazon API
Two-tier alerts:
  - INSTANT email  -> FAANG + top tech (priority companies)
  - DAILY DIGEST   -> everything else relevant, bundled once a day with heartbeat
Runs continuously on Railway. Polls every 10 minutes.
"""

import requests
import json
import time
import os
from datetime import datetime, date, timezone

# ---------------------------------------------------------------------------
# CONFIG (env vars set in Railway)
# ---------------------------------------------------------------------------

EMAIL_FROM         = os.environ["EMAIL_FROM"]
EMAIL_TO           = os.environ["EMAIL_TO"]
SENDGRID_API_KEY   = os.environ["SENDGRID_API_KEY"]
POLL_INTERVAL_SECS = 10 * 60
STATE_FILE         = "/app/data/seen_jobs.json"
DIGEST_FILE        = "/app/data/pending_digest.json"

# ---------------------------------------------------------------------------
# PRIORITY COMPANIES -> trigger INSTANT email
# Everything else relevant goes to the daily digest.
# Matching is case-insensitive substring on company name.
# ---------------------------------------------------------------------------

PRIORITY_COMPANIES = [
    # FAANG + top tech
    "amazon", "google", "meta", "facebook", "apple", "microsoft",
    "netflix", "stripe", "nvidia", "openai", "anthropic", "databricks",
    # added per request
    "robinhood", "coinbase", "figma", "rippling", "snap", "reddit",
    "doordash", "jane street", "citadel",
    # referral companies - instant alert so I can move fast with a referral
    "fidelity", "jpmorgan", "jp morgan", "j.p. morgan",
]

# DIGEST allowlist -> these get bundled into the daily digest.
# Anything NOT in priority and NOT here is dropped silently (no random startups).
DIGEST_COMPANIES = [
    # big tech / well-known
    "linkedin", "salesforce", "adobe", "intuit", "workday", "servicenow",
    "atlassian", "shopify", "spotify", "uber", "lyft", "airbnb", "pinterest",
    "dropbox", "block", "square", "paypal", "twilio", "cloudflare", "datadog",
    "snowflake", "mongodb", "palantir", "scale ai", "waymo", "cruise",
    "instacart", "doordash", "roblox", "unity", "twitch", "discord",
    # fintech / startups (strong)
    "brex", "ramp", "plaid", "chime", "affirm", "sofi", "gusto", "notion",
    "asana", "duolingo", "grammarly", "samsara", "verkada", "anduril",
    "spacex", "applied intuition", "rivian", "lucid",
    # security
    "crowdstrike", "okta", "palo alto", "zscaler", "cloudflare", "sentinelone",
    # quant / trading
    "hudson river", "two sigma", "optiver", "imc", "akuna", "drw", "jump trading",
    "five rings", "sig", "jane street", "citadel", "de shaw", "point72",
    "virtu", "flow traders", "tower research", "millennium",
    # AI labs
    "cohere", "mistral", "perplexity", "scale", "hugging face", "runway",
    "character", "adept", "together ai",
]

# ---------------------------------------------------------------------------
# KEYWORDS
# ---------------------------------------------------------------------------

TITLE_KEYWORDS = [
    "software engineer", "software developer", "sde", "swe",
    "backend", "frontend", "front end", "fullstack", "full stack",
    "machine learning", "ml engineer", "data engineer", "platform engineer",
    "infrastructure engineer", "site reliability", "systems engineer",
    "ai engineer", "new grad", "university grad", "intern",
    "associate engineer", "entry level",
]

EXCLUDE_KEYWORDS = [
    "senior", "sr.", "sr ", "staff", "principal", "director",
    "manager", "vp ", "vice president", "head of", "lead engineer",
]

# ---------------------------------------------------------------------------
# DATA SOURCES
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

SIMPLIFY_FEEDS = [
    # Summer 2026 internships (this coming summer)
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
    # Summer 2027 internships / co-ops (your main window, May 2027 grad)
    "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json",
    # New grad full-time (2025/2026, some 2027-start) - SimplifyJobs
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
    # New grad full-time - vanshb03 mirror (extra coverage)
    "https://raw.githubusercontent.com/vanshb03/New-Grad-2026/dev/.github/scripts/listings.json",
]


def _ts_to_date(ts):
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return ""


def fetch_simplify():
    jobs = []
    for feed in SIMPLIFY_FEEDS:
        try:
            r = requests.get(feed, headers=HEADERS, timeout=20)
            r.raise_for_status()
            for j in r.json():
                if not j.get("active", True) or not j.get("is_visible", True):
                    continue
                locs = j.get("locations") or []
                terms = j.get("terms") or []
                jobs.append({
                    "id":       "simplify_" + str(j.get("id", j.get("url", ""))),
                    "company":  j.get("company_name", ""),
                    "title":    j.get("title", ""),
                    "location": ", ".join(locs) if isinstance(locs, list) else str(locs),
                    "url":      j.get("url", ""),
                    "posted":   _ts_to_date(j.get("date_posted")),
                    "season":   ", ".join(terms) if isinstance(terms, list) else str(terms),
                })
        except Exception as e:
            print("  WARN Simplify feed error:", e)
    return jobs


def fetch_amazon():
    # Query multiple job types + queries so we catch internships AND full-time.
    # Amazon's API uses job_type=Full-Time / Intern; interns are a separate type.
    queries = [
        ("software engineer",        "Full-Time", "Full-Time"),
        ("software development",     "Full-Time", "Full-Time"),
        ("software engineer intern", "Intern",    "Internship"),
        ("software development engineer internship", "Intern", "Internship"),
        ("software engineer",        "Intern",    "Internship"),
    ]
    seen_ids = set()
    out = []
    for base_query, job_type, season_label in queries:
        url = (
            "https://www.amazon.jobs/en/search.json"
            "?base_query=" + base_query.replace(" ", "+") +
            "&loc_query=United+States"
            "&job_type=" + job_type +
            "&category=software-development&result_limit=100"
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            for j in r.json().get("jobs", []):
                jid = str(j.get("id_icims", j.get("job_path", "")))
                if jid in seen_ids:
                    continue
                seen_ids.add(jid)
                out.append({
                    "id":       "amz_" + jid,
                    "company":  "Amazon",
                    "title":    j.get("title", ""),
                    "location": j.get("normalized_location", ""),
                    "url":      "https://www.amazon.jobs" + j.get("job_path", ""),
                    "posted":   j.get("posted_date", ""),
                    "season":   season_label,
                })
        except Exception as e:
            print("  WARN Amazon query failed (" + job_type + "/" + base_query + "):", e)
    return out


# Direct Greenhouse scrapers for priority companies that open EARLY
# (July-Oct). These beat Simplify's lag by minutes-to-hours.
# Tries both Greenhouse API hosts so token/domain quirks don't break it.
DIRECT_GREENHOUSE = {
    "Databricks": "Databricks",
    "Stripe":     "stripe",
    "Anthropic":  "anthropic",
    "OpenAI":     "openai",
    "Robinhood":  "robinhood",
    "Coinbase":   "coinbase",
    "Figma":      "figma",
}


def fetch_direct_greenhouse():
    jobs = []
    for company, token in DIRECT_GREENHOUSE.items():
        got = None
        for host in ("boards-api.greenhouse.io", "job-boards.greenhouse.io"):
            try:
                r = requests.get(
                    "https://" + host + "/v1/boards/" + token + "/jobs",
                    headers=HEADERS, timeout=15,
                )
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                got = r.json().get("jobs", [])
                break
            except Exception:
                continue
        if got is None:
            print("  WARN direct greenhouse failed:", company)
            continue
        for j in got:
            jobs.append({
                "id":       "ghd_" + token + "_" + str(j["id"]),
                "company":  company,
                "title":    j.get("title", ""),
                "location": (j.get("location") or {}).get("name", ""),
                "url":      j.get("absolute_url", ""),
                "posted":   (j.get("updated_at", "") or "")[:10],
                "season":   "",
            })
    return jobs

# ---------------------------------------------------------------------------
# FILTERS
# ---------------------------------------------------------------------------

def is_relevant(title):
    t = title.lower()
    return (any(kw in t for kw in TITLE_KEYWORDS) and
            not any(ex in t for ex in EXCLUDE_KEYWORDS))


def is_usa(location):
    if not location:
        return True
    loc = location.lower()
    non_us = [
        # countries (full + common abbreviations)
        "canada", "mexico", "united kingdom", " uk", "u.k.", "ireland",
        "estonia", "poland", "australia", "hong kong", "india", "singapore",
        "germany", "deu", "france", "netherlands", "brazil", "japan", "korea",
        "china", "spain", "italy", "sweden", "israel", "switzerland", "swe ",
        "austria", "belgium", "denmark", "finland", "norway", "portugal",
        "romania", "czech", "hungary", "greece", "turkey", "uae", "taiwan",
        "philippines", "vietnam", "thailand", "malaysia", "indonesia",
        "argentina", "chile", "colombia", "peru", "egypt", "nigeria",
        "south africa", "new zealand", "scotland", "wales",
        # non-US cities that show up a lot
        "toronto", "vancouver", "montreal", "ottawa", "waterloo, on",
        "london", "dublin", "bangalore", "bengaluru", "hyderabad", "pune",
        "berlin", "munich", "paris", "amsterdam", "zurich", "stockholm",
        "tel aviv", "sydney", "melbourne", "tokyo", "seoul", "shanghai",
        "beijing", "shenzhen", "sao paulo", "mexico city", "warsaw",
        "barcelona", "madrid", "milan", "lisbon", "prague", "bucharest",
    ]
    # If any non-US signal appears AND there's no explicit US signal, drop it.
    # Note: ", ca" matches California but NOT "canada" (which is caught above first).
    us_signal = (
        "united states" in loc or "usa" in loc or "u.s." in loc or
        (", ca" in loc and "canada" not in loc)
    )
    if any(x in loc for x in non_us) and not us_signal:
        return False
    return True


def is_priority(company):
    c = company.lower()
    return any(p in c for p in PRIORITY_COMPANIES)


def is_digest_company(company):
    c = company.lower()
    return any(d in c for d in DIGEST_COMPANIES)

# ---------------------------------------------------------------------------
# STATE
# ---------------------------------------------------------------------------

def load_json(path, default):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)

# ---------------------------------------------------------------------------
# EMAIL (SendGrid HTTP API)
# ---------------------------------------------------------------------------

def send_email(subject, html):
    import urllib.request
    data = json.dumps({
        "personalizations": [{"to": [{"email": EMAIL_TO}]}],
        "from": {"email": EMAIL_FROM},
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
    }).encode()
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=data,
        headers={
            "Authorization": "Bearer " + SENDGRID_API_KEY,
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print("  WARN Email failed:", e)
        return False


def job_rows(jobs):
    rows = ""
    for j in jobs:
        rows += (
            "<tr>"
            "<td style='padding:8px;border-bottom:1px solid #eee'><b>" + j["company"] + "</b></td>"
            "<td style='padding:8px;border-bottom:1px solid #eee'>"
            "<a href='" + j["url"] + "' style='color:#0066cc'>" + j["title"] + "</a></td>"
            "<td style='padding:8px;border-bottom:1px solid #eee'>" + j.get("season", "") + "</td>"
            "<td style='padding:8px;border-bottom:1px solid #eee'>" + j["location"] + "</td>"
            "</tr>"
        )
    return rows


def instant_alert(jobs):
    html = (
        "<html><body style='font-family:sans-serif;max-width:900px;margin:auto'>"
        "<h2 style='color:#d63031'>NEW FAANG+ " + str(len(jobs)) + " role(s) - " +
        datetime.now().strftime("%b %d %H:%M") + "</h2>"
        "<table style='border-collapse:collapse;width:100%'>"
        "<thead><tr style='background:#f4f4f4'>"
        "<th style='padding:8px;text-align:left'>Company</th>"
        "<th style='padding:8px;text-align:left'>Role</th>"
        "<th style='padding:8px;text-align:left'>Season</th>"
        "<th style='padding:8px;text-align:left'>Location</th>"
        "</tr></thead><tbody>" + job_rows(jobs) + "</tbody></table>"
        "</body></html>"
    )
    if send_email("FAANG+ " + str(len(jobs)) + " new role(s)!", html):
        print("  ALERT instant sent -", len(jobs), "priority jobs")


def daily_digest(digest_jobs, sources_ok):
    count = len(digest_jobs)
    status = "all sources OK" if sources_ok else "some sources failed"
    if digest_jobs:
        body = job_rows(digest_jobs)
    else:
        body = "<tr><td colspan=4 style='padding:8px;color:#888'>No new broader-company roles today.</td></tr>"
    html = (
        "<html><body style='font-family:sans-serif;max-width:900px;margin:auto'>"
        "<h2 style='color:#00b894'>Daily Digest - " + datetime.now().strftime("%b %d, %Y") + "</h2>"
        "<p>" + str(count) + " new role(s) from broader companies in the last 24h. "
        "Monitor heartbeat: " + status + ".</p>"
        "<table style='border-collapse:collapse;width:100%'>"
        "<thead><tr style='background:#f4f4f4'>"
        "<th style='padding:8px;text-align:left'>Company</th>"
        "<th style='padding:8px;text-align:left'>Role</th>"
        "<th style='padding:8px;text-align:left'>Season</th>"
        "<th style='padding:8px;text-align:left'>Location</th>"
        "</tr></thead><tbody>" + body + "</tbody></table>"
        "<p style='color:#888;font-size:12px'>FAANG+ roles are sent instantly. This digest covers everything else.</p>"
        "</body></html>"
    )
    if send_email("Daily job digest - " + str(count) + " new roles", html):
        print("  DIGEST sent -", count, "broader jobs")

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def run_once(seen, pending_digest, first_run=False):
    all_jobs = fetch_simplify() + fetch_amazon() + fetch_direct_greenhouse()
    sources_ok = len(all_jobs) > 0

    instant = []
    for j in all_jobs:
        if j["id"] in seen:
            continue
        if not is_relevant(j["title"]):
            continue
        if not is_usa(j["location"]):
            continue
        seen.add(j["id"])

        if is_priority(j["company"]):
            instant.append(j)
            print("  PRIORITY:", j["company"], "-", j["title"])
        elif is_digest_company(j["company"]):
            pending_digest.append(j)
        # else: not a tracked company -> dropped silently

    # On the very first run we only index; never blast existing jobs.
    if instant and not first_run:
        instant_alert(instant)

    return sources_ok


def main():
    print("=" * 55)
    print("  Job Monitor v2 - Simplify feeds + Amazon API")
    print("  Instant:", ", ".join(PRIORITY_COMPANIES[:6]), "...")
    print("  Poll every", POLL_INTERVAL_SECS // 60, "min")
    print("=" * 55)

    seen           = set(load_json(STATE_FILE, []))
    pending_digest = load_json(DIGEST_FILE, [])
    first_run      = len(seen) == 0
    last_digest    = date.today()

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        print("\n[" + now + "] Polling...")

        sources_ok = run_once(seen, pending_digest, first_run=first_run)
        save_json(STATE_FILE, list(seen))

        if first_run:
            print("  First run - indexed", len(seen), "existing jobs. No emails sent.")
            pending_digest.clear()
            save_json(DIGEST_FILE, pending_digest)
            first_run = False
        else:
            save_json(DIGEST_FILE, pending_digest)

        if date.today() > last_digest:
            daily_digest(pending_digest, sources_ok)
            pending_digest.clear()
            save_json(DIGEST_FILE, pending_digest)
            last_digest = date.today()

        print("  Sleeping", POLL_INTERVAL_SECS // 60, "m... (digest queue:", len(pending_digest), ")")
        time.sleep(POLL_INTERVAL_SECS)


if __name__ == "__main__":
    main()
