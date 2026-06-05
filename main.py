#!/usr/bin/env python3
"""NPB/KBO Protector — 日職・韓職賽前勝負預測系統 (Web 版)"""

import os
import logging
import requests
from datetime import date, datetime
from flask import Flask, render_template, jsonify, request

from cpbl.scraper import CPBLScraper
from cpbl.predictor import PredictionModel
from cpbl.elo import ELOSystem
from cpbl.odds import OddsFetcher, MOCK_ODDS
import cpbl.mock_data as mock

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── 設定 ────────────────────────────────────────
DEMO_MODE      = os.environ.get("CPBL_DEMO", "1").lower() in ("1", "true", "yes")
DISCORD_URL    = os.environ.get("DISCORD_WEBHOOK_URL", "")
PORT           = int(os.environ.get("PORT", 5000))

# ── 快取 ────────────────────────────────────────
_cache: dict = {
    "date":        None,
    "games":       [],
    "standings":   [],
    "pitchers":    [],
    "last_update": None,
}

elo          = ELOSystem()
model        = PredictionModel(elo)
scraper      = CPBLScraper()
odds_fetcher = OddsFetcher()   # The Odds API → 運彩 → Mock


# ── 資料更新 ─────────────────────────────────────

def refresh(game_date: date | None = None) -> list:
    if game_date is None:
        game_date = date.today()

    log.info(f"Refreshing data for {game_date}  (demo={DEMO_MODE})")

    # 1. 取得賽程
    games = _fetch_games(game_date)

    # 2. 逐場預測
    for g in games:
        if g.get("away") and g.get("home") and g.get("status") != "輪休":
            weather    = None
            odds_data  = None

            if DEMO_MODE:
                key = f"{g['away']}-{g['home']}"
                odds_data = MOCK_ODDS.get(key, {})
            else:
                try:
                    weather = scraper.fetch_weather(g.get("venue", ""))
                except Exception:
                    pass
                odds_data = odds_fetcher.get(g["away"], g["home"]) or {}

            g["weather"]    = weather
            g["odds_raw"]   = odds_data   # 供 API 輸出
            g["prediction"] = model.predict(g, weather, odds_data)
        else:
            g["prediction"] = None
            g["odds_raw"]   = None

    _cache["date"]        = str(game_date)
    _cache["games"]       = games
    _cache["standings"]   = mock.get_standings()
    _cache["pitchers"]    = mock.get_top_pitchers(15)
    _cache["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return games


def _fetch_games(game_date: date) -> list:
    if DEMO_MODE:
        return mock.get_today_games(game_date)
    try:
        games = scraper.fetch_schedule(game_date)
        if games:
            return games
    except requests.HTTPError as e:
        log.warning(f"cpbl.com.tw HTTP {e.response.status_code}，使用 Demo 資料")
    except Exception as e:
        log.warning(f"爬蟲失敗：{e}，使用 Demo 資料")
    return mock.get_today_games(game_date)


# ── 路由 ─────────────────────────────────────────

@app.route("/")
def dashboard():
    d_str = request.args.get("date")
    if d_str:
        try:
            game_date = datetime.strptime(d_str, "%Y-%m-%d").date()
        except ValueError:
            game_date = date.today()
    else:
        game_date = date.today()

    if _cache["date"] != str(game_date):
        refresh(game_date)

    return render_template(
        "index.html",
        games=_cache["games"],
        standings=_cache["standings"],
        pitchers=_cache["pitchers"],
        game_date=str(game_date),
        last_update=_cache["last_update"],
        demo_mode=DEMO_MODE,
        weights={k: int(v * 100) for k, v in {
            "starter": 0.32, "lineup": 0.18, "bullpen": 0.13,
            "odds": 0.10,
            "home_away": 0.08, "recent_form": 0.07, "h2h": 0.05,
            "injuries": 0.03, "weather": 0.02, "defense": 0.02,
        }.items()},
    )


@app.route("/api/today")
def api_today():
    if not _cache["games"]:
        refresh()
    return jsonify({
        "games":       _cache["games"],
        "standings":   _cache["standings"],
        "pitchers":    _cache["pitchers"],
        "last_update": _cache["last_update"],
        "demo_mode":   DEMO_MODE,
    })


@app.route("/api/refresh")
def api_refresh():
    d_str = request.args.get("date")
    game_date = None
    if d_str:
        try:
            game_date = datetime.strptime(d_str, "%Y-%m-%d").date()
        except ValueError:
            pass
    games = refresh(game_date)
    return jsonify({"status": "ok", "count": len(games), "ts": _cache["last_update"]})


@app.route("/api/quota")
def api_quota():
    """查 The Odds API 剩餘配額"""
    return jsonify(odds_fetcher.quota())


@app.route("/api/pitcher/<name>")
def api_pitcher(name: str):
    p = mock.PITCHERS.get(name)
    if not p:
        return jsonify({"error": "找不到投手"}), 404
    return jsonify({**p, "name": name})


# ── Discord 推播 ──────────────────────────────────

def send_discord(games: list):
    if not DISCORD_URL:
        return
    lines = ["**⚾ NPB/KBO 今日賽前預測**\n"]
    for g in games:
        if not g.get("prediction"):
            continue
        pred = g["prediction"]
        hw   = int(pred["home_win_prob"] * 100)
        aw   = 100 - hw
        win  = g["home_name"] if pred["winner"] == "home" else g["away_name"]
        conf = pred["confidence"]

        odds_txt = ""
        of = pred.get("factors", {}).get("odds", {})
        if of.get("curr_home_odds"):
            mkt = of.get("market_home_prob", "?")
            vg  = of.get("analysis", {}).get("value_gap", 0) if of.get("analysis") else 0
            odds_txt = (
                f"\n  📋 賠率：客 `{of['curr_away_odds']}` / 主 `{of['curr_home_odds']}`"
                f"  市場隱含主隊 `{mkt}%`  差距 `{vg:+.0f}%`"
            )
            sigs = of.get("signals", [])
            if sigs:
                odds_txt += "\n  " + " | ".join(sigs[:2])

        lines.append(
            f"**{g['away_name']}** `{aw}%`  vs  `{hw}%` **{g['home_name']}**"
            f"  →  🏆 {win} (信心 {conf:.0f}%)"
            + odds_txt
        )
    try:
        requests.post(DISCORD_URL, json={"content": "\n".join(lines)}, timeout=8)
        log.info("Discord 推播成功")
    except Exception as e:
        log.error(f"Discord 推播失敗：{e}")


# ── 入口 ─────────────────────────────────────────

if __name__ == "__main__":
    refresh()
    if DISCORD_URL:
        send_discord(_cache["games"])
    app.run(host="0.0.0.0", port=PORT, debug=False)
