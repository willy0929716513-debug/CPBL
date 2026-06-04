#!/usr/bin/env python3
"""CPBL Protector Bot V7 — ML + ELO + Market + RL Memory + Monte Carlo"""
import os, json, logging, datetime, requests, sys, copy
sys.path.insert(0, ".")

from cpbl.scraper import CPBLScraper
from cpbl.elo import ELOSystem
from cpbl.predictor import PredictionModel
from cpbl.odds import OddsFetcher, MOCK_ODDS
import cpbl.mock_data as mock
from cpbl.mock_data import PITCHERS, VENUE_FACTORS, TEAM_DEFAULT_SP
import cpbl.memory as mem_module
import cpbl.agent as agent_module
import cpbl.simulator as simulator

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
EDGE_MIN    = 0.03 if DEMO_MODE else 0.05
CONF_MIN    = 0.55

# ── Helpers (kept for compat; agent_module is authoritative for picks) ───────

def kelly_stake(p_win, dec_odds):
    return agent_module.kelly_stake(p_win, dec_odds)

def calc_edge(p_model, dec_odds):
    return agent_module.calc_edge(p_model, dec_odds)

def get_tier(conf):
    return agent_module.get_tier(conf)

TIER_EMOJI = agent_module.TIER_EMOJI

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

def send_discord_no_games(game_date, reason="無法取得一軍賽程"):
    if not DISCORD_URL: return
    now_tw   = datetime.datetime.now(TW)
    time_str = now_tw.strftime("%m/%d %H:%M")
    msg = (
        f"⚾ **CPBL Bot** {game_date}\n"
        f"🕐 {time_str} (台灣時間)\n"
        f"ℹ️ 今日無推薦：{reason}"
    )
    try:
        requests.post(DISCORD_URL, json={"content": msg}, timeout=8)
    except Exception as e:
        log.warning("Discord no-games: %s", e)


def send_discord(picks, all_preds, game_date, history=None, memory=None):
    if not DISCORD_URL or not all_preds: return
    now_tw   = datetime.datetime.now(TW)
    time_str = now_tw.strftime("%m/%d %H:%M")

    hist_str = "尚無歷史記錄"
    if history:
        settled = [h for h in history if h.get("result") is not None]
        if settled:
            wins = sum(1 for h in settled if h["result"] == "W")
            ml_rec  = [h for h in settled if h.get("bet_type") == "ML"]
            rl_rec  = [h for h in settled if h.get("bet_type") == "RL"]
            tot_rec = [h for h in settled if h.get("bet_type") in ("TOT",)]
            def wr(lst): return f"{sum(1 for x in lst if x['result']=='W')}/{len(lst)}" if lst else ""
            parts = [f"{wins}勝/{len(settled)}場 ({wins/len(settled)*100:.0f}%)"]
            if ml_rec:  parts.append(f"ML {wr(ml_rec)}")
            if rl_rec:  parts.append(f"RL {wr(rl_rec)}")
            if tot_rec: parts.append(f"TOT {wr(tot_rec)}")
            hist_str = "  ".join(parts)

    TIER_LABEL = agent_module.TIER_LABEL

    # V7 記憶摘要
    mem_line = ""
    if memory and memory.get("total_games", 0) > 0:
        acc = mem_module.accuracy(memory)
        roi = memory.get("roi_units", 0.0)
        mem_line = (
            f"\n🧠 V7 RL: {memory['total_games']}局 "
            f"準確率{acc*100:.0f}% ROI{roi:+.1f}u | "
            f"連{'✅' if memory.get('streak_correct',0) > memory.get('streak_wrong',0) else '❌'}"
            f"{max(memory.get('streak_correct',0), memory.get('streak_wrong',0))}"
        )

    rec_count = len(picks)
    lines = [
        "⚾ **CPBL V7 分析報告**",
        f"🕐 {time_str} (台灣時間) | ✅賽程 ✅盤口 ✅傷兵 ✅近況 ✅MC ✅RL",
        f"📊 歷史: {hist_str}{mem_line}",
        "",
        f"**今日 {len(all_preds)} 場賽事 — {'推薦 ' + str(rec_count) + ' 場下注' if rec_count else '今日無推薦下注'}**",
    ]

    def fmt_sp(pitcher: dict) -> str:
        name = pitcher.get("name", "")
        if not name: return "TBD"
        tag = "🌏" if pitcher.get("foreign") else ""
        era = pitcher.get("era", "?")
        r3  = pitcher.get("recent_3_era", era)
        k9  = pitcher.get("k9", "?")
        return f"{tag}{name}(ERA {era} 近3場ERA {r3} K/9:{k9})"

    # ── 推薦下注的場次 ──
    pick_keys = {(p["away"], p["home"]) for p in picks}
    for p in picks:
        asp = p.get("away_sp") or {}
        hsp = p.get("home_sp") or {}
        vf        = VENUE_FACTORS.get(p.get("venue", ""), {})
        pf_str    = f" PF{vf.get('run_factor',1.0):.2f}" if vf else ""
        venue_tag = f"🏟️{p.get('venue','')}{pf_str}" if p.get("venue") else ""
        g_time    = p.get("game_time", p.get("time", ""))
        hw        = round(p.get("home_win_prob", 0.5) * 100, 1)
        aw        = round(p.get("away_win_prob", 0.5) * 100, 1)
        market    = round(p.get("market_home_prob", 0), 1)
        be_pct    = round(100.0 / p["bp"], 1) if p.get("bp", 0) > 1 else "?"
        total     = p.get("market_total", "")
        lines += [
            "",
            f"**{TIER_LABEL.get(p['tier'],'⭐ 穩定')}  {p['away_cn']} @ {p['home_cn']}**",
            f"🗓️ {game_date} {g_time} {venue_tag}",
            f"⚾ 先發: {fmt_sp(asp)} — {fmt_sp(hsp)}",
            f"💰 推薦: `{p['bet_label']}` @ **{p['bp']}**",
            f"> 勝率: 客 {aw}% vs 主 {hw}% | 市場主隊: {market}% | 盈虧平衡: {be_pct}%",
            f"> Edge: **{p['edge']*100:+.1f}%** 信心{p['conf']*100:.0f}% | Kelly: ${p['stake']:.0f}",
        ]
        if total:
            lines.append(f"> 大小分: {total}")
        mc_p = p.get("mc") or {}
        if mc_p.get("std_dev") is not None:
            ci = mc_p.get("ci_90", [0, 1])
            lines.append(
                f"> 🎲 MC {mc_p.get('n','?')}次: "
                f"90%CI [{ci[0]*100:.0f}%,{ci[1]*100:.0f}%] "
                f"σ={mc_p['std_dev']:.3f}"
            )
        for sig in (p.get("signals") or [])[:2]:
            lines.append(f"> {sig}")
        for reason in (p.get("reasoning") or [])[:1]:
            lines.append(f"> {reason}")

    # ── 僅供參考（不推薦）的場次 ──
    ref_preds = [pr for pr in all_preds if not pr.get("recommended")]
    if ref_preds:
        lines += ["", "━" * 18, "📊 **今日其他比賽（僅供參考，不建議下注）**"]
        for pr in ref_preds:
            asp = pr.get("away_sp") or {}
            hsp = pr.get("home_sp") or {}
            g_time = pr.get("game_time", pr.get("time", ""))
            hw = round(pr.get("home_win_prob", 0.5) * 100, 1)
            aw = round(pr.get("away_win_prob", 0.5) * 100, 1)
            # 決定優勢方
            if hw >= aw:
                adv = f"主隊 **{pr['home_cn']}** 勝算略高 ({hw}% vs {aw}%)"
            else:
                adv = f"客隊 **{pr['away_cn']}** 勝算略高 ({aw}% vs {hw}%)"
            vf  = VENUE_FACTORS.get(pr.get("venue", ""), {})
            vt  = f"🏟️{pr.get('venue','')}" if pr.get("venue") else ""
            mc_pr = pr.get("mc") or {}
            mc_str = ""
            if mc_pr.get("uncertain"):
                mc_str = " ⚠️高波動"
            elif mc_pr.get("std_dev"):
                mc_str = f" σ={mc_pr['std_dev']:.3f}"
            lines += [
                "",
                f"**{pr['away_cn']} @ {pr['home_cn']}**  🗓️ {g_time} {vt}",
                f"⚾ 先發: {fmt_sp(asp)} — {fmt_sp(hsp)}",
                f"> {adv}{mc_str}",
                f"> ⚠️ 差距不足或波動過大，不建議下注",
            ]

    lines += [
        "",
        "━" * 22,
        "V7: ELO + 9因子 · MC模擬 · RL自適應 · Kelly(25%)",
        "先發ERA · 牛棚疲勞 · 打線wRC+ · 主客場 · 天氣 · 球場PF",
        f"📡 場中分析: 執行 Live Monitor 取得即時推薦",
    ]

    try:
        requests.post(DISCORD_URL, json={"content": "\n".join(lines)}, timeout=8)
        log.info("Discord sent (%d picks, %d predictions)", len(picks), len(all_preds))
    except Exception as e:
        log.warning("Discord: %s", e)

# ── Main ───────────────────────────────────────────────────────────────────

def _update_memory_from_history(memory: dict, history: list) -> int:
    """從 Gist 已結算記錄更新 RL 記憶（每次只處理新增的已結算場次）。"""
    processed = set(memory.get("_processed_keys", []))
    updated = 0
    for rec in history:
        if rec.get("result") is None:
            continue
        key = f"{rec.get('date')}_{rec.get('home')}_{rec.get('away')}"
        if key in processed:
            continue
        result_win = rec["result"] == "W"
        bet_label  = rec.get("bet_label", "")
        # 從 bet_label 判斷預測方向（"XX 獨贏"）
        home_cn = rec.get("home", "")
        pred_home_win = home_cn in bet_label
        conf = float(rec.get("conf", 0.6))
        edge = float(rec.get("edge", 0.0))
        # 沒有 factors 資料，用空 dict（只更新基本 accuracy）
        memory = mem_module.update(
            memory,
            actual_home_win=result_win if pred_home_win else not result_win,
            predicted_home_win=pred_home_win,
            conf=conf,
            factors={},
            edge=edge,
        )
        processed.add(key)
        updated += 1
    memory["_processed_keys"] = list(processed)[-500:]  # 最多保留 500 筆，防止過大
    return updated


def main():
    now_tw = datetime.datetime.now(TW)
    today     = now_tw.date()
    today_str = str(today)
    log.info("CPBL Bot V7 — %s  demo=%s", today, DEMO_MODE)

    elo     = ELOSystem()
    model   = PredictionModel(elo)
    scraper = CPBLScraper()
    fetcher = OddsFetcher()

    # ── 0. 載入 RL 記憶 ──────────────────────────────────────────────────────
    memory = mem_module.load()
    log.info("Memory: %d局 準確率%.0f%% | %s",
             memory.get("total_games", 0),
             mem_module.accuracy(memory) * 100,
             mem_module.weight_str(memory))

    # ── 1. Schedule ──────────────────────────────────────────────────────────
    if DEMO_MODE:
        games = mock.get_today_games(today)
        log.info("Demo: %d games", len(games))
    else:
        games = []
        try:
            games = scraper.fetch_schedule(today)
            if not games:
                raise ValueError("no games parsed from scraper")
            log.info("Scraped %d 一軍 games from cpbl.com.tw", len(games))
        except Exception as e:
            log.warning("Scraper failed (%s)", e)

        if not games:
            sched_path = os.path.join(os.path.dirname(__file__), "data", "schedule.json")
            try:
                with open(sched_path, encoding="utf-8") as f:
                    sched = json.load(f)
                games = [
                    {**g, "league": "A"}
                    for g in sched.get("games", [])
                    if g.get("date") == today_str
                    and g.get("away") and g.get("home")
                    and g.get("status") not in ("休兵日", "輪休")
                ]
                if games:
                    log.info("Schedule file: %d games for %s", len(games), today_str)
                else:
                    log.info("Schedule file: no games for %s", today_str)
            except Exception as ef:
                log.warning("Schedule file read failed (%s)", ef)

    # ── 2. 投手成績（即時 → 快取 → mock）────────────────────────────────────
    pitcher_cache_path = os.path.join(os.path.dirname(__file__), "data", "pitcher_stats.json")
    merged_pitchers = copy.deepcopy(PITCHERS)

    if not DEMO_MODE:
        live_stats = {}
        try:
            live_stats = scraper.fetch_pitcher_stats(today.year)
        except Exception as e:
            log.warning("Live pitcher stats: %s", e)

        if not live_stats and os.path.exists(pitcher_cache_path):
            try:
                with open(pitcher_cache_path, encoding="utf-8") as f:
                    cache = json.load(f)
                live_stats = cache.get("stats", {})
                log.info("Pitcher stats: from cache (%s)", cache.get("updated_at", "?"))
            except Exception:
                pass

        updated_cnt = 0
        for name, live in live_stats.items():
            if name in merged_pitchers:
                for k, v in live.items():
                    if isinstance(v, (int, float)):
                        merged_pitchers[name][k] = v
                updated_cnt += 1
        if updated_cnt:
            log.info("Pitcher stats: %d players updated with live data", updated_cnt)
            try:
                os.makedirs(os.path.dirname(pitcher_cache_path), exist_ok=True)
                with open(pitcher_cache_path, "w", encoding="utf-8") as f:
                    json.dump({"updated_at": now_tw.strftime("%Y-%m-%d %H:%M"),
                               "year": today.year, "stats": live_stats},
                              f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    # ── 3. Odds ──────────────────────────────────────────────────────────────
    if DEMO_MODE:
        all_odds = {f"{g['away']}-{g['home']}": MOCK_ODDS.get(f"{g['away']}-{g['home']}", {}) for g in games}
    else:
        try:
            all_odds = fetcher.fetch_all()
            log.info("Odds: %d games", len(all_odds))
        except Exception as e:
            log.warning("Odds failed: %s", e)
            all_odds = {}

    # ── 4. Predict + Monte Carlo + Agent Decision ─────────────────────────────
    picks     = []
    all_preds = []
    game_preds: dict = {}
    MC_N = 200 if DEMO_MODE else 2000   # Demo 省時間用 200次

    for g in games:
        away, home = g.get("away", ""), g.get("home", "")
        if not (away and home):
            continue

        odds    = all_odds.get(f"{away}-{home}", {})
        weather = None
        if not DEMO_MODE:
            try:
                weather = scraper.fetch_weather(g.get("venue", ""))
            except Exception:
                pass

        ap_name = g.get("away_pitcher") or TEAM_DEFAULT_SP.get(away, "")
        hp_name = g.get("home_pitcher") or TEAM_DEFAULT_SP.get(home, "")
        g_for_pred = {**g, "away_pitcher": ap_name, "home_pitcher": hp_name}

        pred = model.predict(g_for_pred, weather, odds,
                             pitchers=merged_pitchers, memory=memory)
        if not pred:
            continue

        # ── Monte Carlo 模擬 ──
        mc = simulator.simulate(pred, n=MC_N)
        log.info("MC %s@%s: mean=%.3f std=%.3f ci=[%.3f,%.3f] uncertain=%s",
                 away, home, mc["mean_prob"], mc["std_dev"],
                 mc["ci_90"][0], mc["ci_90"][1], mc["uncertain"])

        hp   = pred["home_win_prob"]
        ap   = pred["away_win_prob"]
        conf = pred["confidence"] / 100.0
        of   = pred.get("factors", {}).get("odds", {}) or {}
        h_odds = float(of.get("curr_home_odds") or 0)
        a_odds = float(of.get("curr_away_odds") or 0)

        game_preds[f"{home}|{away}"] = {
            "home_win_prob": round(hp, 3),
            "market_total":  float(of.get("total_line") or 8.5),
            "mc_mean":       mc["mean_prob"],
            "mc_std":        mc["std_dev"],
        }

        asp_data = {**merged_pitchers.get(ap_name, {}), "name": ap_name} if ap_name else {}
        hsp_data = {**merged_pitchers.get(hp_name, {}), "name": hp_name} if hp_name else {}

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
            factors=pred.get("factors", {}),
            mc=mc,
        )

        # ── V7 Decision Agent ──
        decision = agent_module.decide(g_for_pred, pred, mc=mc, demo_mode=DEMO_MODE)
        best_pick = None
        if decision:
            pick = {**base, **decision}
            picks.append(pick)
            best_pick = pick

        # ── 參考方向（無論是否推薦都記錄）──
        if hp >= ap:
            ref_label = f"{g.get('home_name', home)} 勝算較高"
            ref_prob  = round(hp * 100, 1)
            ref_odds  = h_odds
        else:
            ref_label = f"{g.get('away_name', away)} 勝算較高"
            ref_prob  = round(ap * 100, 1)
            ref_odds  = a_odds

        ref_edge = calc_edge(max(hp, ap), ref_odds) if ref_odds > 1 else 0
        adj_conf = round(min(0.95, conf + mc.get("conf_boost", 0.0)), 3)

        all_preds.append({**base,
            "ref_label":   ref_label,
            "ref_prob":    ref_prob,
            "ref_odds":    round(ref_odds, 2),
            "ref_edge":    round(ref_edge, 4),
            "conf":        adj_conf,
            "tier":        get_tier(adj_conf),
            "recommended": best_pick is not None,
        })

    picks.sort(key=lambda x: x["edge"], reverse=True)
    all_preds.sort(key=lambda x: (not x["recommended"], -abs(x["home_win_prob"] - 0.5)))
    log.info("Picks: %d from %d games", len(picks), len(games))

    # ── 5. Gist history + RL 更新 ────────────────────────────────────────────
    gid, history = load_gist()
    today_str = str(today)

    # 用已結算記錄更新 RL 記憶
    mem_updated = _update_memory_from_history(memory, history)
    if mem_updated:
        log.info("Memory: updated from %d settled records", mem_updated)
        mem_module.save(memory)

    # 寫入今日下注記錄（若尚未存在）
    known_dates = {r.get("date") for r in history}
    if picks and today_str not in known_dates:
        for p in picks:
            history.append({
                "date": today_str, "home": p["home"], "away": p["away"],
                "bet_type": p.get("btype", "ML"), "bet_label": p["bet_label"],
                "bp": p["bp"], "stake": p["stake"],
                "edge": p["edge"], "conf": p["conf"],
                "mc_std": p.get("mc", {}).get("std_dev"),
                "result": None,
            })
        save_gist(gid, history)

    recent = [r for r in history if r.get("result") is not None][-30:]

    # ── 6. Write picks_latest.json ───────────────────────────────────────────
    existing = {}
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    os.makedirs("docs", exist_ok=True)
    out = {
        "generated_at":    now_tw.strftime("%Y-%m-%d %H:%M") + " (台灣時間)",
        "game_date":       today_str,
        "picks":           picks,
        "predictions":     all_preds,
        "live_games":      existing.get("live_games", []),
        "live_updated_at": existing.get("live_updated_at", ""),
        "live_updated_ts": existing.get("live_updated_ts", 0),
        "recent_history":  recent,
        "game_preds":      game_preds,
        "demo_mode":       DEMO_MODE,
        "v7_memory": {
            "total_games":    memory.get("total_games", 0),
            "accuracy":       round(mem_module.accuracy(memory), 3),
            "roi_units":      memory.get("roi_units", 0.0),
            "weights":        mem_module.weight_str(memory),
            "calibration":    mem_module.calibration_str(memory),
            "streak_correct": memory.get("streak_correct", 0),
            "streak_wrong":   memory.get("streak_wrong", 0),
        },
    }
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    log.info("Saved %s (%d picks, %d predictions)", JSON_PATH, len(picks), len(all_preds))

    # ── 7. Discord ───────────────────────────────────────────────────────────
    if all_preds:
        send_discord(picks, all_preds, today_str, history, memory)
    elif not games and not DEMO_MODE:
        send_discord_no_games(today_str, "今日無賽事（備份日程未填或真的休兵）")


if __name__ == "__main__":
    main()
