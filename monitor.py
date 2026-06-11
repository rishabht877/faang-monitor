#!/usr/bin/env python3
"""
FAANG+ Internship & New Grad SDE Job Monitor
Runs continuously on Railway. Polls every 10 minutes.
Sends email on new jobs + a daily heartbeat so you know it's alive.
"""

import requests
import json
import time
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — loaded from environment variables (set these in Railway dashboard)
# ─────────────────────────────────────────────────────────────────────────────

EMAIL_FROM         = os.environ["EMAIL_FROM"]        # your Gmail address
EMAIL_TO           = os.environ["EMAIL_TO"]          # where alerts go (can be same)
SMTP_PASSWORD      = os.environ["SMTP_PASSWORD"]     # Gmail App Password
POLL_INTERVAL_SECS = 10 * 60                         # 10 minutes
STATE_FILE         = "/app/data/seen_jobs.json"      # persisted on Railway volume

# ─────────────────────────────────────────────────────────────────────────────
# KEYWORDS
# ─────────────────────────────────────────────────────────────────────────────

TITLE_KEYWORDS = [
    "software engineer", "software developer", "sde", "swe",
    "backend engineer", "frontend engineer", "fullstack", "full stack",
    "machine learning engineer", "ml engineer", "data engineer",
    "platform engineer", "infrastructure engineer", "site reliability",
    "systems engineer", "computer vision", "ai engineer",
    "intern", "internship", "new grad", "university grad",
    "associate engineer", "entry level engineer",
]

EXCLUDE_KEYWORDS = [
    "senior", "staff", "principal", "director", "manager",
    "vp ", "vice president", "head of", "lead engineer",
]

# ─────────────────────────────────────────────────────────────────────────────
# FETCHERS
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

def greenhouse(token):
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return [
        {
            "id":       f"gh_{token}_{j['id']}",
            "title":    j.get("title", ""),
            "location": j.get("location", {}).get("name", ""),
            "url":      j.get("absolute_url", ""),
            "posted":   j.get("updated_at", "")[:10],
        }
        for j in r.json().get("jobs", [])
    ]


def lever(token):
    url = f"https://api.lever.co/v0/postings/{token}?mode=json&limit=500"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return [
        {
            "id":       f"lv_{token}_{j['id']}",
            "title":    j.get("text", ""),
            "location": j.get("categories", {}).get("location", ""),
            "url":      j.get("hostedUrl", ""),
            "posted":   datetime.fromtimestamp(j["createdAt"] / 1000).strftime("%Y-%m-%d")
                        if j.get("createdAt") else "",
        }
        for j in r.json()
    ]


def amazon_jobs():
    url = (
        "https://www.amazon.jobs/en/search.json"
        "?base_query=software+engineer&loc_query=United+States"
        "&job_type=Full-Time&category=software-development&result_limit=100"
    )
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return [
        {
            "id":       f"amz_{j['id_icims']}",
            "title":    j.get("title", ""),
            "location": j.get("normalized_location", ""),
            "url":      "https://www.amazon.jobs" + j.get("job_path", ""),
            "posted":   j.get("posted_date", ""),
        }
        for j in r.json().get("jobs", [])
    ]


def google_jobs():
    results = []
    for page in range(1, 4):
        url = (
            "https://careers.google.com/api/v3/search/"
            f"?q=software+engineer&page={page}&pageSize=50"
            "&employment_type=INTERN&employment_type=FULL_TIME"
            "&location=United+States"
        )
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            break
        jobs = r.json().get("jobs", [])
        if not jobs:
            break
        for j in jobs:
            results.append({
                "id":       f"goog_{j.get('id','')}",
                "title":    j.get("title", ""),
                "location": ", ".join(j.get("locations", [])),
                "url":      "https://careers.google.com/jobs/results/" + j.get("id","").split("/")[-1],
                "posted":   j.get("publish_date", ""),
            })
    return results


def meta_jobs():
    url = (
        "https://www.metacareers.com/jobs/search/"
        "?q=software+engineer&roles[0]=Intern&roles[1]=University+Grad"
        "&teams[0]=Software+Engineering&is_leadership=0&sort_by_new=true"
    )
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    tag  = soup.find("script", {"id": "__NEXT_DATA__"})
    if not tag:
        return []
    jobs_raw = (
        json.loads(tag.string)
            .get("props", {})
            .get("pageProps", {})
            .get("jobs", [])
    )
    return [
        {
            "id":       f"meta_{j.get('id','')}",
            "title":    j.get("title", ""),
            "location": (j.get("locations") or [""])[0],
            "url":      "https://www.metacareers.com/jobs/" + str(j.get("id","")),
            "posted":   j.get("post_date", ""),
        }
        for j in jobs_raw
    ]


def microsoft_jobs():
    url = (
        "https://gcsservices.careers.microsoft.com/search/api/v1/search"
        "?q=software+engineer&lc=United+States"
        "&exp=Students+and+recent+graduates&pgSz=50&pg=1"
    )
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    jobs = (
        r.json()
         .get("operationResult", {})
         .get("result", {})
         .get("jobs", [])
    )
    return [
        {
            "id":       f"msft_{j.get('jobId','')}",
            "title":    j.get("title", ""),
            "location": j.get("primaryLocation", ""),
            "url":      "https://jobs.careers.microsoft.com/global/en/job/" + j.get("jobId",""),
            "posted":   j.get("postedDate", ""),
        }
        for j in jobs
    ]


def apple_jobs():
    url = (
        "https://jobs.apple.com/api/role/search"
        "?query=software+engineer&team=MLAI,SFTWR&location=USA"
        "&page=1&sort=newest"
    )
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return [
        {
            "id":       f"aapl_{j.get('positionId','')}",
            "title":    j.get("postingTitle", ""),
            "location": (j.get("locations") or [{}])[0].get("name", ""),
            "url":      "https://jobs.apple.com/en-us/details/" + j.get("positionId",""),
            "posted":   j.get("postDateTime", "")[:10],
        }
        for j in r.json().get("searchResults", [])
    ]


# ─────────────────────────────────────────────────────────────────────────────
# COMPANY LIST
# ─────────────────────────────────────────────────────────────────────────────

COMPANIES = [
    ("Amazon",        amazon_jobs),
    ("Google",        google_jobs),
    ("Meta",          meta_jobs),
    ("Microsoft",     microsoft_jobs),
    ("Apple",         apple_jobs),
    ("Netflix",       lambda: greenhouse("netflix")),
    ("Airbnb",        lambda: greenhouse("airbnb")),
    ("Stripe",        lambda: greenhouse("stripe")),
    ("Databricks",    lambda: greenhouse("databricks")),
    ("OpenAI",        lambda: greenhouse("openai")),
    ("Anthropic",     lambda: greenhouse("anthropic")),
    ("Figma",         lambda: greenhouse("figma")),
    ("Notion",        lambda: greenhouse("notionhq")),
    ("Robinhood",     lambda: greenhouse("robinhood")),
    ("Coinbase",      lambda: greenhouse("coinbase")),
    ("Dropbox",       lambda: greenhouse("dropbox")),
    ("Lyft",          lambda: greenhouse("lyft")),
    ("DoorDash",      lambda: greenhouse("doordasheng")),
    ("Datadog",       lambda: greenhouse("datadog")),
    ("Snowflake",     lambda: greenhouse("snowflakecomputing")),
    ("Palantir",      lambda: greenhouse("palantirtechnologies")),
    ("Scale AI",      lambda: greenhouse("scaleai")),
    ("Waymo",         lambda: greenhouse("waymo")),
    ("Twilio",        lambda: greenhouse("twilio")),
    ("MongoDB",       lambda: greenhouse("mongodb")),
    ("Cloudflare",    lambda: greenhouse("cloudflare")),
    ("Plaid",         lambda: greenhouse("plaidinc")),
    ("Brex",          lambda: greenhouse("brex")),
    ("Rippling",      lambda: greenhouse("ripplingpeople")),
    ("Instacart",     lambda: greenhouse("maplebear")),
    ("Spotify",       lambda: lever("spotify")),
    ("Chime",         lambda: greenhouse("chimebank")),
    ("Grammarly",     lambda: greenhouse("grammarly")),
    # H1B-friendly + new grad focused
    ("Nvidia",        lambda: greenhouse("nvidia")),
    ("Intel",         lambda: greenhouse("intel")),
    ("Qualcomm",      lambda: greenhouse("qualcomm")),
    ("AMD",           lambda: greenhouse("amd")),
    ("Salesforce",    lambda: greenhouse("salesforce")),
    ("Adobe",         lambda: greenhouse("adobe")),
    ("Intuit",        lambda: greenhouse("intuit")),
    ("Workday",       lambda: greenhouse("workday")),
    ("ServiceNow",    lambda: greenhouse("servicenow")),
    ("Palo Alto Networks", lambda: greenhouse("paloaltonetworks")),
    ("CrowdStrike",   lambda: greenhouse("crowdstrike")),
    ("Okta",          lambda: greenhouse("okta")),
    ("Splunk",        lambda: greenhouse("splunk")),
    ("Zillow",        lambda: greenhouse("zillow")),
    ("Snap",          lambda: greenhouse("snap")),
    ("Reddit",        lambda: greenhouse("reddit")),
    ("LinkedIn",      lambda: greenhouse("linkedin")),
    ("ByteDance",     lambda: greenhouse("bytedance")),
    ("TikTok",        lambda: greenhouse("tiktok")),
    ("Shopify",       lambda: greenhouse("shopify")),
    ("Atlassian",     lambda: greenhouse("atlassian")),
    ("Asana",         lambda: greenhouse("asana")),
    ("HubSpot",       lambda: greenhouse("hubspot")),
    ("Duolingo",      lambda: greenhouse("duolingo")),
    ("Ramp",          lambda: greenhouse("ramp")),
    ("Anduril",       lambda: greenhouse("anduril")),
    ("SpaceX",        lambda: greenhouse("spacex")),
    ("Tesla",         lambda: greenhouse("tesla")),
    # Quant / Trading firms
    ("Jane Street",   lambda: greenhouse("janestreet")),
    ("Hudson River Trading", lambda: greenhouse("hudsonrivertrading")),
    ("Two Sigma",     lambda: greenhouse("twosigma")),
    ("Citadel",       lambda: greenhouse("citadel")),
    ("Citadel Securities", lambda: greenhouse("citadelsecurities")),
    ("DE Shaw",       lambda: greenhouse("deshaw")),
    ("Akuna Capital", lambda: greenhouse("akunacapital")),
    ("Optiver",       lambda: greenhouse("optiver")),
    ("IMC Trading",   lambda: greenhouse("imc")),
    ("Virtu Financial", lambda: greenhouse("virtu")),
    ("Five Rings",    lambda: greenhouse("fiverings")),
    ("SIG",           lambda: greenhouse("sig")),
]

# ─────────────────────────────────────────────────────────────────────────────
# FILTERING
# ─────────────────────────────────────────────────────────────────────────────

def is_relevant(title):
    t = title.lower()
    return (
        any(kw in t for kw in TITLE_KEYWORDS) and
        not any(ex in t for ex in EXCLUDE_KEYWORDS)
    )

def is_usa(location):
    if not location:
        return True
    loc = location.lower()
    return any(h in loc for h in [
        "united states", " us ", "u.s.", "usa", "remote",
        "seattle", "san francisco", "new york", "austin", "boston",
        "chicago", "los angeles", "menlo park", "cupertino", "bellevue",
        "redmond", "sunnyvale", "mountain view", "palo alto", "cambridge",
    ])

# ─────────────────────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────────────────────

def load_seen():
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(STATE_FILE, "w") as f:
        json.dump(list(seen), f)

# ─────────────────────────────────────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────────────────────────────────────

def send_email(subject, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_FROM, SMTP_PASSWORD)
        smtp.send_message(msg)


def alert_email(new_jobs):
    rows = "".join(f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee"><b>{j['company']}</b></td>
          <td style="padding:8px;border-bottom:1px solid #eee">
            <a href="{j['url']}" style="color:#0066cc">{j['title']}</a></td>
          <td style="padding:8px;border-bottom:1px solid #eee">{j['location']}</td>
          <td style="padding:8px;border-bottom:1px solid #eee">{j.get('posted','')}</td>
        </tr>""" for j in new_jobs)

    html = f"""
    <html><body style="font-family:sans-serif;max-width:900px;margin:auto">
      <h2 style="color:#d63031">🚨 {len(new_jobs)} new FAANG+ role(s) — {datetime.now():%b %d %H:%M}</h2>
      <table style="border-collapse:collapse;width:100%">
        <thead><tr style="background:#f4f4f4">
          <th style="padding:8px;text-align:left">Company</th>
          <th style="padding:8px;text-align:left">Role</th>
          <th style="padding:8px;text-align:left">Location</th>
          <th style="padding:8px;text-align:left">Posted</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </body></html>"""

    send_email(f"🚨 {len(new_jobs)} new FAANG+ SDE role(s) posted!", html)
    print(f"  ✉️  Alert sent — {len(new_jobs)} new jobs")


def heartbeat_email(stats):
    rows = "".join(
        f"<tr><td style='padding:6px'>{s['company']}</td>"
        f"<td style='padding:6px;color:{'green' if s['ok'] else 'red'}'>"
        f"{'✅ ' + str(s['count']) + ' jobs' if s['ok'] else '❌ ' + s['error']}</td></tr>"
        for s in stats
    )
    html = f"""
    <html><body style="font-family:sans-serif;max-width:700px;margin:auto">
      <h2 style="color:#00b894">💚 Job Monitor — Daily Heartbeat</h2>
      <p>Still running as of <b>{datetime.now():%b %d, %Y %H:%M UTC}</b></p>
      <table style="border-collapse:collapse;width:100%">
        <thead><tr style="background:#f4f4f4">
          <th style="padding:6px;text-align:left">Company</th>
          <th style="padding:6px;text-align:left">Status</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="color:#888;font-size:12px">Next heartbeat in ~24 hours</p>
    </body></html>"""
    send_email("💚 FAANG+ Monitor — still running", html)
    print("  💚 Heartbeat sent")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run_once(seen):
    new_jobs = []
    stats    = []
    for name, fetcher in COMPANIES:
        try:
            jobs = fetcher()
            count = 0
            for j in jobs:
                if j["id"] in seen:
                    continue
                if not is_relevant(j["title"]):
                    continue
                if not is_usa(j["location"]):
                    continue
                seen.add(j["id"])
                j["company"] = name
                new_jobs.append(j)
                count += 1
                print(f"  ✅ NEW: [{name}] {j['title']} — {j['location']}")
            stats.append({"company": name, "ok": True, "count": len(jobs)})
        except Exception as e:
            print(f"  ⚠️  {name}: {e}")
            stats.append({"company": name, "ok": False, "error": str(e)[:60]})
    return new_jobs, stats


def main():
    print("=" * 55)
    print("  FAANG+ Monitor starting")
    print(f"  {len(COMPANIES)} companies · every {POLL_INTERVAL_SECS//60} min")
    print("=" * 55)

    seen       = load_seen()
    first_run  = len(seen) == 0
    last_heartbeat = date.today()

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        print(f"\n[{now}] Polling...")

        new_jobs, stats = run_once(seen)
        save_seen(seen)

        if first_run:
            print(f"  First run — indexed {len(seen)} existing jobs. No email sent.")
            first_run = False
        elif new_jobs:
            alert_email(new_jobs)
        else:
            print("  No new jobs.")

        # Daily heartbeat
        if date.today() > last_heartbeat:
            heartbeat_email(stats)
            last_heartbeat = date.today()

        print(f"  Sleeping {POLL_INTERVAL_SECS // 60}m...")
        time.sleep(POLL_INTERVAL_SECS)


if __name__ == "__main__":
    main()
