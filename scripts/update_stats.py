#!/usr/bin/env python3
"""
NPB 數據本地更新腳本 — FIXED STABLE VERSION
修正重點：
- 先發投手永遠不會全部未定
- fallback 不再 return empty name
- starter enrichment 強化
"""

import sys, os, json, time, logging, argparse, datetime, copy
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from bs4 import BeautifulSoup
from cpbl.mock_data import PITCHERS, TEAM_DEFAULT_SP
from cpbl.stats_scraper import (
    enrich_pitcher,
    fetch_npbdata_jp_pitchers,
    fetch_npbdata_jp_batters,
    fetch_pitcher_stats_nk,
    fetch_team_stats_nk,
    enrich_schedule_with_starters,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("update_stats")

DATA_DIR        = os.path.join(os.path.dirname(__file__), "..", "data")
STATS_FILE      = os.path.join(DATA_DIR, "pitcher_stats.json")
TEAM_STATS_FILE = os.path.join(DATA_DIR, "team_stats.json")
SCHED_FILE      = os.path.join(DATA_DIR, "schedule.json")


# =========================
# 🔥 FIXED FALLBACK (核心修正)
# =========================
def _fallback_pitcher(team: str):
    sp = TEAM_DEFAULT_SP.get(team)

    # 1️⃣ team default SP
    if sp:
        name = sp if isinstance(sp, str) else sp.get("name", "")
        base = PITCHERS.get(name, {})
        return {
            "name": name,
            "era": base.get("era", 3.50),
            "k9": base.get("k9", 7.5),
            "fip": base.get("fip", 3.80),
            "source": "team_default_sp"
        }

    # 2️⃣ mock fallback（一定有名字）
    for p in PITCHERS.values():
        if p.get("league") == "NPB":
            return {
                "name": p.get("name", "Unknown"),
                "era": p.get("era", 3.80),
                "k9": p.get("k9", 7.0),
                "fip": p.get("fip", 4.00),
                "source": "mock_fallback"
            }

    # 3️⃣ 最低保底（永遠不會空 name）
    return {
        "name": f"{team} SP",
        "era": 3.80,
        "k9": 7.0,
        "fip": 4.00,
        "source": "hard_fallback"
    }


# =========================
# schedule starter fix
# =========================
def _enrich_starters():
    try:
        with open(SCHED_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.warning("schedule load failed: %s", e)
        return

    games = data.get("games", [])
    if not games:
        return

    today = datetime.date.today()

    try:
        enrich_schedule_with_starters(today, games)
    except Exception as e:
        log.warning("starter scraper failed: %s", e)

    # 🔥 強制補值（核心修正）
    for g in games:
        if not g.get("away_pitcher"):
            g["away_pitcher"] = _fallback_pitcher(g["away"])
        if not g.get("home_pitcher"):
            g["home_pitcher"] = _fallback_pitcher(g["home"])

    with open(SCHED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log.info("starter enrichment completed")


# =========================
# main minimal safe
# =========================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    print("NPB update FIXED VERSION")

    # pitchers
    live = fetch_npbdata_jp_pitchers(args.year) or {}
    merged = copy.deepcopy(PITCHERS)

    for k, v in live.items():
        merged[k] = {**merged.get(k, {}), **v}
        enrich_pitcher(merged[k])

    os.makedirs(DATA_DIR, exist_ok=True)

    if not args.dry:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump({"stats": merged}, f, ensure_ascii=False, indent=2)

    # teams
    teams = fetch_npbdata_jp_batters(args.year) or fetch_team_stats_nk(args.year)

    if teams and not args.dry:
        with open(TEAM_STATS_FILE, "w", encoding="utf-8") as f:
            json.dump({"stats": teams}, f, ensure_ascii=False, indent=2)

    # schedule starter fix
    _enrich_starters()

    print("DONE")


if __name__ == "__main__":
    main()