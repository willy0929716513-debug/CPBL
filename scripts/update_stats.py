#!/usr/bin/env python3
"""
NPB 數據本地更新腳本 — Starter Safe Patch Version
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
ODDS_FILE       = os.path.join(DATA_DIR, "odds_today.json")


# =========================================================
# 🔥 ONLY FIX AREA: starter fallback（你問題的核心）
# =========================================================
def _safe_pitcher(team: str):
    base = TEAM_DEFAULT_SP.get(team) or PITCHERS.get(team) or {}
    return {
        "name": base.get("name", ""),
        "era": base.get("era"),
        "k9": base.get("k9"),
        "fip": base.get("fip"),
        "source": "safe_fallback"
    }


def _enrich_starters_in_schedule(today_str: str, dry: bool = False):
    try:
        with open(SCHED_FILE, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        log.warning("schedule load failed: %s", e)
        return

    games = payload.get("games", [])
    if not games:
        return

    today = datetime.date.fromisoformat(today_str)
    tomorrow = today + datetime.timedelta(days=1)

    def process(day):
        try:
            day_games = [g for g in games if g.get("date") == day.isoformat()]
            if not day_games:
                return 0

            # try real scraper first
            try:
                enrich_schedule_with_starters(day, day_games)
            except Exception as e:
                log.warning("starter scrape failed (%s)", e)

            # =========================
            # 🔥 FIX: 永遠保證不會 None
            # =========================
            for g in day_games:
                if not g.get("away_pitcher"):
                    g["away_pitcher"] = _safe_pitcher(g.get("away"))

                if not g.get("home_pitcher"):
                    g["home_pitcher"] = _safe_pitcher(g.get("home"))

                g["starter_source"] = g.get("starter_source", "safe_fallback")

            return len(day_games)

        except Exception as e:
            log.warning("starter process error: %s", e)
            return 0

    total = process(today) + process(tomorrow)

    if not dry:
        try:
            with open(SCHED_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("schedule save failed: %s", e)

    log.info("starter fixed slots: %d", total)


# =========================================================
# 以下全部保留你原本邏輯（完全不動）
# =========================================================

def merge_stats(live: dict, base: dict = None) -> dict:
    base = copy.deepcopy(base or PITCHERS)
    merged = {}

    for name in set(base) | set(live):
        p = copy.deepcopy(base.get(name, {}))
        for k, v in live.get(name, {}).items():
            if isinstance(v, (int, float)):
                p[k] = v
        enrich_pitcher(p)
        merged[name] = p

    return merged


def save_stats(merged: dict, dry: bool = False):
    if dry:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump({"stats": merged}, f, ensure_ascii=False, indent=2)


def update_schedule(games: list, dry: bool = False):
    if not games:
        return

    try:
        with open(SCHED_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except:
        data = {"games": []}

    data["games"] = games

    if not dry:
        with open(SCHED_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================================
# MAIN
# =========================================================
def main():
    now = datetime.datetime.now()
    today = now.date().isoformat()

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--skip-schedule", action="store_true")
    args = ap.parse_args()

    print("NPB UPDATE START")

    live = fetch_npbdata_jp_pitchers(now.year)
    merged = merge_stats(live)
    save_stats(merged, args.dry)

    games = []

    if not args.skip_schedule:
        from cpbl.stats_scraper import fetch_schedule_multi
        games = fetch_schedule_multi(now.date())

        update_schedule(games, args.dry)

        # 🔥 ONLY FIX CALLED HERE
        _enrich_starters_in_schedule(today, args.dry)

    print("DONE")


if __name__ == "__main__":
    main()