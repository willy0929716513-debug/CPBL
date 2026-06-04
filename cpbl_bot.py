#!/usr/bin/env python3
"""CPBL Protector Bot — 按照 mlb_bot 模式"""
import os, json, logging, datetime, requests, sys
sys.path.insert(0, ".")

from cpbl.scraper import CPBLScraper
from cpbl.elo import ELOSystem
from cpbl.predictor import PredictionModel
from cpbl.odds import OddsFetcher, MOCK_ODDS
import cpbl.mock_data as mock
from cpbl.mock_data import PITCHERS, VENUE_FACTORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cpbl_bot")

TW = datetime.timezone(datetime.timedelta(hours=8))

# ── Config ─────────────────────────────────────────────────────────────────
JSON_PATH   = "docs/picks_latest.json"
GIST_DESC   = "cpbl_bot_history"
DISCORD_URL = os.environ.get("DISCORD_WEBHOOK", os.environ.get("DISCORD_WEBHOOK_URL", ""))
GH_TOKEN    = os.environ.get("GH_TOKEN", os.environ.get("GIST_TOKEN", ""))
DEMO_MODE   = os.environ.get("CPBL_DEMO", "0") in ("1", "true", "yes")

KELLY       = 0.25
KELLY_FLOOR = 50.0
KELLY_MAX   = 200.0
BANK        = 1000.0
EDGE_MIN    = 0.03 if DEMO_MODE else 0.06
CONF_MIN    = 0.55 if DEMO_MODE else 0.60

# ── Helpers ────────────────────────────────────────────────────────────────

def kelly_stake(p_win, dec_odds):
    b = dec_odds - 1.0
    if b <= 0: return 0.0
    k = (b * p_win - (1 - p_win)) / b
    return round(min(max(k * KELLY * BANK, KELLY_FLOOR), KELLY_MAX), 0) if k > 0 else 0.0

def calc_edge(p_model, dec_odds):
    return p_model - 1.0 / dec_odds

def get_tier(conf):
    if conf >= 0.82: return 1   # 💎 Diamond
    if conf >= 0.72: return 2   # 🔥 Fire
    return 3                    # ⭐ Star

TIER_EMOJI = {1: "💎", 2: "🔥", 3: "⭐"}

# ── Gist ───────────────────────────────────────────────────────────────────

def _gh_headers():
    return {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}

def load_gist():
    if not GH_TOKEN: return None, []
    try:
        resp = requests.get("https://api.github.com/gists", headers=_gh_headers(), timeout=10)
        for g in resp.json():
            if g.get("description") == GIST_DESC:
                gid    = g["id"]
                detail = requests.get(f"https://api.github.com/gists/{gid}", headers=_gh_headers(), timeout=10).json()
                raw    = list(detail["files"].values())[0]["raw_url"]
                return gid, requests.get(raw, timeout=10).json()
    except Exception as e:
        log.warning("Gist load: %s", e)
    return None, []

def save_gist(gid, records):
    if not GH_TOKEN: return
    body = json.dumps(records, ensure_ascii=False, indent=2)
    pl   = {"description": GIST_DESC, "public": False,
            "files": {"history.json": {"content": body}}}
    try:
        url = f"https://api.github.com/gists/{gid}" if gid else "https://api.github.com/gists"
        fn  = requests.patch if gid else requests.post
        fn(url, headers=_gh_headers(), json=pl, timeout=10)
        log.info("Gist saved (%d records)", len(records))
    except Exception as e:
        log.warning("Gist save: %s", e)

# ── Discord ────────────────────────────────────────────────────────────────

def send_discord(picks, game_date, history=None):
    if not DISCORD_URL or not picks: return
    now_tw   = datetime.datetime.now(TW)
    time_str = now_tw.strftime("%m/%d %H:%M")

    # Build history summary
    hist_str = "尚無歷史記錄"
    if history:
        settled = [h for h in history if h.get("result") is not None]
        if settled:
            wins   = sum(1 for h in settled if h["result"] == "W")
            ml_rec = [h for h in settled if h.get("bet_type") == "ML"]
            rl_rec = [h for h in settled if h.get("bet_type") == "RL"]
            tot_rec= [h for h in settled if h.get("bet_type") in ("TOT",)]
            def wr(lst): return f"{sum(1 for x in lst if x['result']=='W')}/{len(lst)}" if lst else ""
            parts  = [f"{wins}勝/{len(settled)}場 ({wins/len(settled)*100:.0f}%)"]
            if ml_rec:  parts.append(f"ML {wr(ml_rec)}")
            if rl_rec:  parts.append(f"RL {wr(rl_rec)}")
            if tot_rec: parts.append(f"TOT {wr(tot_rec)}")
            hist_str = "  ".join(parts)

    TIER_LABEL = {1: "💎 頂級", 2: "🔥 強力", 3: "⭐ 穩定"}

    lines = [
        "⚾ **CPBL V2 分析報告**",
        f"🕐 {time_str} (台灣時間) | ✅賽程 ✅盤口 ✅傷兵 ✅近況",
        f"📊 歷史: {hist_str}",
        "",
        f"**推薦 {len(picks)} 場（💎強→⭐弱 排序）**",
    ]

    for p in picks:
        asp = p.get("away_sp") or {}
        hsp = p.get("home_sp") or {}

        def fmt_sp(pitcher: dict) -> str:
            name = pitcher.get("name", "")
            if not name:
                return "TBD"
            tag = "🌏" if pitcher.get("foreign") else ""
            era = pitcher.get("era", "?")
            r3  = pitcher.get("recent_3_era", era)
            k9  = pitcher.get("k9", "?")
            return f"{tag}{name}(ERA {era} 近3場ERA {r3} K/9:{k9})"

        vf        = VENUE_FACTORS.get(p.get("venue", ""), {})
        pf_str    = f" PF{vf.get('run_factor',1.0):.2f}" if vf else ""
        venue_tag = f"🏟️{p.get('venue','')}{pf_str}" if p.get("venue") else ""
        g_date    = p.get("game_date", game_date)
        g_time    = p.get("game_time", p.get("time", ""))
        hw        = round(p.get("home_win_prob", 0.5) * 100, 1)
        market    = round(p.get("market_home_prob", 0), 1)   # already %
        be_pct    = round(100.0 / p["bp"], 1) if p.get("bp", 0) > 1 else "?"
        total     = p.get("market_total", "")

        lines += [
            "",
            f"**{TIER_LABEL.get(p['tier'],'⭐ 穩定')}  {p['away_cn']} @ {p['home_cn']}**",
            f"🗓️ {g_date} {g_time} (台灣時間) {venue_tag}",
            f"⚾ 先發: {fmt_sp(asp)} — {fmt_sp(hsp)}",
            f"💰 推薦: `{p['bet_label']}` @ **{p['bp']}**",
            f"> 市場主隊: {market}% | 模型主隊: {hw}% | 盈虧平衡: {be_pct}%",
            f"> Edge: **{p['edge']*100:+.1f}%** 信心{p['conf']*100:.0f}% | Kelly: ${p['stake']:.0f}",
        ]
        if total:
            lines.append(f"> 大小分: {total}")
        for sig in (p.get("signals") or [])[:2]:
            lines.append(f"> {sig}")

    lines += [
        "",
        "━" * 22,
        "先發ERA+近況 · 牛棚疲勞 · 打線wRC+ · 主客場勝率",
        "傷兵分級 · 天氣 · 球場PF · 對戰紀錄 · Kelly下注(25%)",
        f"📡 場中分析: 執行 Live Monitor 取得即時推薦",
    ]

    try:
        requests.post(DISCORD_URL, json={"content": "\n".join(lines)}, timeout=8)
        log.info("Discord sent (%d picks)", len(picks))
    except Exception as e:
        log.warning("Discord: %s", e)

# ── Main ───────────────────────────────────────────────────────────────────

def main():
    now_tw = datetime.datetime.now(TW)
    today     = now_tw.date()
    today_str = str(today)
    log.info("CPBL Bot — %s  demo=%s", today, DEMO_MODE)

    elo     = ELOSystem()
    model   = PredictionModel(elo)
    scraper = CPBLScraper()
    fetcher = OddsFetcher()

    # 1. Schedule
    if DEMO_MODE:
        games = mock.get_today_games(today)
        log.info("Demo: %d games", len(games))
    else:
        try:
            games = scraper.fetch_schedule(today)
            if not games: raise ValueError("empty")
            log.info("Scraped %d games", len(games))
        except Exception as e:
            log.warning("Scraper failed (%s), using mock", e)
            games = mock.get_today_games(today)

    # 2. Odds
    if DEMO_MODE:
        all_odds = {f"{g['away']}-{g['home']}": MOCK_ODDS.get(f"{g['away']}-{g['home']}", {}) for g in games}
    else:
        try:
            all_odds = fetcher.fetch_all()
            log.info("Odds: %d games", len(all_odds))
        except Exception as e:
            log.warning("Odds failed: %s", e)
            all_odds = {}

    # 3. Predict + generate picks
    picks      = []
    game_preds = {}

    for g in games:
        away, home = g.get("away", ""), g.get("home", "")
        if not (away and home): continue

        odds    = all_odds.get(f"{away}-{home}", {})
        weather = None
        if not DEMO_MODE:
            try:
                weather = scraper.fetch_weather(g.get("venue", ""))
            except Exception:
                pass

        pred = model.predict(g, weather, odds)
        if not pred: continue

        hp   = pred["home_win_prob"]
        ap   = pred["away_win_prob"]
        conf = pred["confidence"] / 100.0
        of   = pred.get("factors", {}).get("odds", {}) or {}
        h_odds = float(of.get("curr_home_odds") or 0)
        a_odds = float(of.get("curr_away_odds") or 0)

        game_preds[f"{home}|{away}"] = {
            "home_win_prob": round(hp, 3),
            "market_total":  float(of.get("total_line") or 8.5),
        }

        # Pitcher data with name included
        ap_name = g.get("away_pitcher") or ""
        hp_name = g.get("home_pitcher") or ""
        asp_data = {**PITCHERS.get(ap_name, {}), "name": ap_name} if ap_name else {}
        hsp_data = {**PITCHERS.get(hp_name, {}), "name": hp_name} if hp_name else {}

        base = dict(
            away=away, home=home,
            away_cn=g.get("away_name", away),
            home_cn=g.get("home_name", home),
            game_date=today_str,
            game_time=g.get("time", ""),
            time=g.get("time", ""),
            venue=g.get("venue", ""),
            home_win_prob=round(hp, 3),
            away_win_prob=round(ap, 3),
            away_sp=asp_data,
            home_sp=hsp_data,
            market_home_prob=float(of.get("market_home_prob") or 0),
            value_gap=float((of.get("analysis") or {}).get("value_gap", 0)),
            curr_home_odds=h_odds,
            curr_away_odds=a_odds,
            market_total=float(of.get("total_line") or 8.5),
            signals=of.get("signals", []),
            factors={k: round(float(v), 3) for k, v in pred.get("factors", {}).items()
                     if isinstance(v, (int, float))},
        )

        for p_win, dec_odds, label, team_name in [
            (hp, h_odds, f"{g.get('home_name', home)} 獨贏", "ML"),
            (ap, a_odds, f"{g.get('away_name', away)} 獨贏", "ML"),
        ]:
            if dec_odds > 1.0:
                e_val = calc_edge(p_win, dec_odds)
                if e_val >= EDGE_MIN and conf >= CONF_MIN:
                    picks.append({**base,
                        "btype": "ML",
                        "bet_label": label,
                        "bp": round(dec_odds, 2),
                        "stake": kelly_stake(p_win, dec_odds),
                        "edge": round(e_val, 4),
                        "conf": round(conf, 3),
                        "tier": get_tier(conf),
                    })

    picks.sort(key=lambda x: x["edge"], reverse=True)
    log.info("Picks: %d from %d games", len(picks), len(games))

    # 4. Preserve existing live_games
    existing = {}
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    # 5. Gist history
    gid, history = load_gist()
    today_str    = str(today)
    known_dates  = {r.get("date") for r in history}
    if picks and today_str not in known_dates:
        for p in picks:
            history.append({
                "date": today_str, "home": p["home"], "away": p["away"],
                "bet_type": p["btype"], "bet_label": p["bet_label"],
                "bp": p["bp"], "stake": p["stake"],
                "edge": p["edge"], "conf": p["conf"], "result": None,
            })
        save_gist(gid, history)

    recent = [r for r in history if r.get("result") is not None][-30:]

    # 6. Write picks_latest.json
    os.makedirs("docs", exist_ok=True)
    out = {
        "generated_at":   now_tw.strftime("%Y-%m-%d %H:%M") + " (台灣時間)",
        "game_date":      today_str,
        "picks":          picks,
        "live_games":     existing.get("live_games", []),
        "live_updated_at": existing.get("live_updated_at", ""),
        "live_updated_ts": existing.get("live_updated_ts", 0),
        "recent_history": recent,
        "game_preds":     game_preds,
        "demo_mode":      DEMO_MODE,
    }
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    log.info("Saved %s (%d picks)", JSON_PATH, len(picks))

    # 7. Discord
    send_discord(picks, today_str, history)


if __name__ == "__main__":
    main()
