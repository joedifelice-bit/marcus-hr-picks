# MLB HR Daily Prop Picks

A local app + daily refresh script for MLB home-run prop bet analysis. Top 30 ranked plays, BET / MONITOR / PASS tags vs FanDuel lines.

## Files in this folder

| File | Purpose |
|---|---|
| `MLB_HR_App.html` | The app. Double-click to open in your browser. |
| `picks.json` | Today's picks data (the app loads this). |
| `refresh_picks.py` | **Live-data refresh script.** Pulls fresh rosters + stats from MLB Stats API. Run this each day before regenerating picks. |
| `MLB_HR_Tracker_2026-05-01.xlsx` | Excel tracker (top 30, top 15 +EV, ROI log, methodology). |
| `MLB_HR_App_Netlify.zip` | Bundle for hosting on Netlify Drop (gives you a shareable URL). |
| `README.md` | This file. |

## Why the refresh script exists

Web search results lag reality. Articles from 2025 still show players on their 2025 teams even after offseason trades and free-agent signings. This caused real errors today:

- **Marcell Ozuna** signed with the Pirates Feb 16, 2026 — was being shown on the Braves
- **Pete Alonso** signed with the Orioles Dec 11, 2025 — was being shown on the Mets
- **Brandon Lowe** was traded to the Pirates Dec 19, 2025 — was being shown on the Rays

The MLB Stats API (`statsapi.mlb.com`) is the authoritative source for current rosters and recent game-log stats. `refresh_picks.py` pulls directly from it, so team data is always correct.

## Daily workflow

### 1. First thing each morning — run the refresh script

In Terminal, from this folder:

```bash
python3 refresh_picks.py
```

Or for a specific date:

```bash
python3 refresh_picks.py 2026-05-15
```

This fetches:

- ✅ Today's full schedule + probable starting pitchers
- ✅ Each player's **current team** (auto-resolves trade/free-agency moves)
- ✅ Each pitcher's last 5 starts (HR allowed, IP, ERA, K, BB)
- ✅ Each hitter's last 20 PA stats + season HR rate
- ✅ Career splits vs LHP / vs RHP
- ✅ Park HR factors

Output: `slate_data.json` — verified factual data, ready for analysis.

### 2. Ask Claude to apply the model

Open Cowork mode in this project and say:

> "Refresh picks from slate_data.json — apply v2 model and pull FanDuel HR odds for each hitter."

Claude reads `slate_data.json`, adds:

- FanDuel HR prop odds (web search or your paste)
- Statcast barrel% / hard-hit% (Baseball Savant, when extractable)
- Reverse-split detection (career LvL vs RvL OPS comparison)
- Final EV ranking + BET / MONITOR / PASS tags

Then writes the updated `picks.json` and syncs the embedded data inside `MLB_HR_App.html`.

### 3. Open the app

Double-click `MLB_HR_App.html`. Click **Generate Today's Picks**. The header date will match today, and the picks will reflect verified current rosters.

### 4. Bet, log, track

- **BET** plays = EV ≥ +5% with confidence ≥ B−. These are your card.
- **MONITOR** = wait for line to drift (note the trigger price in the card).
- **PASS** = priced too tight at FanDuel.
- Log each play in the Excel tracker's "Daily ROI Tracker" tab.

## What the refresh script does NOT pull

These still need Claude:

- **FanDuel HR prop odds** — no public API; pasting from FD app gives best accuracy
- **Statcast barrel% / hard-hit%** — would need adding `pybaseball` to the script (planned)
- **Reverse-split detection** — needs career split comparison (planned)

For now, the script is the systematic fix for the team-error problem. Once it runs, every player is verified against their current MLB team.

## Sharing the app

`MLB_HR_App_Netlify.zip` is ready to deploy:

1. Open https://app.netlify.com/drop
2. Drag the zip
3. You get a shareable public URL in seconds

To update the hosted version after a refresh: drag the updated `picks.json` over Netlify's deploy panel — the live app will pull fresh data on the next Generate click (no-cache header is set in `netlify.toml`).

## Methodology v2

P(HR) = HR/PA-vs-hand × Park HR factor × Pitcher HR/9 multiplier × Barrel-quality multiplier × Form factor × Expected PA

- **HR/PA vs hand**: hitter career or trailing-365-day HR per PA against pitcher handedness
- **Park HR factor**: 3-yr Statcast park factor for hitter handedness (Coors 1.30, GAB 1.10, Daikin 1.05, PNC 0.85 RHB / 1.05 LHB, Citi 0.96)
- **Pitcher HR/9 multiplier**: 60% L5 starts + 40% season HR/9, normalized to league avg HR/9 (~1.20)
- **Barrel-quality multiplier**: hitter barrel% × pitcher barrel%-allowed, normalized to league avg
- **Reverse-split flag**: triggers when pitcher's same-handed OPS allowed > opposite-handed (e.g., Bassitt LHB .844 / RHB .632; Springs LHB .873 / RHB .783)
- **Form factor**: capped 0.85–1.20× based on last-20-PA contact quality (NOT simple HR streaks)
- **Expected PA**: lineup spot 1–4 → 4.3-4.5 PA. 5–7 → 4.0 PA. 8–9 → 3.5 PA.

Fair odds (American): if P < 0.5 → +(1−P)/P × 100. EV % = P × FD payout − (1−P).

## What the app does NOT do

- Place bets (you bet from FanDuel — the app tells you what's +EV)
- Avoid the bookmaker's edge (HR prop vig runs 15–25% — even +EV plays produce small expected ROI; bankroll discipline matters)
- Save bet history automatically (use the Excel tracker for ROI logging)

## Troubleshooting

**App shows yesterday's picks:** The yellow stale-data banner will fire when picks data is from a previous date. Run `refresh_picks.py` and ask Claude to regenerate.

**Script errors with "Network unreachable":** Check internet connection. The script hits `statsapi.mlb.com` which is publicly accessible (no auth needed).

**Missing FanDuel odds for some players:** Web search coverage is partial. For full precision, paste the FanDuel HR props page text directly into Cowork chat — Claude will parse it.

**A player I want is missing from picks:** Tell Claude "Add [player name] to picks for today" — Claude will fetch their data and slot them into the model.
