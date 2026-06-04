#!/usr/bin/env python3
"""CPBL 場中更新器 — 每次執行：讀 picks_latest.json → 抓即時比分 → 更新 live_games → 存回"""
import json, logging, os, sys, time, datetime, requests

sys.path.insert(0, ".")
from cpbl.scraper import CPBLScraper

log = logging.getLogger("live_update")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

TW        = datetime.timezone(datetime.timedelta(hours=8))
JSON_PATH = "docs/picks_latest.json"
DISCORD   = os.environ.get("DISCORD_WEBHOOK_URL", os.environ.get("DISCORD_WEBHOOK", ""))

TEAM_CN = {
    "AEL": "中信兄弟", "CT": "統一7-ELEVEn獅",
    "FG":  "富邦悍將",  "WL": "樂天桃猿", "TSG": "台鋼雄鷹",
}


def notify(msg):
    log.info(msg)
    if DISCORD:
        try:
            requests.post(DISCORD, json={"content": msg}, timeout=8)
        except Exception as e:
            log.warning("Discord: %s", e)


def fetch_live_scores(scraper, today):
    """Try to get live game data from cpbl.com.tw; returns list of live game dicts."""
    try:
        games = scraper.fetch_schedule(today)
        live  = []
        for g in games:
            status = str(g.get("status", "")).lower()
            if any(s in status for s in ["進行", "live", "●", "in_progress"]):
                away = g.get("away", "")
                home = g.get("home", "")
                live.append({
                    "away":       away,
                    "home":       home,
                    "away_cn":    g.get("away_name") or TEAM_CN.get(away, away),
                    "home_cn":    g.get("home_name") or TEAM_CN.get(home, home),
                    "away_runs":  int(g.get("away_score", 0) or 0),
                    "home_runs":  int(g.get("home_score", 0) or 0),
                    "inning":     int(g.get("inning", 1) or 1),
                    "top_inning": True,
                    "bet":        None,
                    "reason":     None,
                    "projected_total": None,
                })
        return live
    except Exception as e:
        log.warning("Scraper: %s", e)
        return None   # None = error, different from [] = confirmed no live games


def in_game_window():
    """Time-based fallback: is it within typical game hours?"""
    now = datetime.datetime.now(TW)
    nm  = now.hour * 60 + now.minute
    for sh, sm in [(13, 5), (17, 5), (18, 35)]:
        if sh * 60 + sm <= nm <= sh * 60 + sm + 180:
            return True
    return False


def generate_live_picks(live_games, game_preds):
    result = []
    for g in live_games:
        home, away   = g["home"], g["away"]
        inning       = g["inning"]
        top_inning   = g["top_inning"]
        home_r, away_r = g["home_runs"], g["away_runs"]
        total        = home_r + away_r
        diff         = home_r - away_r

        pred      = game_preds.get(f"{home}|{away}", {})
        mkt_total = float(pred.get("market_total") or 8.5)
        p_home    = float(pred.get("home_win_prob") or 0.5)

        innings_done = float(inning) - (1.0 if top_inning else 0.5)
        innings_left = max(0.0, 9.0 - innings_done)
        rate         = mkt_total / 9.0
        projected    = round(total + rate * innings_left, 1)
        expected_now = round(mkt_total * innings_done / 9.0, 1) if innings_done > 0 else 0.0
        pace         = (total / expected_now) if expected_now > 0 else 1.0

        bet = reason = None
        if inning >= 6 and innings_left >= 1.5 and pace <= 0.60:
            bet    = "大小分 UNDER"
            reason = f"第{inning}局僅{total}分（預期{expected_now}分），低分走勢盤口{mkt_total}"
        elif 4 <= inning <= 7 and expected_now > 0 and pace >= 1.40 and total >= 5:
            bet    = "大小分 OVER"
            reason = f"第{inning}局已得{total}分（預期{expected_now}分），高分走勢盤口{mkt_total}"
        elif inning >= 7 and diff >= 2 and p_home >= 0.45:
            bet    = "主隊獨贏"
            reason = f"第{inning}局主隊領先{diff}分（賽前主隊勝率{round(p_home*100)}%）"
        elif inning >= 7 and diff <= -2 and p_home <= 0.55:
            bet    = "客隊獨贏"
            reason = f"第{inning}局客隊領先{abs(diff)}分（賽前客隊勝率{round((1-p_home)*100)}%）"
        elif 4 <= inning <= 8 and -2 <= diff <= -1 and p_home >= 0.54:
            bet    = "主隊讓分(+1.5)"
            reason = f"主隊落後{abs(diff)}分 第{inning}局，賽前主隊勝率{round(p_home*100)}%"
        elif 4 <= inning <= 8 and 1 <= diff <= 2 and p_home <= 0.46:
            bet    = "客隊讓分(+1.5)"
            reason = f"客隊落後{diff}分 第{inning}局，賽前客隊勝率{round((1-p_home)*100)}%"

        result.append({**g, "projected_total": projected, "market_total": mkt_total, "bet": bet, "reason": reason})

    return result


def main():
    if not os.path.exists(JSON_PATH):
        log.error("%s not found — run cpbl_bot.py first", JSON_PATH)
        return

    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    game_preds = data.get("game_preds", {})
    prev_bets  = {
        f"{g['away_cn']}@{g['home_cn']}|{g.get('bet','')}"
        for g in data.get("live_games", []) if g.get("bet")
    }

    today   = datetime.datetime.now(TW).date()
    scraper = CPBLScraper()

    live_games = fetch_live_scores(scraper, today)

    if live_games is None:
        # Scraper error
        if in_game_window():
            log.info("Scraper error but in game window — keeping existing live_games")
            live_games = data.get("live_games", [])
        else:
            live_games = []

    live_picks = generate_live_picks(live_games, game_preds)

    # Discord notify new picks
    for pick in live_picks:
        if pick.get("bet"):
            key = f"{pick['away_cn']}@{pick['home_cn']}|{pick.get('bet','')}"
            if key not in prev_bets:
                notify(f"⚾ **場中推薦 — {pick['bet']}**\n{pick['away_cn']} @ {pick['home_cn']}\n{pick.get('reason','')}")

    now_tw = datetime.datetime.now(TW)
    data["live_games"]       = live_picks
    data["live_updated_at"]  = now_tw.strftime("%Y-%m-%d %H:%M") + " (台灣時間)"
    data["live_updated_ts"]  = int(time.time())

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log.info("Done — %d 場進行中 / %d 個場中推薦",
             len(live_picks), sum(1 for g in live_picks if g.get("bet")))


if __name__ == "__main__":
    main()
