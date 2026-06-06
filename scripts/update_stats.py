#!/usr/bin/env python3
"""
NPB 數據本地更新腳本 — 日本職棒專用

使用方式：
  python scripts/update_stats.py          # 更新投手+賽程
  python scripts/update_stats.py --dry    # 只爬不寫入
  python scripts/update_stats.py --push   # 爬完自動 git commit + push
  python scripts/update_stats.py --odds-only --push  # 只更新賠率

資料來源優先順序：
  投手成績: npbdata.jp (pd.read_html) → nk-datasets
  賽程:     Yahoo Japan → npb.jp 官方 → 日刊體育 → The Odds API
  賠率:     The Odds API (baseball_npb) / oddsportal
"""
import sys, os, json, time, logging, argparse, datetime, copy
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from bs4 import BeautifulSoup
from cpbl.mock_data import PITCHERS
from cpbl.stats_scraper import (
    enrich_pitcher, calc_fip,
    fetch_npbdata_jp_pitchers, fetch_npbdata_jp_batters,
    fetch_pitcher_stats_nk, fetch_team_stats_nk,
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

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "ja,en-US;q=0.8",
}

_ODDS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
}

# NPB team name lookup for odds
_NPB_TEAM_MAP = {
    "yomiuri giants": "GNT", "giants": "GNT",
    "hanshin tigers": "HNS", "hanshin": "HNS",
    "hiroshima carp": "HRC", "hiroshima": "HRC", "carp": "HRC",
    "yokohama dena baystars": "YDB", "baystars": "YDB", "dena": "YDB",
    "yakult swallows": "YKL", "yakult": "YKL", "swallows": "YKL",
    "chunichi dragons": "CND", "chunichi": "CND", "dragons": "CND",
    "softbank hawks": "SBH", "softbank": "SBH", "hawks": "SBH",
    "orix buffaloes": "ORX", "orix": "ORX", "buffaloes": "ORX",
    "rakuten eagles": "RKT", "rakuten": "RKT", "eagles": "RKT",
    "lotte marines": "LTT", "marines": "LTT",
    "seibu lions": "SEI", "seibu": "SEI", "lions": "SEI",
    "nippon-ham fighters": "HAM", "fighters": "HAM", "nippon ham": "HAM",
}

_OP_URL_NPB = "https://www.oddsportal.com/baseball/japan/npb/"


# ─────────────────────────────────────────────────────────────
# 合併 + 寫入
# ─────────────────────────────────────────────────────────────

def merge_stats(live: dict, base: dict = None) -> dict:
    """合併 live 數據與 mock 底稿（NPB only，live 覆蓋 base 中的數字欄位）。"""
    base = copy.deepcopy(base or PITCHERS)
    # 只保留 NPB mock 底稿（剔除 KBO mock 數據）
    base = {k: v for k, v in base.items() if v.get("league", "NPB") == "NPB"}
    merged = {}
    for name in set(base.keys()) | set(live.keys()):
        p = copy.deepcopy(base.get(name, {}))
        for k, v in live.get(name, {}).items():
            if isinstance(v, (int, float)):
                p[k] = v
            elif k in ("team", "league", "foreign", "throws") and k not in p:
                p[k] = v
        enrich_pitcher(p)
        merged[name] = p
    return merged


def save_stats(merged: dict, dry: bool = False):
    now     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {"updated_at": now, "year": datetime.date.today().year,
               "source": "npbdata.jp+nk-datasets", "stats": merged}
    if dry:
        log.info("[DRY] 會寫入 %s（%d 名投手）", STATS_FILE, len(merged))
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("寫入 %s（%d 名投手）", STATS_FILE, len(merged))


def save_team_stats(team_stats: dict, source: str = "npbdata.jp", dry: bool = False):
    now     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {"updated_at": now, "year": datetime.date.today().year,
               "source": source, "stats": team_stats}
    if dry:
        log.info("[DRY] 會寫入 %s（%d 支球隊）", TEAM_STATS_FILE, len(team_stats))
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TEAM_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("寫入 %s（%d 支球隊）", TEAM_STATS_FILE, len(team_stats))


def update_schedule(games: list, dry: bool = False):
    """將爬到的 NPB 賽程寫入 schedule.json（合併現有資料）。"""
    if not games:
        log.info("update_schedule: 無新賽程")
        return

    _tw     = datetime.timezone(datetime.timedelta(hours=8))
    cutoff  = (datetime.datetime.now(_tw).date() - datetime.timedelta(days=2)).isoformat()

    try:
        with open(SCHED_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {"games": []}

    kept = [g for g in existing.get("games", [])
            if g.get("league") == "NPB" and g.get("date", "") >= cutoff]

    kept_by_id: dict[str, dict] = {
        g.get("game_id") or f"{g['date']}-{g['away']}-{g['home']}": g
        for g in kept
    }

    added = updated = 0
    for g in games:
        gid = g.get("game_id") or f"{g['date']}-{g['away']}-{g['home']}"
        if gid not in kept_by_id:
            kept.append(g)
            kept_by_id[gid] = g
            added += 1
        else:
            eg = kept_by_id[gid]
            changed = False
            if g.get("away_pitcher") and not eg.get("away_pitcher"):
                eg["away_pitcher"] = g["away_pitcher"]; changed = True
            if g.get("home_pitcher") and not eg.get("home_pitcher"):
                eg["home_pitcher"] = g["home_pitcher"]; changed = True
            if g.get("time") and not eg.get("time"):
                eg["time"] = g["time"]; changed = True
            if g.get("away_score") is not None and eg.get("away_score") is None:
                eg["away_score"] = g["away_score"]
                eg["home_score"] = g["home_score"]
                eg["status"]     = g.get("status", "終了")
                changed = True
            if changed:
                updated += 1

    kept.sort(key=lambda x: (x.get("date", ""), x.get("time", "")))
    payload = {"games": kept,
               "updated_at": datetime.datetime.now(_tw).date().isoformat()}
    if dry:
        log.info("[DRY] 新增 %d 場、更新 %d 場（總計 %d 場）", added, updated, len(kept))
        return
    with open(SCHED_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("schedule.json 新增 %d 場、更新 %d 場（共 %d 場 NPB）",
             added, updated, len(kept))


# ─────────────────────────────────────────────────────────────
# 賽程爬取（14 天滾動窗口）
# ─────────────────────────────────────────────────────────────

def scrape_schedule(year: int, months: list, session: requests.Session) -> list:
    """昨天到 14 天後的 NPB 賽程（多來源自動 fallback）。"""
    from cpbl.stats_scraper import fetch_schedule_multi

    all_games = []
    _tw   = datetime.timezone(datetime.timedelta(hours=8))
    today = datetime.datetime.now(_tw).date()
    start = today - datetime.timedelta(days=1)
    end   = today + datetime.timedelta(days=14)

    odds_key = os.environ.get("ODDS_API_KEY", "")
    current  = start
    while current <= end:
        games = fetch_schedule_multi(current, odds_api_key=odds_key)
        if games:
            log.info("  %s: %d 場 NPB", current, len(games))
        all_games.extend(games)
        time.sleep(0.5)
        current += datetime.timedelta(days=1)

    log.info("賽程合計: %d 場（%s ~ %s）", len(all_games), start, end)
    return all_games


# ─────────────────────────────────────────────────────────────
# 先發投手補強
# ─────────────────────────────────────────────────────────────

def _enrich_starters_in_schedule(today_str: str, dry: bool = False) -> None:
    """schedule.json の今日・明日の先発投手を Yahoo Japan 予告先発で補完。"""
    try:
        with open(SCHED_FILE, encoding="utf-8") as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.warning("_enrich_starters: cannot load schedule.json: %s", e)
        return

    games = payload.get("games", [])
    if not games:
        return

    today    = datetime.date.fromisoformat(today_str)
    tomorrow = today + datetime.timedelta(days=1)
    enriched_total = 0

    for target_date in (today, tomorrow):
        date_str  = target_date.isoformat()
        day_games = [g for g in games if g.get("date") == date_str and g.get("league") == "NPB"]
        if not day_games:
            continue

        before = sum(1 for g in day_games if g.get("away_pitcher") or g.get("home_pitcher"))
        enrich_schedule_with_starters(target_date, day_games)
        after  = sum(1 for g in day_games if g.get("away_pitcher") or g.get("home_pitcher"))
        filled = after - before
        enriched_total += filled

        if filled:
            print(f"  ✅ {date_str}: {filled} 場有先發投手資料（共 {len(day_games)} 場 NPB）")
        else:
            print(f"  ⚠️  {date_str}: 未找到先發投手（共 {len(day_games)} 場 NPB）")

    if enriched_total and not dry:
        payload["updated_at"] = today_str
        with open(SCHED_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        log.info("_enrich_starters: saved %d new pitcher slots", enriched_total)


# ─────────────────────────────────────────────────────────────
# 賠率爬取
# ─────────────────────────────────────────────────────────────

def _npb_code(name: str) -> str:
    n = name.lower().strip()
    for k, v in _NPB_TEAM_MAP.items():
        if k in n or n in k:
            return v
    return ""



def _scrape_odds_api(session: requests.Session) -> dict:
    """The Odds API — NPB"""
    api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        log.warning("ODDS_API_KEY 未設定，跳過賠率抓取")
        return {}
    url = (f"https://api.the-odds-api.com/v4/sports/baseball_npb/odds/"
           f"?apiKey={api_key}&regions=eu,us&markets=h2h&oddsFormat=decimal")
    try:
        r = session.get(url, timeout=12, headers=_ODDS_HEADERS)
        if r.status_code == 404:
            log.debug("baseball_npb odds endpoint not found")
            return {}
        if r.status_code == 401:
            log.warning("Odds API: invalid API key")
            return {}
        r.raise_for_status()
        data   = r.json()
        result = {}
        for event in (data if isinstance(data, list) else []):
            home_en   = event.get("home_team", "").lower()
            away_en   = event.get("away_team", "").lower()
            home_code = _npb_code(home_en)
            away_code = _npb_code(away_en)
            if not home_code or not away_code:
                continue
            ah = hh = None
            for bm in event.get("bookmakers", []):
                for mkt in bm.get("markets", []):
                    if mkt.get("key") == "h2h":
                        for out in mkt.get("outcomes", []):
                            n = out.get("name", "").lower()
                            if home_en in n:
                                hh = float(out.get("price", hh or 1.90))
                            elif away_en in n:
                                ah = float(out.get("price", ah or 1.90))
                if ah and hh:
                    break
            if ah and hh:
                result[f"{away_code}-{home_code}"] = {
                    "source":         "The Odds API (NPB)",
                    "curr_away_odds": round(ah, 3),
                    "curr_home_odds": round(hh, 3),
                    "open_away_odds": round(ah, 3),
                    "open_home_odds": round(hh, 3),
                    "vig_pct":        round((1/ah + 1/hh - 1) * 100, 2),
                    "bookmakers":     ["The Odds API"],
                }
        if result:
            log.info("The Odds API NPB: %d 場賠率", len(result))
        return result
    except Exception as e:
        log.debug("The Odds API NPB 失敗: %s", e)
        return {}


def _scrape_op_html(session: requests.Session) -> dict:
    """oddsportal NPB HTML 解析（備援）"""
    result = {}
    try:
        r = session.get(_OP_URL_NPB, timeout=15, headers=_ODDS_HEADERS)
        if r.status_code != 200:
            return {}
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select(".eventRow, [class*='eventRow']"):
            teams = row.select(".participant-name, .team-name")
            if len(teams) < 2:
                continue
            ac = _npb_code(teams[0].get_text(strip=True))
            hc = _npb_code(teams[1].get_text(strip=True))
            if not ac or not hc:
                continue
            nums = []
            for el in row.select(".odds-nowrp, .oddsValueInner, [class*='odds']"):
                try:
                    nums.append(float(el.get_text(strip=True)))
                except ValueError:
                    pass
            if len(nums) >= 2:
                ah, hh = nums[0], nums[1]
                result[f"{ac}-{hc}"] = {
                    "source":         "oddsportal",
                    "curr_away_odds": round(ah, 3),
                    "curr_home_odds": round(hh, 3),
                    "open_away_odds": round(ah, 3),
                    "open_home_odds": round(hh, 3),
                    "vig_pct":        round((1/ah + 1/hh - 1) * 100, 2) if ah > 1 and hh > 1 else 7.5,
                    "bookmakers":     ["oddsportal"],
                }
    except Exception as e:
        log.debug("oddsportal 失敗: %s", e)
    if result:
        log.info("oddsportal NPB: %d 場賠率", len(result))
    return result


def scrape_odds(game_date_str: str, session: requests.Session,
                use_playwright: bool = False) -> dict:
    odds = _scrape_odds_api(session)
    if not odds:
        odds = _scrape_op_html(session)
    return odds


def save_odds(odds: dict, game_date_str: str, source: str = "local", dry: bool = False):
    now     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {"updated_at": now, "game_date": game_date_str,
               "source": source, "odds": odds}
    if dry:
        log.info("[DRY] 會寫入 %s（%d 場賠率）", ODDS_FILE, len(odds))
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ODDS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("寫入 %s（%d 場賠率）", ODDS_FILE, len(odds))


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    _TW_TZ  = datetime.timezone(datetime.timedelta(hours=8))
    _now_tw = datetime.datetime.now(_TW_TZ)

    ap = argparse.ArgumentParser(description="NPB 數據更新腳本")
    ap.add_argument("--dry",           action="store_true", help="只爬不寫入")
    ap.add_argument("--push",          action="store_true", help="完成後自動 git commit + push")
    ap.add_argument("--year",          type=int, default=_now_tw.year)
    ap.add_argument("--months",        nargs="+", type=int,
                    default=[_now_tw.month, min(12, _now_tw.month + 1)])
    ap.add_argument("--skip-schedule", action="store_true", help="跳過賽程爬取")
    ap.add_argument("--skip-odds",     action="store_true", help="跳過賠率爬取")
    ap.add_argument("--odds-only",     action="store_true", help="只爬賠率")
    ap.add_argument("--no-playwright", action="store_true", help="停用 Playwright")
    args = ap.parse_args()

    print("=" * 60)
    print(f"NPB 數據更新 — {args.year}年 | dry={args.dry}")
    print("=" * 60)

    session = requests.Session()
    session.headers.update(_HEADERS)

    today_str  = _now_tw.date().isoformat()
    live_stats: dict = {}

    if not args.odds_only:
        # ── [1/4] npbdata.jp 投手成績（主要來源）──
        print(f"\n[1/4] 抓取 NPB 投手成績（npbdata.jp — pd.read_html）...")
        npbd_stats = fetch_npbdata_jp_pitchers(args.year)
        if npbd_stats:
            live_stats.update(npbd_stats)
            print(f"  ✅ npbdata.jp: {len(npbd_stats)} 名投手 (ERA/FIP/WHIP/K9/BB9)")
        else:
            print("  ⚠️ npbdata.jp 失敗（HTTP 403 or 無資料）")

        # ── [1b] nk-datasets 補充（npbdata.jp 失敗時的備援）──
        print(f"\n[1b/4] nk-datasets NPB 投手成績（備援）...")
        nk_stats = fetch_pitcher_stats_nk(args.year)
        if nk_stats:
            for name, p in nk_stats.items():
                if name not in live_stats:
                    live_stats[name] = p
                else:
                    # nk-datasets 數據較舊，只補充缺失欄位
                    for k, v in p.items():
                        if k not in live_stats[name] and isinstance(v, (int, float)):
                            live_stats[name][k] = v
            npb_cnt = sum(1 for v in nk_stats.values() if v.get("league") == "NPB")
            print(f"  ✅ nk-datasets: {npb_cnt} 名 NPB 投手（補充缺失數據）")
        else:
            print("  ⚠️ nk-datasets 失敗（套件未安裝？）")

        # ── [2/4] 合併 + 儲存投手成績 ──
        merged = merge_stats(live_stats)
        print(f"\n[2/4] 儲存投手成績...")
        print(f"  合計: {len(merged)} 名投手 (live={len(live_stats)}, mock補充={len(merged)-len(live_stats)})")
        for name in list(merged.keys())[:3]:
            p = merged[name]
            print(f"  {name}: ERA={p.get('era')} FIP={p.get('fip')} K9={p.get('k9')} BB9={p.get('bb9')}")
        save_stats(merged, dry=args.dry)

        # ── [2b] 球隊成績 ──
        print(f"\n[2b/4] 抓取 NPB 球隊成績...")
        team_stats = fetch_npbdata_jp_batters(args.year)
        if team_stats:
            print(f"  ✅ npbdata.jp batter: {len(team_stats)} 支球隊")
        else:
            print("  ⚠️ npbdata.jp batter 失敗，嘗試 nk-datasets...")
            team_stats = fetch_team_stats_nk(args.year)
            if team_stats:
                print(f"  ✅ nk-datasets 球隊: {len(team_stats)} 支")

        if team_stats:
            src = "npbdata.jp" if team_stats else "nk-datasets"
            save_team_stats(team_stats, source=src, dry=args.dry)

        # ── [3/4] 賽程 ──
        if not args.skip_schedule:
            print(f"\n[3/4] 抓取 NPB 賽程（{args.months} 月份）...")
            games = scrape_schedule(args.year, args.months, session)
            update_schedule(games, dry=args.dry)

            print(f"\n[3b/4] 今明先發投手補強（Yahoo Japan 予告先発）...")
            _enrich_starters_in_schedule(today_str, args.dry)
        else:
            print("\n[3/4] 跳過賽程爬取（--skip-schedule）")
    else:
        print("\n[--odds-only] 跳過投手成績與賽程爬取")

    # ── [4/4] 賠率 ──
    if not args.skip_odds:
        print(f"\n[4/4] 抓取今日 NPB 賠率（{today_str}）...")
        use_pw = not args.no_playwright
        odds   = scrape_odds(today_str, session, use_playwright=use_pw)
        if odds:
            sources = {v.get("source", "?") for v in odds.values()}
            print(f"  ✅ {len(odds)} 場賠率 [來源: {', '.join(sources)}]")
            for k, v in list(odds.items())[:3]:
                print(f"  {k}: {v.get('curr_away_odds')} / {v.get('curr_home_odds')}")
            save_odds(odds, today_str, source=next(iter(sources), "local"), dry=args.dry)
        else:
            print("  ⚠️ 無法取得賠率（ODDS_API_KEY 未設定？）")
    else:
        print("\n[4/4] 跳過賠率爬取（--skip-odds）")

    if args.push and not args.dry:
        print("\n[push] Git commit + push...")
        import subprocess
        files = [f for f in [STATS_FILE, TEAM_STATS_FILE, SCHED_FILE, ODDS_FILE]
                 if os.path.exists(f)]
        if files:
            subprocess.run(["git", "add"] + files, check=True)
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")
            subprocess.run(["git", "commit", "-m", f"data: auto-update NPB {ts} [skip ci]"],
                           check=True)
            subprocess.run(["git", "push"], check=True)
            print("  ✅ 已推送")

    print("\n✅ 完成")


if __name__ == "__main__":
    main()
