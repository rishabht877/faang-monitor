# FAANG+ Job Monitor

Polls 35 top tech companies every 10 minutes for SDE internship and new grad roles.
Emails you instantly when something new is posted. Runs free on Railway — no laptop needed.

---

## Setup (15 minutes total)

### 1. Get a Gmail App Password
> This is NOT your regular Gmail password. It's a special 16-character code.

1. Go to https://myaccount.google.com/apppasswords
2. Sign in → click "Select app" → choose "Mail"
3. Click "Select device" → choose "Other" → type "job monitor"
4. Click Generate → copy the 16-character password (looks like: `abcd efgh ijkl mnop`)

---

### 2. Push this code to GitHub

```bash
# In terminal, from this folder:
git init
git add .
git commit -m "initial commit"

# Create a new repo on github.com (call it faang-monitor), then:
git remote add origin https://github.com/YOUR_USERNAME/faang-monitor.git
git push -u origin main
```

---

### 3. Deploy on Railway

1. Go to https://railway.app → sign up with GitHub (free)
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select your `faang-monitor` repo
4. Railway will detect the Procfile automatically — click **Deploy**

---

### 4. Set Environment Variables in Railway

In your Railway project → click your service → go to **Variables** tab → add these 3:

| Variable       | Value                          |
|----------------|--------------------------------|
| `EMAIL_FROM`   | your Gmail address             |
| `EMAIL_TO`     | where you want alerts sent     |
| `SMTP_PASSWORD`| your 16-char App Password      |

Click **Deploy** again after saving variables.

---

### 5. Verify it's working

- Check **Logs** tab in Railway — you should see:
  ```
  FAANG+ Monitor starting
  35 companies · every 10 min
  [2026-06-11 14:00] Polling...
  First run — indexed 847 existing jobs. No email sent.
  Sleeping 10m...
  ```
- You'll get a **daily heartbeat email** every 24 hours showing all 35 companies with ✅/❌ status
- When new jobs drop, you get an instant alert email with company, title, location, and direct link

---

## Adding more companies

**On Greenhouse** (most common): find the token in their careers URL
- `boards.greenhouse.io/stripe` → token is `stripe`
- Add to COMPANIES list: `("Company Name", lambda: greenhouse("token"))`

**On Lever**: same idea
- `jobs.lever.co/uber` → token is `uber`
- Add: `("Company Name", lambda: lever("token"))`

---

## Free tier limits

Railway's free Hobby plan gives you $5/month of compute credit.
This script uses ~$0.50–1.00/month (it mostly sleeps). You're well within free limits.
