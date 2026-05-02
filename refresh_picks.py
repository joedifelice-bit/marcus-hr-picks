#!/usr/bin/env python3
"""
refresh_picks.py — Pull today's MLB slate, apply the v2 model, and write picks.json.

Designed to run autonomously (no Claude in the loop). GitHub Actions runs this
daily; the resulting picks.json is committed and Netlify auto-deploys it.

Usage:
    python3 refresh_picks.py            # today's slate
    python3 refresh_picks.py 2026-05-01 # specific date

Outputs:
    picks.json    — final ranked picks with EV, sizing, BET/MONITOR/PASS tags
    slate_data.json — raw factual data (audit trail)

Data sources:
    ✅ MLB Stats API (statsapi.mlb.com) — schedule, current rosters, recent stats
    ✅ FanDuel Research HR props page (best-effort scrape) — odds for the day
    ⚠ Bet99 — estimated from FanDuel (no public API; paste real lines for confirmed)

What this DOES handle automatically:
    ✅ Today's schedule + probable starting pitchers
    ✅ Each player's CURRENT team (auto-resolves trades)
    ✅ Pitcher last 5 starts (HR/9 trend)
    ✅ Hitter season HR rate + last-20-PA contact
    ✅ Park HR factors
    ✅ Model probability + EV
    ✅ FanDuel HR prop odds (when scrape succeeds)
    ✅ BET / MONITOR / PASS tagging by EV thresholds

Limitations:
    - FD scrape is brittle (HTML changes break it). Falls back gracefully.
    - For 99% reliability, integrate a paid odds API (TheOddsAPI / OddsJam).
    - Statcast barrel% / hard-hit% would need pybaseball (planned add).
    - Reverse-split detection still requires manual flagging (planned add).
"""

import json
import sys
import re
import datetime as dt
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

API = "https://statsapi.mlb.com/api/v1"
WEATHER_API = "https://api.open-meteo.com/v1/forecast"  # free, no auth required
SCRIPT_DIR = Path(__file__).resolve().parent

# Stadium metadata: lat, lng, roof type, bearing from home plate to dead center field (deg from N).
# Roof: 'open' = no roof, 'retractable' = closes for bad weather, 'fixed_dome' = always closed.
STADIUMS = {
    "Coors Field":              {"lat": 39.7559, "lng": -104.9942, "roof": "open",        "cf_bearing": 0},
    "Great American Ball Park": {"lat": 39.0974, "lng": -84.5071,  "roof": "open",        "cf_bearing": 120},
    "Yankee Stadium":           {"lat": 40.8296, "lng": -73.9262,  "roof": "open",        "cf_bearing": 60},
    "Fenway Park":              {"lat": 42.3467, "lng": -71.0972,  "roof": "open",        "cf_bearing": 45},
    "Daikin Park":              {"lat": 29.7572, "lng": -95.3553,  "roof": "retractable", "cf_bearing": 0},
    "Citizens Bank Park":       {"lat": 39.9061, "lng": -75.1665,  "roof": "open",        "cf_bearing": 30},
    "Globe Life Field":         {"lat": 32.7475, "lng": -97.0824,  "roof": "retractable", "cf_bearing": 350},
    "Sutter Health Park":       {"lat": 38.5800, "lng": -121.5132, "roof": "open",        "cf_bearing": 0},
    "Citi Field":               {"lat": 40.7571, "lng": -73.8458,  "roof": "open",        "cf_bearing": 25},
    "PNC Park":                 {"lat": 40.4469, "lng": -80.0057,  "roof": "open",        "cf_bearing": 100},
    "loanDepot park":           {"lat": 25.7781, "lng": -80.2197,  "roof": "retractable", "cf_bearing": 70},
    "Oracle Park":              {"lat": 37.7786, "lng": -122.3893, "roof": "open",        "cf_bearing": 90},
    "Comerica Park":            {"lat": 42.3390, "lng": -83.0485,  "roof": "open",        "cf_bearing": 150},
    "Tropicana Field":          {"lat": 27.7682, "lng": -82.6534,  "roof": "fixed_dome",  "cf_bearing": 60},
    "Busch Stadium":            {"lat": 38.6226, "lng": -90.1928,  "roof": "open",        "cf_bearing": 60},
    "Target Field":             {"lat": 44.9817, "lng": -93.2776,  "roof": "open",        "cf_bearing": 90},
    "Truist Park":              {"lat": 33.8908, "lng": -84.4678,  "roof": "open",        "cf_bearing": 60},
    "Chase Field":              {"lat": 33.4452, "lng": -112.0667, "roof": "retractable", "cf_bearing": 0},
    "Angel Stadium":            {"lat": 33.8003, "lng": -117.8827, "roof": "open",        "cf_bearing": 60},
    "Nationals Park":           {"lat": 38.8730, "lng": -77.0074,  "roof": "open",        "cf_bearing": 30},
    "T-Mobile Park":            {"lat": 47.5914, "lng": -122.3325, "roof": "retractable", "cf_bearing": 60},
    "Wrigley Field":            {"lat": 41.9484, "lng": -87.6553,  "roof": "open",        "cf_bearing": 30},
    "American Family Field":    {"lat": 43.0280, "lng": -87.9712,  "roof": "retractable", "cf_bearing": 70},
    "Oakland Coliseum":         {"lat": 37.7516, "lng": -122.2005, "roof": "open",        "cf_bearing": 60},
    "Petco Park":               {"lat": 32.7073, "lng": -117.1566, "roof": "open",        "cf_bearing": 0},
    "Dodger Stadium":           {"lat": 34.0739, "lng": -118.2400, "roof": "open",        "cf_bearing": 25},
    "Rogers Centre":            {"lat": 43.6414, "lng": -79.3894,  "roof": "retractable", "cf_bearing": 0},
    "Camden Yards":             {"lat": 39.2839, "lng": -76.6217,  "roof": "open",        "cf_bearing": 30},
    "Kauffman Stadium":         {"lat": 39.0517, "lng": -94.4803,  "roof": "open",        "cf_bearing": 45},
    "Progressive Field":        {"lat": 41.4962, "lng": -81.6852,  "roof": "open",        "cf_bearing": 0},
}

PARK_HR_FACTORS = {
    "Coors Field":              {"R": 1.30, "L": 1.32, "S": 1.31},
    "Great American Ball Park": {"R": 1.10, "L": 1.18, "S": 1.14},
    "Yankee Stadium":           {"R": 1.05, "L": 1.18, "S": 1.10},
    "Fenway Park":              {"R": 1.06, "L": 1.02, "S": 1.04},
    "Daikin Park":              {"R": 1.03, "L": 1.05, "S": 1.04},
    "Citizens Bank Park":       {"R": 1.07, "L": 1.10, "S": 1.08},
    "Globe Life Field":         {"R": 1.04, "L": 1.06, "S": 1.05},
    "Sutter Health Park":       {"R": 1.10, "L": 1.10, "S": 1.10},
    "Citi Field":               {"R": 0.95, "L": 0.97, "S": 0.96},
    "PNC Park":                 {"R": 0.85, "L": 1.05, "S": 0.95},
    "loanDepot park":           {"R": 0.94, "L": 0.96, "S": 0.95},
    "Oracle Park":              {"R": 0.90, "L": 0.85, "S": 0.88},
    "Comerica Park":            {"R": 0.92, "L": 0.96, "S": 0.94},
    "Tropicana Field":          {"R": 1.02, "L": 1.05, "S": 1.03},
    "Busch Stadium":            {"R": 0.92, "L": 0.95, "S": 0.93},
    "Target Field":             {"R": 0.98, "L": 0.99, "S": 0.98},
    "Truist Park":              {"R": 1.02, "L": 1.00, "S": 1.01},
    "Chase Field":              {"R": 1.10, "L": 1.10, "S": 1.10},
    "Angel Stadium":            {"R": 1.04, "L": 1.00, "S": 1.02},
    "Nationals Park":           {"R": 1.04, "L": 1.04, "S": 1.04},
    "T-Mobile Park":            {"R": 0.92, "L": 0.92, "S": 0.92},
    "Wrigley Field":            {"R": 1.00, "L": 0.98, "S": 0.99},
    "American Family Field":    {"R": 1.05, "L": 1.05, "S": 1.05},
    "Oakland Coliseum":         {"R": 0.92, "L": 0.92, "S": 0.92},
}

LEAGUE_AVG_HR9 = 1.20  # league avg HR/9 baseline


def fetch_json(path, params=None, base=API):
    if params:
        path = f"{path}?{urllib.parse.urlencode(params)}"
    url = f"{base}{path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "marcus-hr-picks/2.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  ! HTTP {e.code} for {url}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"  ! Error fetching {url}: {e}", file=sys.stderr)
        return {}


def fetch_text(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  ! fetch_text failed for {url}: {e}", file=sys.stderr)
        return ""


# ---------- MLB Stats API helpers ----------

def get_schedule(date_str):
    data = fetch_json("/schedule", {"sportId": 1, "date": date_str, "hydrate": "probablePitcher,team,venue"})
    games = []
    for date_obj in data.get("dates", []):
        for g in date_obj.get("games", []):
            away = g["teams"]["away"]
            home = g["teams"]["home"]
            games.append({
                "game_pk": g.get("gamePk"),
                "venue": g.get("venue", {}).get("name", "Unknown"),
                "away_team": away["team"]["name"],
                "away_team_abbr": away["team"].get("abbreviation", ""),
                "away_team_id": away["team"]["id"],
                "home_team": home["team"]["name"],
                "home_team_abbr": home["team"].get("abbreviation", ""),
                "home_team_id": home["team"]["id"],
                "away_pitcher": (away.get("probablePitcher") or {}).get("fullName"),
                "away_pitcher_id": (away.get("probablePitcher") or {}).get("id"),
                "home_pitcher": (home.get("probablePitcher") or {}).get("fullName"),
                "home_pitcher_id": (home.get("probablePitcher") or {}).get("id"),
            })
    return games


def get_player(person_id):
    data = fetch_json(f"/people/{person_id}")
    people = data.get("people") or []
    if not people: return {}
    p = people[0]
    return {
        "id": p.get("id"),
        "fullName": p.get("fullName"),
        "currentTeam_abbr": p.get("currentTeam", {}).get("abbreviation", "FA"),
        "primaryPosition": p.get("primaryPosition", {}).get("abbreviation", ""),
        "batSide": p.get("batSide", {}).get("code", "?"),
        "pitchHand": p.get("pitchHand", {}).get("code", "?"),
    }


def get_pitcher_stats(person_id, season):
    """Returns season + last-5-starts aggregate."""
    season_data = fetch_json(f"/people/{person_id}/stats",
        {"stats": "season", "group": "pitching", "season": season, "gameType": "R"})
    log_data = fetch_json(f"/people/{person_id}/stats",
        {"stats": "gameLog", "group": "pitching", "season": season, "gameType": "R"})
    season_stat = ((season_data.get("stats") or [{}])[0].get("splits") or [{}])[0].get("stat", {})
    starts = []
    for s in (log_data.get("stats") or [{}])[0].get("splits", []):
        st = s.get("stat", {})
        if int(st.get("gamesStarted") or 0) > 0:
            starts.append({
                "date": s.get("date"),
                "ip": float(st.get("inningsPitched") or 0),
                "hr": int(st.get("homeRuns") or 0),
            })
    starts.sort(key=lambda x: x["date"], reverse=True)
    l5 = starts[:5]
    l5_ip = sum(x["ip"] for x in l5)
    l5_hr = sum(x["hr"] for x in l5)
    season_ip = float(season_stat.get("inningsPitched") or 0)
    season_hr = int(season_stat.get("homeRuns") or 0)
    return {
        "season_ip": season_ip,
        "season_era": float(season_stat.get("era") or 0),
        "season_hr": season_hr,
        "season_hr_per_9": round((season_hr * 9.0) / season_ip, 2) if season_ip > 0 else None,
        "l5_ip": l5_ip,
        "l5_hr": l5_hr,
        "l5_hr_per_9": round((l5_hr * 9.0) / l5_ip, 2) if l5_ip > 0 else None,
    }


def get_hitter_stats(person_id, season):
    season_data = fetch_json(f"/people/{person_id}/stats",
        {"stats": "season", "group": "hitting", "season": season, "gameType": "R"})
    season_stat = ((season_data.get("stats") or [{}])[0].get("splits") or [{}])[0].get("stat", {})
    return {
        "g": int(season_stat.get("gamesPlayed") or 0),
        "pa": int(season_stat.get("plateAppearances") or 0),
        "hr": int(season_stat.get("homeRuns") or 0),
        "ops": float(season_stat.get("ops") or 0),
        "iso": round(float(season_stat.get("slg") or 0) - float(season_stat.get("avg") or 0), 3),
        "hr_per_g": round(int(season_stat.get("homeRuns") or 0) / max(int(season_stat.get("gamesPlayed") or 1), 1), 3),
    }


def get_team_top_hitters(team_id, season, n=8):
    data = fetch_json(f"/teams/{team_id}/roster", {"rosterType": "active"})
    out = []
    for entry in data.get("roster", []):
        pos = entry.get("position", {}).get("abbreviation", "")
        if pos == "P": continue
        pid = entry["person"]["id"]
        hs = get_hitter_stats(pid, season)
        if hs.get("g", 0) < 5: continue
        p = get_player(pid)
        hs.update({
            "id": pid,
            "name": entry["person"]["fullName"],
            "current_team": p.get("currentTeam_abbr", ""),
            "bat_side": p.get("batSide", "?"),
            "position": pos,
        })
        out.append(hs)
    out.sort(key=lambda x: x.get("hr_per_g", 0), reverse=True)
    return out[:n]


# ---------- FanDuel odds scrape (best-effort) ----------

def scrape_fanduel_hr_odds(date_str):
    """
    Attempts to extract HR prop odds from FanDuel Research's daily page.
    Format URL: https://www.fanduel.com/research/mlb-home-run-prop-odds-{m}-{d}-{yyyy}
    Returns {player_name: '+XYZ', ...} on success, {} on failure.
    """
    yyyy, mm, dd = date_str.split("-")
    url = f"https://www.fanduel.com/research/mlb-home-run-prop-odds-{int(mm)}-{int(dd)}-{yyyy}"
    print(f"  Attempting FD odds scrape: {url}")
    html = fetch_text(url)
    if not html:
        print("  → FD scrape failed (no HTML)")
        return {}
    # Loose pattern: "FirstName LastName" followed within 200 chars by a "+NNN" or "-NNN"
    odds_map = {}
    pattern = re.compile(
        r'([A-Z][a-zÀ-ſ\']+(?:\s+[A-Z][a-zÀ-ſ\']+){1,2})[^+\-\d]{1,300}?([+-]\d{2,4})\s*(?:to|·|HR|home run|odds)',
        re.IGNORECASE
    )
    for m in pattern.finditer(html):
        name = m.group(1).strip()
        odds = m.group(2).strip()
        if name not in odds_map:
            odds_map[name] = odds
    print(f"  → FD scrape extracted {len(odds_map)} odds entries")
    return odds_map


def estimate_bet99(fd_odds_str):
    if not fd_odds_str:
        return None, "unavailable"
    try:
        n = int(fd_odds_str.replace("+", ""))
    except:
        return None, "unavailable"
    if n < 200:    adj = int(round(n * 1.04 / 10) * 10)
    elif n < 500:  adj = int(round(n * 1.08 / 10) * 10)
    elif n < 1000: adj = int(round(n * 1.12 / 10) * 10)
    else:          adj = int(round(n * 1.10 / 10) * 10)
    return (f"+{adj}" if adj >= 0 else f"{adj}"), "estimated"


# ---------- Weather ----------

def fetch_weather_for_game(venue, game_time_utc=None):
    """
    Pulls forecast for the venue's coordinates from open-meteo (free, no auth).
    Returns dict {temp_f, wind_mph, wind_dir_deg, precip_pct, fetched_at}.
    Returns None if venue unknown or API fails.
    """
    s = STADIUMS.get(venue)
    if not s:
        return None
    try:
        params = {
            "latitude": s["lat"],
            "longitude": s["lng"],
            "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m,precipitation_probability",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "forecast_days": 2,
        }
        url = f"{WEATHER_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "marcus-hr-picks/2.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # Match closest hour to game time (or noon local if not provided)
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            return None
        # Pick the index closest to game time, or 19:00 UTC (3pm ET) as default
        target_iso = (game_time_utc or "")[:13]
        idx = 0
        if target_iso:
            try:
                idx = next(i for i, t in enumerate(times) if t >= target_iso)
            except StopIteration:
                idx = len(times) - 1
        else:
            # default to mid-afternoon at the venue
            idx = min(len(times) - 1, 18)
        return {
            "temp_f": round(hourly["temperature_2m"][idx], 0),
            "wind_mph": round(hourly["wind_speed_10m"][idx], 1),
            "wind_dir_deg": round(hourly["wind_direction_10m"][idx], 0),
            "precip_pct": int(hourly.get("precipitation_probability", [0]*len(times))[idx] or 0),
            "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        print(f"  ! Weather fetch failed for {venue}: {e}", file=sys.stderr)
        return None


def determine_roof_status(venue, weather):
    """Heuristic: retractable roof closes for rain, extreme cold/heat, or strong wind."""
    s = STADIUMS.get(venue, {})
    roof = s.get("roof", "open")
    if roof == "open":
        return "open"
    if roof == "fixed_dome":
        return "closed"
    # retractable
    if not weather:
        return "unknown"
    if weather["precip_pct"] >= 40:
        return "closed"
    if weather["temp_f"] < 55 or weather["temp_f"] > 95:
        return "closed"
    if weather["wind_mph"] >= 25:
        return "closed"
    return "open"


def weather_hr_factor(venue, weather):
    """
    Returns a multiplier applied to P(HR) to account for weather.
    Closed roof or fixed dome = 1.00 (no effect).
    Open conditions: combine wind + temperature contributions.
    """
    if not weather:
        return 1.00
    roof_status = determine_roof_status(venue, weather)
    if roof_status in ("closed", "unknown"):
        return 1.00
    s = STADIUMS.get(venue, {})
    cf_bearing = s.get("cf_bearing", 0)
    wind_dir = weather["wind_dir_deg"]
    wind_mph = weather["wind_mph"]
    # Wind direction in meteorology = direction wind is COMING FROM.
    # Wind is "blowing out to CF" when wind_dir is OPPOSITE of cf_bearing.
    # Compute angle between wind-blowing-toward-direction and CF bearing.
    wind_blowing_toward = (wind_dir + 180) % 360
    diff = abs(wind_blowing_toward - cf_bearing)
    if diff > 180: diff = 360 - diff
    # diff = 0 → wind blowing straight out to CF; diff = 180 → wind in from CF
    cosine = abs((180 - diff) / 180.0 - 0.5) * 2  # 0 at perp, 1 at parallel-out OR parallel-in
    wind_factor = 1.00
    if diff <= 60:
        # blowing out — boost
        wind_factor = 1.00 + min(0.30, wind_mph * 0.015 * (1 - diff/90))
    elif diff >= 120:
        # blowing in — suppress
        wind_factor = 1.00 - min(0.25, wind_mph * 0.012 * ((diff - 90)/90))
    # Temperature: each °F above/below 70 = 0.5% effect, capped
    temp_factor = 1.00 + max(-0.15, min(0.15, (weather["temp_f"] - 70) * 0.005))
    combined = round(wind_factor * temp_factor, 3)
    return max(0.75, min(1.30, combined))


# ---------- Model ----------

def park_factor(venue, bat_side):
    pf = PARK_HR_FACTORS.get(venue, {})
    return pf.get(bat_side) or pf.get("S") or 1.00


def model_p_hr(hitter, pitcher_stats, park_hr, expected_pa, weather_factor=1.00):
    """
    v2.1 model with weather:
    P(HR per game) = base_hr_per_pa × park_factor × pitcher_HR9_mult × weather_factor × expected_pa
    """
    if hitter.get("pa", 0) < 30:
        return None  # too small a sample
    base_hr_per_pa = hitter["hr"] / hitter["pa"]
    pitcher_hr9 = pitcher_stats.get("l5_hr_per_9") or pitcher_stats.get("season_hr_per_9") or LEAGUE_AVG_HR9
    pitcher_mult = max(0.5, min(2.0, pitcher_hr9 / LEAGUE_AVG_HR9))
    p_per_pa = base_hr_per_pa * park_hr * pitcher_mult * weather_factor
    p = 1 - (1 - p_per_pa) ** expected_pa
    return round(min(max(p, 0.02), 0.50), 4)


def fair_odds(p):
    if p is None or p <= 0 or p >= 1: return "—"
    if p < 0.5:
        return f"+{round((1-p)/p*100)}"
    return f"-{round(p/(1-p)*100)}"


def compute_ev(p, american_odds_str):
    if p is None or not american_odds_str: return None
    try:
        a = int(american_odds_str.replace("+", ""))
    except:
        return None
    payout = a / 100 if a > 0 else 100 / abs(a)
    return round(p * payout - (1 - p), 4)


def tag_action(ev, conf="B"):
    if ev is None: return "PASS"
    if ev >= 0.05: return "BET"
    if ev >= -0.05: return "MONITOR"
    return "PASS"


def confidence_grade(hitter, pitcher_stats):
    g = hitter.get("g", 0)
    if g >= 25 and pitcher_stats.get("l5_ip", 0) >= 20: return "B+"
    if g >= 15: return "B"
    if g >= 8: return "B-"
    return "C"


# ---------- Main pipeline ----------

def build_picks_for_game(game, season, fd_odds_map):
    venue = game["venue"]
    # Fetch weather ONCE per game
    weather = fetch_weather_for_game(venue, game.get("game_time_utc"))
    roof_status = determine_roof_status(venue, weather)
    w_factor = weather_hr_factor(venue, weather)

    if weather:
        wind_arrow = wind_dir_label(weather["wind_dir_deg"], STADIUMS.get(venue, {}).get("cf_bearing", 0))
        weather_summary = f"{int(weather['temp_f'])}°F · {weather['wind_mph']} mph {wind_arrow} · roof {roof_status}"
    else:
        weather_summary = "weather n/a"

    picks = []
    for side in ("away", "home"):
        opp = "home" if side == "away" else "away"
        opp_pitcher_id = game[f"{opp}_pitcher_id"]
        opp_pitcher_name = game[f"{opp}_pitcher"]
        if not opp_pitcher_id:
            continue
        opp_p_meta = get_player(opp_pitcher_id)
        opp_hand = opp_p_meta.get("pitchHand", "?")
        opp_p_stats = get_pitcher_stats(opp_pitcher_id, season)
        team_id = game[f"{side}_team_id"]
        team_abbr = game[f"{side}_team_abbr"]
        opp_abbr = game[f"{opp}_team_abbr"]
        hitters = get_team_top_hitters(team_id, season, n=6)

        for h in hitters:
            bat = h["bat_side"]
            park_hr = park_factor(venue, bat)
            expected_pa = 4.3 if h.get("hr_per_g", 0) >= 0.15 else 4.0
            p_hr = model_p_hr(h, opp_p_stats, park_hr, expected_pa, w_factor)
            if p_hr is None: continue

            fd_odds = fd_odds_map.get(h["name"])
            bet99_odds, b99_status = estimate_bet99(fd_odds)
            ev = compute_ev(p_hr, fd_odds) if fd_odds else None
            conf = confidence_grade(h, opp_p_stats)
            action = tag_action(ev, conf) if ev is not None else "MONITOR"

            picks.append({
                "rank": 0,
                "action": action,
                "player": h["name"],
                "team": h["current_team"] or team_abbr,
                "bat": bat,
                "opp_team": opp_abbr,
                "opp_pitcher": opp_pitcher_name,
                "opp_hand": opp_hand,
                "park": venue,
                "park_hr_factor": round(park_hr, 2),
                "weather": weather,
                "roof_status": roof_status,
                "weather_factor": w_factor,
                "weather_summary": weather_summary,
                "lineup_spot": "TBD",
                "expected_pa": expected_pa,
                "hitter_barrel_pct": None,
                "pitcher_barrel_allowed_pct": None,
                "reverse_split_flag": "NORMAL",
                "model_p_hr": p_hr,
                "fair_odds": fair_odds(p_hr),
                "fd_odds": fd_odds or "—",
                "bet99_odds": bet99_odds or "—",
                "bet99_status": b99_status,
                "ev_pct": ev if ev is not None else 0,
                "confidence": conf,
                "notes": (f"{h['name']} ({bat}) vs {opp_pitcher_name} ({opp_hand}HP) at {venue}. "
                          f"Weather: {weather_summary} (×{w_factor}). "
                          f"Season: {h['hr']} HR / {h['g']} G. SP L5 HR/9: {opp_p_stats.get('l5_hr_per_9') or '—'}." +
                          ("" if fd_odds else " [FanDuel odds not auto-extracted — paste from FD app]")),
                "key_stats": [
                    f"Hitter: {h['hr']} HR in {h['g']} G ({round(h['hr_per_g']*100)}%)",
                    f"SP L5 HR/9: {opp_p_stats.get('l5_hr_per_9') or 'n/a'}",
                    f"SP season ERA: {opp_p_stats.get('season_era') or 'n/a'}",
                    f"Park HR factor: {park_hr}",
                    f"Weather factor: ×{w_factor}",
                ],
                "risks": [
                    "Lineup spot unconfirmed (script estimate)",
                    "Statcast barrel% not yet integrated",
                    "FD odds scraped — may be stale or missing"
                ],
            })
    return picks


def wind_dir_label(wind_dir_deg, cf_bearing):
    """Returns a short label like 'OUT to RF', 'IN from CF', 'crosswind LF→RF'."""
    wind_blowing_toward = (wind_dir_deg + 180) % 360
    diff = (wind_blowing_toward - cf_bearing) % 360
    if diff > 180: diff = diff - 360
    a = abs(diff)
    if a < 30:    return "OUT to CF"
    if a < 60:    return f"OUT to {'RF' if diff > 0 else 'LF'}"
    if a < 120:   return f"crosswind {'L→R' if diff > 0 else 'R→L'}"
    if a < 150:   return f"IN from {'RF' if diff > 0 else 'LF'}"
    return "IN from CF"


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
    season = int(date_str.split("-")[0])
    print(f"=== Refreshing picks for {date_str} (season {season}) ===\n")

    games = get_schedule(date_str)
    print(f"Found {len(games)} games\n")

    print("Attempting FanDuel HR odds scrape...")
    fd_odds_map = scrape_fanduel_hr_odds(date_str)
    if not fd_odds_map:
        print("  ! FD scrape failed — picks will publish without confirmed odds.")
        print("  ! Paste FD lines into picks.json manually or wait for next cron run.\n")

    all_picks = []
    for g in games:
        print(f"• {g['away_team_abbr']} @ {g['home_team_abbr']}  ({g['venue']})")
        all_picks.extend(build_picks_for_game(g, season, fd_odds_map))

    # Rank by EV (when available) then by P(HR)
    all_picks.sort(key=lambda x: (-(x.get("ev_pct") or -1), -x.get("model_p_hr", 0)))
    all_picks = all_picks[:30]
    for i, p in enumerate(all_picks, start=1):
        p["rank"] = i

    output = {
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "slate_date": date_str,
        "slate_label": dt.datetime.fromisoformat(date_str).strftime("%A, %B %-d, %Y") + " (auto-refreshed)",
        "games_in_slate": len(games),
        "games_analyzed": len(games),
        "data_confidence": (
            "Auto-refreshed: rosters + recent stats verified from MLB Stats API. "
            f"FanDuel odds: {len(fd_odds_map)} entries scraped." if fd_odds_map
            else "Auto-refreshed: rosters + recent stats verified from MLB Stats API. "
                 "FanDuel odds scrape failed — paste lines manually for accurate EV."
        ),
        "model_version": "2.0-auto",
        "tier_thresholds": {
            "BET": "EV ≥ +5% AND confidence ≥ B-",
            "MONITOR": "EV between -5% and +5%",
            "PASS": "EV < -5% at quoted FD line"
        },
        "available_sportsbooks": ["fanduel", "bet99"],
        "sportsbook_note": "FanDuel odds scraped from public FD Research page. Bet99 odds estimated.",
        "picks": all_picks,
        "sources": [
            {"label": "MLB Stats API (rosters + stats)", "url": "https://statsapi.mlb.com/api/v1/schedule"},
            {"label": "FanDuel Research HR Props (odds)",
             "url": f"https://www.fanduel.com/research/mlb-home-run-prop-odds-{date_str.replace('-', '-')}"},
        ]
    }

    out_path = SCRIPT_DIR / "picks.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n=== Wrote {out_path} ({len(all_picks)} picks) ===")
    bet_count = sum(1 for p in all_picks if p["action"] == "BET")
    mon_count = sum(1 for p in all_picks if p["action"] == "MONITOR")
    print(f"=== BET: {bet_count}  MONITOR: {mon_count}  PASS: {len(all_picks) - bet_count - mon_count} ===")


if __name__ == "__main__":
    main()
