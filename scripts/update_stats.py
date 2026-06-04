#!/usr/bin/env python3
"""
CPBL 數據本地更新腳本 — 在你的電腦執行，把數據推上 GitHub

使用方式：
  python scripts/update_stats.py          # 更新投手+賽程
  python scripts/update_stats.py --dry    # 只爬不寫入
  python scripts/update_stats.py --push   # 爬完自動 git commit + push

執行環境：你的個人電腦（不是 GitHub Actions）
原因：所有 CPBL 數據網站封鎖雲端機房 IP（包含 GH Actions、Codespace）
"""
import sys, os, json, time, logging, argparse, datetime, copy
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from bs4 import BeautifulSoup
from cpbl.mock_data import PITCHERS
from cpbl.stats_scraper import enrich_pitcher, calc_fip

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("update_stats")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
STATS_FILE   = os.path.join(DATA_DIR, "pitcher_stats.json")
SCHED_FILE   = os.path.join(DATA_DIR, "schedule.json")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.cpbl.com.tw/",
}

BASE = "https://www.cpbl.com.tw"

# ─────────────────────────────────────────────────────────────
# 1. CPBL 官方投手成績
# ─────────────────────────────────────────────────────────────

def scrape_cpbl_pitchers(year: int, session: requests.Session) -> dict:
    """
    從 CPBL 官網抓先發投手成績。
    支援多種 URL 格式，自動嘗試。
    """
    urls = [
        f"{BASE}/stats/player?kind=P&year={year}&kindType=SP",
        f"{BASE}/stats/player?kind=P&year={year}&kindType=1",
        f"{BASE}/stats/player?kind=P&year={year}",
        f"{BASE}/stats/toplist?type=0&kind=P&year={year}",
        f"{BASE}/stats/record?type=0&kindType=SP&year={year}",
    ]

    for url in urls:
        try:
            log.info("嘗試 CPBL stats: %s", url)
            r = session.get(url, timeout=15)
            if r.status_code == 403:
                log.warning("403 被擋 — 請確認在個人電腦執行，不是雲端機器")
                break
            if r.status_code == 404:
                continue
            r.raise_for_status()
            stats = _parse_cpbl_stats(r.text)
            if stats:
                log.info("CPBL 官網: 抓到 %d 名投手", len(stats))
                return stats
        except requests.exceptions.RequestException as e:
            log.warning("URL %s 失敗: %s", url, e)
            continue

    return {}


def _parse_cpbl_stats(html: str) -> dict:
    soup  = BeautifulSoup(html, "html.parser")
    stats = {}
    col_map = {
        "姓名": "name", "球員": "name",
        "ERA": "era", "防禦率": "era",
        "WHIP": "whip",
        "K/9": "k9", "SO/9": "k9",
        "BB/9": "bb9",
        "HR/9": "hr9",
        "IP":  "innings", "局數": "innings",
        "K":   "_k", "SO": "_k", "三振": "_k",
        "BB":  "_bb", "四壞": "_bb",
        "HR":  "_hr", "全壘打": "_hr",
        "HBP": "_hbp",
        "GS":  "gs", "先發": "gs",
        "W":   "wins", "勝": "wins",
        "L":   "losses", "敗": "losses",
        "K%":  "k_pct",
        "BB%": "bb_pct",
        "FIP": "fip",
        "BABIP": "babip",
        "LOB%": "lob_pct",
    }
    for table in soup.find_all("table"):
        header_row = (table.find("thead") or table).find("tr")
        if not header_row:
            continue
        raw  = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
        hdrs = [col_map.get(h, h.lower()) for h in raw]
        if "name" not in hdrs or "era" not in hdrs:
            continue
        for row in table.select("tbody tr, tr")[1:]:
            tds  = [td.get_text(strip=True) for td in row.find_all("td")]
            if not tds:
                continue
            try:
                name = tds[hdrs.index("name")].strip()
            except (ValueError, IndexError):
                continue
            if not name or name in ("合計", "Total", "平均", ""):
                continue
            p: dict = {}
            for field in ("era", "whip", "k9", "bb9", "hr9", "innings",
                          "_k", "_bb", "_hr", "_hbp",
                          "gs", "wins", "losses", "k_pct", "bb_pct",
                          "fip", "babip", "lob_pct"):
                if field not in hdrs:
                    continue
                raw_val = tds[hdrs.index(field)]
                raw_val = raw_val.replace("⅓", ".33").replace("⅔", ".67").replace("%", "")
                try:
                    p[field] = float(raw_val)
                except (ValueError, TypeError):
                    pass
            if "era" not in p:
                continue
            # 用累計數字算 K9/BB9
            ip = p.pop("innings", 0)
            if ip > 0:
                p["innings"] = ip
                k   = p.pop("_k",   0)
                bb  = p.pop("_bb",  0)
                hr  = p.pop("_hr",  0)
                hbp = p.pop("_hbp", 0)
                if k  > 0 and "k9"  not in p: p["k9"]  = round(k  / ip * 9, 2)
                if bb > 0 and "bb9" not in p: p["bb9"] = round(bb / ip * 9, 2)
                if hr > 0:
                    p["_raw_k"] = k; p["_raw_bb"] = bb
                    p["_raw_hr"] = hr; p["_raw_hbp"] = hbp
            enrich_pitcher(p)
            stats[name] = p

    return stats


# ─────────────────────────────────────────────────────────────
# 2. 嘗試 cpblstats.com（若可存取）
# ─────────────────────────────────────────────────────────────

def scrape_cpblstats(year: int, session: requests.Session) -> dict:
    """從 cpblstats.com 抓進階數據（包含 FIP/K%/BB% 等）。"""
    urls = [
        f"https://cpblstats.com/pitchers?year={year}",
        f"https://cpblstats.com/stats/pitchers/{year}",
        f"https://cpblstats.com/api/pitchers?year={year}",
    ]
    for url in urls:
        try:
            r = session.get(url, timeout=12)
            if r.status_code == 403:
                log.warning("cpblstats.com 403 — 可能仍封鎖你的 IP")
                break
            if r.status_code != 200:
                continue
            # JSON API
            if "application/json" in r.headers.get("content-type", ""):
                data  = r.json()
                stats = _parse_json_pitchers(data)
                if stats:
                    log.info("cpblstats.com API: %d 名投手", len(stats))
                    return stats
            # HTML
            stats = _parse_cpblstats_html(r.text)
            if stats:
                log.info("cpblstats.com HTML: %d 名投手", len(stats))
                return stats
        except Exception as e:
            log.debug("cpblstats URL %s: %s", url, e)
            continue
    return {}


def _parse_json_pitchers(data) -> dict:
    """解析 JSON 格式的投手數據（通用格式）。"""
    stats = {}
    items = data if isinstance(data, list) else data.get("data", data.get("pitchers", []))
    for item in items:
        name = item.get("name") or item.get("playerName") or item.get("chineseName", "")
        if not name:
            continue
        p = {k: v for k, v in item.items()
             if k in ("era", "whip", "fip", "xfip", "k9", "bb9", "hr9",
                      "k_pct", "bb_pct", "babip", "lob_pct",
                      "innings", "gs", "wins", "losses", "k_bb_pct")}
        if "era" not in p:
            continue
        enrich_pitcher(p)
        stats[name] = p
    return stats


def _parse_cpblstats_html(html: str) -> dict:
    """解析 cpblstats.com 的 HTML 表格。"""
    # 結構與 CPBL 官網類似，重用解析邏輯
    return _parse_cpbl_stats(html)


# ─────────────────────────────────────────────────────────────
# 3. myCPBL
# ─────────────────────────────────────────────────────────────

def scrape_mycpbl(year: int, session: requests.Session) -> dict:
    """從 myCPBL 抓投手數據。"""
    urls = [
        f"https://mycpbl.com/stats/pitcher?year={year}",
        f"https://www.mycpbl.com/stats/pitcher?year={year}",
        f"https://mycpbl.com/api/pitcher?year={year}",
    ]
    for url in urls:
        try:
            r = session.get(url, timeout=12)
            if r.status_code == 403:
                break
            if r.status_code != 200:
                continue
            if "json" in r.headers.get("content-type", ""):
                stats = _parse_json_pitchers(r.json())
            else:
                stats = _parse_cpbl_stats(r.text)
            if stats:
                log.info("myCPBL: %d 名投手", len(stats))
                return stats
        except Exception as e:
            log.debug("myCPBL %s: %s", url, e)
    return {}


# ─────────────────────────────────────────────────────────────
# 4. CPBL 賽程
# ─────────────────────────────────────────────────────────────

def scrape_schedule(year: int, months: list[int], session: requests.Session) -> list:
    """抓多個月份的賽程，用 Playwright 繞過 JS 渲染。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("Playwright 未安裝，跳過賽程爬取。可用: pip install playwright && playwright install chromium")
        return []

    from cpbl.scraper import CPBLScraper, TEAM_CODE_MAP
    import datetime

    all_games = []
    scraper   = CPBLScraper()

    for month in months:
        for day in range(1, 32):
            try:
                d = datetime.date(year, month, day)
            except ValueError:
                break
            games = scraper.fetch_schedule(d)
            all_games.extend(games)
            time.sleep(0.5)   # 避免爬太快

    log.info("賽程: 共 %d 場（%d 個月份）", len(all_games), len(months))
    return all_games


# ─────────────────────────────────────────────────────────────
# 5. 合併 + 寫入
# ─────────────────────────────────────────────────────────────

def merge_stats(live: dict, base: dict = None) -> dict:
    """
    合併多個來源的數據。
    live 覆蓋 base（mock）中的數字型欄位。
    """
    base = copy.deepcopy(base or PITCHERS)
    merged = {}
    all_names = set(base.keys()) | set(live.keys())
    for name in all_names:
        p = copy.deepcopy(base.get(name, {}))
        for k, v in live.get(name, {}).items():
            if isinstance(v, (int, float)):
                p[k] = v
            elif k in ("team", "foreign", "throws") and k not in p:
                p[k] = v
        enrich_pitcher(p)
        merged[name] = p
    return merged


def save_stats(merged: dict, dry: bool = False):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {"updated_at": now, "year": datetime.date.today().year,
               "source": "local_scraper", "stats": merged}
    if dry:
        log.info("[DRY] 會寫入 %s（%d 名投手）", STATS_FILE, len(merged))
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("寫入 %s（%d 名投手）", STATS_FILE, len(merged))


def update_schedule(games: list, dry: bool = False):
    """將爬到的賽程合併進 schedule.json。"""
    if not games:
        return
    try:
        with open(SCHED_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {"games": []}

    # 以 game_id 去重
    existing_ids = {g.get("game_id") or f"{g['date']}-{g['away']}-{g['home']}"
                    for g in existing.get("games", [])}
    added = 0
    for g in games:
        gid = g.get("game_id") or f"{g['date']}-{g['away']}-{g['home']}"
        if gid not in existing_ids:
            existing["games"].append(g)
            existing_ids.add(gid)
            added += 1

    existing["games"].sort(key=lambda x: (x.get("date", ""), x.get("time", "")))
    if dry:
        log.info("[DRY] 會新增 %d 場賽程到 schedule.json", added)
        return
    with open(SCHED_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    log.info("schedule.json 新增 %d 場（總計 %d 場）",
             added, len(existing["games"]))


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="CPBL 數據本地更新腳本")
    ap.add_argument("--dry",   action="store_true", help="只爬不寫入")
    ap.add_argument("--push",  action="store_true", help="完成後自動 git commit + push")
    ap.add_argument("--year",  type=int, default=datetime.date.today().year)
    ap.add_argument("--months",nargs="+", type=int,
                    default=[datetime.date.today().month,
                             min(12, datetime.date.today().month + 1)],
                    help="要抓的月份（預設：本月+下月）")
    ap.add_argument("--skip-schedule", action="store_true", help="跳過賽程爬取")
    args = ap.parse_args()

    print("=" * 60)
    print(f"CPBL 數據更新 — {args.year}年 | dry={args.dry}")
    print("注意：請在個人電腦執行，不支援 GitHub Actions")
    print("=" * 60)

    session = requests.Session()
    session.headers.update(_HEADERS)

    # ── 暖身 cookie ──
    try:
        session.get("https://www.cpbl.com.tw", timeout=8)
        time.sleep(1)
    except Exception:
        pass

    live_stats = {}

    # ── 投手成績：多來源 ──
    print("\n[1/3] 抓取投手成績...")
    stats = scrape_cpbl_pitchers(args.year, session)
    if stats:
        live_stats.update(stats)
        print(f"  ✅ CPBL 官網: {len(stats)} 名投手")
    else:
        print("  ❌ CPBL 官網失敗，嘗試 cpblstats.com...")
        stats2 = scrape_cpblstats(args.year, session)
        if stats2:
            live_stats.update(stats2)
            print(f"  ✅ cpblstats.com: {len(stats2)} 名投手")
        else:
            stats3 = scrape_mycpbl(args.year, session)
            if stats3:
                live_stats.update(stats3)
                print(f"  ✅ myCPBL: {len(stats3)} 名投手")
            else:
                print("  ⚠️ 所有來源失敗，使用 mock 數據（加上衍生指標計算）")

    # ── 合併 mock + live ──
    merged = merge_stats(live_stats)
    print(f"\n  合計: {len(merged)} 名投手 (live={len(live_stats)}, mock補充={len(merged)-len(live_stats)})")

    # 印出樣本
    for name in list(merged.keys())[:3]:
        p = merged[name]
        print(f"  {name}: ERA={p.get('era')} FIP={p.get('fip')} K%={p.get('k_pct')}% BB%={p.get('bb_pct')}%")

    # ── 儲存投手成績 ──
    print("\n[2/3] 儲存投手成績...")
    save_stats(merged, dry=args.dry)

    # ── 賽程 ──
    if not args.skip_schedule:
        print(f"\n[3/3] 抓取 {args.months} 月份賽程...")
        games = scrape_schedule(args.year, args.months, session)
        update_schedule(games, dry=args.dry)
    else:
        print("\n[3/3] 跳過賽程爬取")

    # ── git push ──
    if args.push and not args.dry:
        print("\n[git] commit + push...")
        import subprocess
        subprocess.run(["git", "add",
                        "data/pitcher_stats.json", "data/schedule.json"],
                       cwd=os.path.join(os.path.dirname(__file__), ".."),
                       check=False)
        subprocess.run(["git", "commit", "-m",
                        f"data: update pitcher stats {datetime.date.today()} [skip ci]"],
                       cwd=os.path.join(os.path.dirname(__file__), ".."),
                       check=False)
        subprocess.run(["git", "push"],
                       cwd=os.path.join(os.path.dirname(__file__), ".."),
                       check=False)
        print("  ✅ 推送完成")

    print("\n完成！")


if __name__ == "__main__":
    main()
