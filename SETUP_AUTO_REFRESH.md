# Auto-Refresh Setup — Daily picks with zero clicks

This setup makes the app automatically show fresh picks every day. Once configured, your morning workflow becomes:

> Open the app → click Generate → see today's best plays.

No script-running, no chat with Claude, no pasting odds (assuming the FanDuel scrape works that day).

## How it works

```
┌────────────────────────┐    cron 8:30am ET    ┌──────────────────┐
│ GitHub Actions runner  │──────────────────────▶│ refresh_picks.py │
└────────────────────────┘                       └────────┬─────────┘
                                                          │ writes
                                                          ▼
┌────────────────────────┐   git push            ┌──────────────────┐
│   GitHub repo          │◀──────────────────────│   picks.json     │
└──────────┬─────────────┘                       └──────────────────┘
           │ webhook
           ▼
┌────────────────────────┐
│  Netlify auto-deploys  │
└──────────┬─────────────┘
           │
           ▼
┌────────────────────────┐
│  https://your-app.com  │  ← you click Generate, app fetches fresh picks.json
└────────────────────────┘
```

## One-time setup (~15 minutes)

### 1. Push this folder to GitHub

```bash
cd "/Users/joedifelice/Documents/Claude/Projects/Marcus - MLB HR Prop Bets"
git init
git add .
git commit -m "Initial commit"
git branch -M main
# Create a new repo at https://github.com/new (private is fine), then:
git remote add origin https://github.com/YOUR-USERNAME/marcus-hr-picks.git
git push -u origin main
```

### 2. Connect Netlify to the GitHub repo

1. Go to https://app.netlify.com → "Add new site" → "Import an existing project"
2. Choose GitHub and authorize
3. Select the `marcus-hr-picks` repo
4. Build settings: leave defaults (no build command needed — it's static files)
5. Publish directory: `.` (root)
6. Click Deploy
7. Netlify gives you a URL like `https://playful-tartufo-abc.netlify.app`
8. (Optional) Domain settings → rename to `marcus-hr-picks.netlify.app`

You'll also want to rename `MLB_HR_App.html` to `index.html` in the repo so Netlify serves it as the root page. Or add a `_redirects` file:

```
/  /MLB_HR_App.html  200
```

### 3. Confirm GitHub Actions is enabled

The workflow file is already at `.github/workflows/daily-refresh.yml`. After you push:

1. Go to your repo on GitHub → "Actions" tab
2. You should see "Daily HR Picks Refresh" listed
3. Click "Run workflow" once to test it manually
4. Verify it commits a new `picks.json` after running
5. Verify Netlify auto-deploys (check Netlify dashboard for a new deploy)

### 4. Done

Tomorrow morning at 8:30am ET, GitHub Actions runs the script, commits the new `picks.json`, Netlify rebuilds, and your app shows fresh picks. Open the app any time after that, click Generate, see today's slate.

## What the daily refresh handles

✅ **Today's MLB schedule + probable starting pitchers** — from MLB Stats API (free, official, rock-solid)
✅ **Each player's CURRENT team** — auto-resolves trades and free-agent moves
✅ **Pitcher last 5 starts** — HR/9 trend
✅ **Hitter season HR rate** — base for probability
✅ **Park HR factors** — built-in lookup
✅ **Model probability + EV** — full v2 model
✅ **BET / MONITOR / PASS tagging** — by EV thresholds
✅ **Bet99 odds estimation** — heuristic (~8-12% longer than FD)
⚠️ **FanDuel HR prop odds** — best-effort scrape of FanDuel Research's daily page

## What can fail (and what to do)

**FanDuel scrape fails** → picks.json publishes with no FD odds. The app shows picks ranked by model P(HR) but EV/sizing will be missing. Fix: paste FD odds via Cowork chat, or upgrade to a paid odds API (next section).

**Workflow doesn't run** → GitHub Actions may pause cron schedules on inactive repos (60+ days no commits). To keep it active, ensure the workflow commits picks.json daily — that counts as activity. If you see it paused, manually trigger from the Actions tab.

**Netlify doesn't auto-deploy** → check that the repo is connected and that "Auto publishing" is enabled in Netlify site settings. Or use a build hook from GitHub Actions to ping Netlify directly.

## Upgrading to truly hands-off (paid)

Add a [TheOddsAPI](https://the-odds-api.com) key (~$30/mo) and update `refresh_picks.py` to call them for both FanDuel + Bet99 odds. They're licensed, ToS-compliant, and reliable. The cron then has zero manual fallback. Open a Cowork session and ask: *"Wire TheOddsAPI into refresh_picks.py — here's my key: [key]"* — I'll handle the integration.

## Manual trigger

To re-run immediately (e.g., late-breaking lineup news):

- **From GitHub**: Actions tab → Daily HR Picks Refresh → Run workflow
- **Locally** (if you have the repo cloned): `python3 refresh_picks.py` then `git add picks.json && git commit -m "manual refresh" && git push`

## Time zones

The cron is set to **12:30 UTC = 8:30 AM ET**. To change:

```yaml
on:
  schedule:
    - cron: '30 12 * * *'   # change this
```

Use https://crontab.guru/ to test new strings. For an afternoon refresh (catches late lineup news), try `'0 22 * * *'` (10 PM UTC = 6 PM ET).
