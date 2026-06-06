#!/usr/bin/env python3
"""NPB/KBO Protector Bot V8 — Ensemble + CLV + Feature Store + Bayesian + Market Move"""
import os, json, logging, datetime, requests, sys, copy
sys.path.insert(0, ".")

from cpbl.scraper import MultiLeagueScraper as CPBLScraper
from cpbl.elo import ELOSystem
from cpbl.predictor import PredictionModel
from cpbl.odds import OddsFetcher, MOCK_ODDS
import cpbl.mock_data as mock
from cpbl.mock_data import PITCHERS, VENUE_FACTORS, TEAM_DEFAULT_SP, TEAM_INFO
import cpbl.memory        as mem_module
import cpbl.agent         as agent_module
import cpbl.simulator     as simulator
import cpbl.ensemble      as ensemble_module
import cpbl.matchup       as matchup_module
import cpbl.feature_store as fs_module
import cpbl.market        as market_module
import cpbl.clv           as clv_module
import cpbl.bayesian      as bayesian_module
import cpbl.stats_scraper as stats_scraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cpbl_bot")

TW = datetime.timezone(datetime.timedelta(hours=8))


def _game_ended(game: dict, now_tw: datetime.datetime) -> bool:
    """Returns True if this game has very likely ended (start + 3h30m elapsed)."""
    date_str = (game.get("date") or "").strip()
    if not date_str:
        return False
    try:
        game_date = datetime.date.fromisoformat(date_str)
        # 日期比今天早 → 一定結束了
        if game_date < now_tw.date():
            return True
        # 今天的比賽：依開始時間判斷（NPB 18:00 JST = 17:00 TW，KBO 약 16:00 TW）
        time_str = (game.get("time") or "").strip()
        if time_str and ":" in time_str:
            parts = time_str.split(":")
            h, m = int(parts[0]), int(parts[1])
        else:
            # 無時間資料：用最保守估計（17:00 TW = 18:00 JST/KST）
            # 讓比賽在 20:30 TW 之後自動過濾
            h, m = 17, 0
        start = datetime.datetime(
            game_date.year, game_date.month, game_date.day, h, m, tzinfo=TW
        )
        return now_tw >= start + datetime.timedelta(hours=3, minutes=30)
    except (ValueError, TypeError):
        return now_tw.hour >= 22


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

def send_discord_no_games(game_date, reason="無法取得今日賽程"):
    if not DISCORD_URL: return
    now_tw   = datetime.datetime.now(TW)
    time_str = now_tw.strftime("%m/%d %H:%M")
    msg = (
        f"⚾ **NPB/KBO Bot** {game_date}\n"
        f"🕐 {time_str} (台灣時間)\n"
        f"ℹ️ 今日無推薦：{reason}"
    )
    try:
        r = requests.post(DISCORD_URL, json={"content": msg}, timeout=8)
        if r.status_code not in (200, 204):
            log.warning("Discord no-games HTTP %s: %s", r.status_code, r.text[:200])
    except Exception as e:
        log.warning("Discord no-games: %s", e)


def _discord_post(content: str):
    """Discord webhook 發送，自動處理 2000 字元上限分段。"""
    LIMIT = 1900
    chunks = []
    if len(content) <= LIMIT:
        chunks = [content]
    else:
        # 按換行切，每段不超過 LIMIT
        current = []
        current_len = 0
        for line in content.split("\n"):
            if current_len + len(line) + 1 > LIMIT and current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            current.append(line)
            current_len += len(line) + 1
        if current:
            chunks.append("\n".join(current))

    for chunk in chunks:
        try:
            r = requests.post(DISCORD_URL, json={"content": chunk}, timeout=8)
            if r.status_code not in (200, 204):
                log.warning("Discord HTTP %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            log.warning("Discord: %s", e)


def send_discord(picks, all_preds, game_date, history=None, memory=None):
    if not DISCORD_URL or not all_preds:
        return
    now_tw    = datetime.datetime.now(TW)
    time_str  = now_tw.strftime("%m/%d %H:%M")
    rec_count = len(picks)

    TIER_LABEL = agent_module.TIER_LABEL
    pick_map   = {(p["away"], p["home"]): p for p in picks}

    lines = [
        f"⚾ **NPB/KBO {game_date} 賽前分析**",
        f"🕐 {time_str} 台灣時間 | 共 {len(all_preds)} 場"
        + (f" | **推薦 {rec_count} 場下注**" if rec_count else ""),
        "",
    ]

    def fmt_sp(sp: dict) -> str:
        if not sp:
            return "未定"
        name = sp.get("name", "")
        if not name:
            return "未定"
        era = sp.get("era")
        k9  = sp.get("k9")
        fip = sp.get("fip")
        stats_parts = []
        if era is not None:
            stats_parts.append(f"ERA {era:.2f}")
        if k9 is not None:
            stats_parts.append(f"K/9 {k9:.1f}")
        if fip is not None and era is not None and abs(fip - era) > 0.3:
            stats_parts.append(f"FIP {fip:.2f}")
        return f"{name} ({' '.join(stats_parts)})" if stats_parts else name

    def factor_tags(pr: dict) -> str:
        """從各因子生成優劣標籤，如 先發▲客 | 打線▲主 | 牛棚▲客"""
        factors = pr.get("factors", {})
        away_cn = pr.get("away_cn", pr.get("away", "客"))
        home_cn = pr.get("home_cn", pr.get("home", "主"))
        tags = []
        FACTOR_MAP = [
            ("starter",     "先發"),
            ("lineup",      "打線"),
            ("bullpen",     "牛棚"),
            ("recent_form", "近況"),
            ("home_away",   "主客場"),
            ("h2h",         "對戰"),
        ]
        for key, label in FACTOR_MAP:
            f = factors.get(key, {})
            adv = f.get("advantage", 0)
            if adv > 3:
                tags.append(f"{label}▲{home_cn}")
            elif adv < -3:
                tags.append(f"{label}▲{away_cn}")
        return " | ".join(tags) if tags else "各項相近"

    def _make_date_tag(d_str):
        try:
            gd = datetime.date.fromisoformat(str(d_str))
            return f"📅 {gd.month:02d}/{gd.day:02d}"
        except Exception:
            return f"📅 {str(d_str)[5:].replace('-', '/')}"

    for pr in all_preds:
        away    = pr["away"]
        home    = pr["home"]
        away_cn = pr.get("away_cn", away)
        home_cn = pr.get("home_cn", home)
        hw      = round(pr.get("home_win_prob", 0.5) * 100, 1)
        aw      = round(pr.get("away_win_prob", 0.5) * 100, 1)
        g_time  = pr.get("game_time", pr.get("time", ""))
        league  = pr.get("league", TEAM_INFO.get(home, {}).get("league", ""))
        flag    = "🇯🇵" if league == "NPB" else "🇰🇷" if league == "KBO" else "⚾"
        _date_tag = _make_date_tag(pr.get("game_date") or game_date)
        time_tag = (_date_tag + (f" 🕐 {g_time}" if g_time else ""))

        # ── 先發投手 ──
        asp = pr.get("away_sp") or {}
        hsp = pr.get("home_sp") or {}
        asp_str = fmt_sp(asp)
        hsp_str = fmt_sp(hsp)

        # ── 市場賠率與 edge ──
        of        = pr.get("factors", {}).get("odds", {})
        h_odds    = float(of.get("curr_home_odds") or pr.get("curr_home_odds") or 0)
        a_odds    = float(of.get("curr_away_odds") or pr.get("curr_away_odds") or 0)
        mkt_home  = float(of.get("market_home_prob") or 0)  # 已是 % 值

        # Edge = 模型勝率 − 市場隱含勝率（完全獨立計算）
        edge_home = hw - mkt_home  # + 表示模型比市場更看好主隊
        edge_away = aw - (100.0 - mkt_home)

        def odds_fmt(o: float) -> str:
            return f"{o:.2f}" if o > 1 else "–"

        def mkt_str() -> str:
            if mkt_home > 0:
                return f"市場：主 {mkt_home:.1f}% ({odds_fmt(h_odds)}) / 客 {100-mkt_home:.1f}% ({odds_fmt(a_odds)})"
            return "市場：無賠率"

        ftags = factor_tags(pr)

        if (away, home) in pick_map:
            p    = pick_map[(away, home)]
            tier = TIER_LABEL.get(p["tier"], "⭐ 穩定")
            be   = round(100.0 / p["bp"], 1) if p.get("bp", 0) > 1 else "?"
            side_cn = home_cn if p["side"] == "home" else away_cn
            edge_val = p["edge"] * 100

            lines += [
                f"{flag} **{away_cn} @ {home_cn}**  {time_tag}",
                f"  先發：客 {asp_str}  vs  主 {hsp_str}",
                f"  優勢：{ftags}",
                f"  🎯 模型：客 **{aw}%** / 主 **{hw}%**",
                f"  📊 {mkt_str()}",
                f"  ⚡ Edge：{side_cn} `{edge_val:+.1f}%`  →  {tier} 💰 `{p['bet_label']}` @ **{p['bp']}**  BEP {be}%",
                "",
            ]
        else:
            # 無推薦：仍顯示完整分析
            if hw >= aw:
                model_verdict = f"主 **{home_cn}** {hw}%  >  客 {away_cn} {aw}%"
                edge_show = f"主隊 {edge_home:+.1f}%"
            else:
                model_verdict = f"客 **{away_cn}** {aw}%  >  主 {home_cn} {hw}%"
                edge_show = f"客隊 {edge_away:+.1f}%"

            lines += [
                f"{flag} {away_cn} @ {home_cn}  {time_tag}",
                f"  先發：客 {asp_str}  vs  主 {hsp_str}",
                f"  優勢：{ftags}",
                f"  🎯 模型：{model_verdict}",
                f"  📊 {mkt_str()}  Edge {edge_show}（不推薦）",
                "",
            ]

    if history:
        settled = [h for h in history if h.get("result") is not None]
        if settled:
            wins = sum(1 for h in settled if h["result"] == "W")
            lines += [
                f"📊 歷史: {wins}勝/{len(settled)}場 ({wins/len(settled)*100:.0f}%)",
            ]

    _discord_post("\n".join(lines))
    log.info("Discord sent (%d picks, %d predictions)", len(picks), len(all_preds))

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
    log.info("CPBL Bot V8 — %s  demo=%s", today, DEMO_MODE)

    elo     = ELOSystem()
    model   = PredictionModel(elo)
    scraper = CPBLScraper()
    fetcher = OddsFetcher()

    # ── 0. 載入 RL 記憶 + V8 Feature Store + CLV + Market Moves ────────────
    memory        = mem_module.load()
    feature_store = fs_module.load()
    clv_records   = clv_module.load()
    market_data   = market_module.load()
    log.info("Memory: %d局 準確率%.0f%% rolling50=%.0f%% | %s",
             memory.get("total_games", 0),
             mem_module.accuracy(memory) * 100,
             mem_module.rolling_accuracy(memory) * 100,
             mem_module.weight_str(memory))
    clv_sum = clv_module.summary(clv_records)
    if clv_sum["n"] > 0:
        log.info("CLV: n=%d avg=%.3f pos_pct=%.0f%% corr=%.2f",
                 clv_sum["n"], clv_sum["avg_clv"],
                 clv_sum["positive_clv_pct"] * 100,
                 clv_sum["clv_win_corr"])

    # ── 1. Schedule ──────────────────────────────────────────────────────────
    if DEMO_MODE:
        games = mock.get_today_games(today)
        log.info("Demo: %d games", len(games))
    else:
        games = []

        # 1a. 多來源賽程：ESPN → ESPN Web → MLB Stats → Odds API /events
        try:
            games = stats_scraper.fetch_schedule_multi(
                today, odds_api_key=os.environ.get("ODDS_API_KEY", "")
            )
        except Exception as e:
            log.warning("Schedule fetch failed: %s", e)

        # 1b. 備援：schedule.json（由 update_data workflow 自動維護 NPB/KBO 賽程）
        if not games:
            sched_path = os.path.join(os.path.dirname(__file__), "data", "schedule.json")
            try:
                with open(sched_path, encoding="utf-8") as f:
                    sched = json.load(f)
                games = [
                    g
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

    # ── 2. 投手成績（ESPN → CPBL官網 → 快取 → mock）──────────────────────────
    pitcher_cache_path = os.path.join(os.path.dirname(__file__), "data", "pitcher_stats.json")
    merged_pitchers = copy.deepcopy(PITCHERS)
    # 確保所有 mock 投手都有衍生指標
    for p in merged_pitchers.values():
        stats_scraper.enrich_pitcher(p)

    if not DEMO_MODE:
        live_stats = {}

        # 2a. 多來源抓取（ESPN + CPBL 官網）
        try:
            live_stats = stats_scraper.fetch_all_pitcher_stats(today.year)
            log.info("Live pitcher stats: %d players (multi-source)", len(live_stats))
        except Exception as e:
            log.warning("Multi-source pitcher stats failed: %s", e)

        # 2b. 退回快取
        if not live_stats and os.path.exists(pitcher_cache_path):
            try:
                with open(pitcher_cache_path, encoding="utf-8") as f:
                    cache = json.load(f)
                live_stats = cache.get("stats", {})
                log.info("Pitcher stats: from cache (%s)", cache.get("updated_at", "?"))
            except Exception:
                pass

        # 2c. 合併到 mock（real data > mock fallback）
        updated_cnt = 0
        for name, live in live_stats.items():
            if name not in merged_pitchers:
                merged_pitchers[name] = {}
            for k, v in live.items():
                if isinstance(v, (int, float)):
                    merged_pitchers[name][k] = v
            stats_scraper.enrich_pitcher(merged_pitchers[name])
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
            all_odds = fetcher.fetch_all(game_date=today_str)
            log.info("Odds: %d games", len(all_odds))
        except Exception as e:
            log.warning("Odds failed: %s", e)
            all_odds = {}

    # ── 4. Predict + Monte Carlo + Agent Decision ─────────────────────────────
    picks     = []
    all_preds = []
    game_preds: dict = {}
    MC_N = 200 if DEMO_MODE else 2000   # Demo 省時間用 200次

    # Deduplicate games and validate team codes before prediction loop.
    # Removes: unknown codes, cross-league matchups, duplicate (date, away, home) entries.
    _seen: set = set()
    valid_games = []
    for g in games:
        away, home = g.get("away", ""), g.get("home", "")
        if not away or not home:
            continue
        if away not in TEAM_INFO or home not in TEAM_INFO:
            log.warning("Unknown team code %s@%s — skipped", away, home)
            continue
        if TEAM_INFO[away]["league"] != TEAM_INFO[home]["league"]:
            log.warning("Cross-league game %s(%s)@%s(%s) — skipped",
                        away, TEAM_INFO[away]["league"], home, TEAM_INFO[home]["league"])
            continue
        key = (g.get("date", ""), away, home)
        if key in _seen:
            log.debug("Duplicate %s@%s on %s — skipped", away, home, g.get("date", ""))
            continue
        _seen.add(key)
        valid_games.append(g)
    if len(valid_games) != len(games):
        log.info("Games filtered: %d → %d (removed %d bad/duplicate entries)",
                 len(games), len(valid_games), len(games) - len(valid_games))
    games = valid_games

    # Filter out games that have already ended (start + 3h30m in the past)
    active = [g for g in games if not _game_ended(g, now_tw)]
    if len(active) != len(games):
        log.info("Ended-game filter: %d → %d (dropped %d finished games)",
                 len(games), len(active), len(games) - len(active))
    games = active

    # If all today's games are done and it's evening, look ahead to tomorrow
    if not games and not DEMO_MODE and now_tw.hour >= 20:
        tomorrow = today + datetime.timedelta(days=1)
        tomorrow_str = str(tomorrow)
        log.info("All today's games ended — fetching tomorrow's schedule (%s)", tomorrow_str)
        found_tmr = False
        try:
            tmr = stats_scraper.fetch_schedule_multi(
                tomorrow, odds_api_key=os.environ.get("ODDS_API_KEY", "")
            )
            if tmr:
                games = tmr
                today_str = tomorrow_str
                found_tmr = True
                log.info("Tomorrow's schedule: %d games", len(games))
        except Exception as _e:
            log.warning("Tomorrow schedule fetch failed: %s", _e)

        if not found_tmr:
            sched_path = os.path.join(os.path.dirname(__file__), "data", "schedule.json")
            try:
                with open(sched_path, encoding="utf-8") as _f:
                    sched_d = json.load(_f)
                games = [
                    g for g in sched_d.get("games", [])
                    if g.get("date") == tomorrow_str
                    and g.get("away") and g.get("home")
                    and g.get("status") not in ("休兵日", "輪休")
                ]
                if games:
                    today_str = tomorrow_str
                    log.info("Tomorrow from schedule.json: %d games", len(games))
            except Exception as _ef:
                log.warning("Schedule file for tomorrow failed: %s", _ef)

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

        ap_confirmed = bool(g.get("away_pitcher"))
        hp_confirmed = bool(g.get("home_pitcher"))
        # 只使用已確認的先發投手；未確認則保留空字串（Discord 顯示「未定」）
        ap_name = g.get("away_pitcher") or ""
        hp_name = g.get("home_pitcher") or ""
        # 用中文隊名覆蓋 g 裡的英文名，讓 bet_label 直接顯示中文
        away_cn_name = TEAM_INFO.get(away, {}).get("name", g.get("away_name", away))
        home_cn_name = TEAM_INFO.get(home, {}).get("name", g.get("home_name", home))
        g_for_pred = {**g, "away_pitcher": ap_name, "home_pitcher": hp_name,
                      "away_name": away_cn_name, "home_name": home_cn_name}

        pred = model.predict(g_for_pred, weather, odds,
                             pitchers=merged_pitchers, memory=memory)
        if not pred:
            continue

        # ── V8 Matchup Matrix ─────────────────────────────────────────────
        mu = matchup_module.game_matchup(away, home, ap_name, hp_name)
        log.info("Matchup %s@%s: net_adv=%.1f (home_bat=%.1f away_bat=%.1f)",
                 away, home, mu["net_advantage"],
                 mu["home_bat_adv"], mu["away_bat_adv"])

        # ── V8 Feature Store 疲勞懲罰 ─────────────────────────────────────
        home_fatigue = fs_module.fatigue_penalty(feature_store, home)
        away_fatigue = fs_module.fatigue_penalty(feature_store, away)
        log.info("Fatigue %s=%.1f %s=%.1f", home, home_fatigue, away, away_fatigue)

        # ── Monte Carlo 模擬 ──────────────────────────────────────────────
        mc = simulator.simulate(pred, n=MC_N)
        log.info("MC %s@%s: mean=%.3f std=%.3f ci=[%.3f,%.3f] uncertain=%s",
                 away, home, mc["mean_prob"], mc["std_dev"],
                 mc["ci_90"][0], mc["ci_90"][1], mc["uncertain"])

        # ── V8 Market Movement Detection ──────────────────────────────────
        game_key = f"{away}@{home}_{today_str}"
        market_data = market_module.record_move(market_data, game_key, odds)
        market_sig  = market_module.analyze(market_data, game_key)
        if market_sig["signals"]:
            log.info("Market %s: %s", game_key,
                     " | ".join(market_sig["signals"]))

        # ── V8 Ensemble ───────────────────────────────────────────────────
        of       = pred.get("factors", {}).get("odds", {}) or {}
        mkt_prob = float(of.get("market_home_prob") or 0) / 100.0
        # 疲勞補正注入 ensemble 之前先調整 model_prob
        fatigue_adj = (home_fatigue - away_fatigue) * 0.008
        adj_model   = max(0.05, min(0.95, pred["home_win_prob"] + fatigue_adj
                                   + mu["net_advantage"] * 0.004))
        ens = ensemble_module.ensemble(
            elo_prob    = pred["elo_base"],
            model_prob  = adj_model,
            market_prob = mkt_prob if mkt_prob > 0 else 0.5,
            mc_mean     = mc["mean_prob"],
            mc_norm_cdf = mc.get("norm_cdf_prob"),
            memory      = memory,
        )
        log.info("Ensemble %s@%s: %.4f (ELO=%.3f ML=%.3f mkt=%.3f MC=%.3f bayes×%.2f)",
                 away, home, ens["prob"],
                 pred["elo_base"], adj_model,
                 mkt_prob, mc["mean_prob"], ens["bayesian_adj"])

        hp     = ens["prob"]
        ap     = 1.0 - hp
        conf   = pred["confidence"] / 100.0
        h_odds = float(of.get("curr_home_odds") or 0)
        a_odds = float(of.get("curr_away_odds") or 0)

        # 無真實賠率時以 ELO 為市場基準（+ 5% vig），讓 decide() 可計算 edge
        # edge = 完整模型概率 − ELO隱含概率 → 反映模型相對 ELO 的額外資訊優勢
        if h_odds <= 1.0 and a_odds <= 1.0:
            elo_h = max(0.05, min(0.95, pred.get("elo_base", 0.5)))
            elo_a = 1.0 - elo_h
            VIG   = 0.05
            h_odds = round(1.0 / (elo_h * (1 + VIG)), 3)
            a_odds = round(1.0 / (elo_a * (1 + VIG)), 3)
            log.debug("ELO odds fallback %s@%s: h=%.3f a=%.3f", away, home, h_odds, a_odds)

        game_preds[f"{home}|{away}"] = {
            "home_win_prob": round(hp, 3),
            "market_total":  float(of.get("total_line") or 8.5),
            "mc_mean":       mc["mean_prob"],
            "mc_std":        mc["std_dev"],
            "ensemble":      ens,
            "matchup":       mu,
        }

        asp_data = {**merged_pitchers.get(ap_name, {}), "name": ap_name, "confirmed": ap_confirmed} if ap_name else {}
        hsp_data = {**merged_pitchers.get(hp_name, {}), "name": hp_name, "confirmed": hp_confirmed} if hp_name else {}

        base = dict(
            away=away, home=home,
            away_cn=TEAM_INFO.get(away, {}).get("name", g.get("away_name", away)),
            home_cn=TEAM_INFO.get(home, {}).get("name", g.get("home_name", home)),
            league=g.get("league", TEAM_INFO.get(home, {}).get("league", "")),
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
            signals=of.get("signals", []) + market_sig.get("signals", []),
            factors=pred.get("factors", {}),
            mc=mc,
            ensemble=ens,
            matchup=mu,
            market_signal=market_sig,
            fatigue={"home": home_fatigue, "away": away_fatigue},
        )

        # ── V8 Decision Agent ─────────────────────────────────────────────
        decision = agent_module.decide(
            g_for_pred, pred,
            mc=mc, demo_mode=DEMO_MODE,
            memory=memory, ensemble=ens, market_sig=market_sig,
        )
        best_pick = None
        if decision:
            pick = {**base, **decision}
            picks.append(pick)
            best_pick = pick
            # CLV 登錄（開盤賠率 vs 下注時賠率）
            entry_odds = h_odds if decision["side"] == "home" else a_odds
            clv_records = clv_module.add_entry(
                clv_records, today_str, game_key,
                entry_odds, decision["side"],
            )

        # ── 參考方向（無論是否推薦都記錄）──
        if hp >= ap:
            ref_label = f"{home_cn_name} 勝算較高"
            ref_prob  = round(hp * 100, 1)
            ref_odds  = h_odds
        else:
            ref_label = f"{away_cn_name} 勝算較高"
            ref_prob  = round(ap * 100, 1)
            ref_odds  = a_odds

        ref_edge = calc_edge(max(hp, ap), ref_odds) if ref_odds > 1 else 0
        adj_conf  = round(min(0.95, conf + mc.get("conf_boost", 0.0)), 3)

        all_preds.append({**base,
            "ref_label":   ref_label,
            "ref_prob":    ref_prob,
            "ref_odds":    round(ref_odds, 2),
            "ref_edge":    round(ref_edge, 4),
            "conf":        adj_conf,
            "tier":        get_tier(adj_conf),
            "recommended": best_pick is not None,
        })

    picks.sort(key=lambda x: x.get("ra_ev", x["edge"]), reverse=True)  # V8: sort by risk-adj EV
    all_preds.sort(key=lambda x: (not x["recommended"], -abs(x["home_win_prob"] - 0.5)))
    log.info("Picks: %d from %d games", len(picks), len(games))

    # game_display_date is the actual date of the games (may be tomorrow if today's all ended)
    game_display_date = today_str

    # ── V8 儲存 Feature Store + CLV ──────────────────────────────────────────
    fs_module.save(feature_store)
    clv_module.save(clv_records)
    market_module.save(market_data)

    # ── 5. Gist history + RL 更新 ────────────────────────────────────────────
    gid, history = load_gist()
    today_str = str(today)  # reset to actual today for gist/history bookkeeping

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
        "game_date":       game_display_date,
        "picks":           picks,
        "predictions":     all_preds,
        "live_games":      existing.get("live_games", []),
        "live_updated_at": existing.get("live_updated_at", ""),
        "live_updated_ts": existing.get("live_updated_ts", 0),
        "recent_history":  recent,
        "game_preds":      game_preds,
        "demo_mode":       DEMO_MODE,
        "v8_memory":       mem_module.v8_summary(memory),
        "v8_clv":          clv_module.summary(clv_records),
    }
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    log.info("Saved %s (%d picks, %d predictions)", JSON_PATH, len(picks), len(all_preds))

    # ── 7. Discord ───────────────────────────────────────────────────────────
    if all_preds:
        send_discord(picks, all_preds, game_display_date, history, memory)
    elif not games and not DEMO_MODE:
        send_discord_no_games(game_display_date, "今日無賽事（備份日程未填或真的休兵）")


if __name__ == "__main__":
    main()
