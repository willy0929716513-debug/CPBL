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

DATA_DIR   = os.path.join(os.path.dirname(__file__), "..", "data")
STATS_FILE = os.path.join(DATA_DIR, "pitcher_stats.json")
SCHED_FILE = os.path.join(DATA_DIR, "schedule.json")
ODDS_FILE  = os.path.join(DATA_DIR, "odds_today.json")

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
# 5. 賠率爬取（台灣運彩 / oddsportal）
# ─────────────────────────────────────────────────────────────

# 台灣運彩隊名 → 代碼
_SL_TEAM_MAP = {
    "中信兄弟": "AEL", "兄弟":   "AEL",
    "統一7-ELEVEn獅": "CT",  "統一獅":  "CT",  "統一":    "CT",
    "富邦悍將":  "FG",  "悍將":   "FG",  "富邦":    "FG",
    "樂天桃猿":  "WL",  "桃猿":   "WL",  "樂天":    "WL",
    "台鋼雄鷹":  "TSG", "雄鷹":   "TSG", "台鋼":    "TSG",
    "味全龍":    "WC",  "龍":     "WC",  "味全":    "WC",
}

# oddsportal 英文隊名 → 代碼
_OP_TEAM_MAP = {
    "rakuten monkeys":              "WL",
    "ctbc brothers":                "AEL",
    "fubon guardians":              "FG",
    "uni-president 7-eleven lions": "CT",
    "uni president 7-eleven lions": "CT",
    "tsg hawks":                    "TSG",
    "taiwan steel hawks":           "TSG",
    "wei-chuan dragons":            "WC",
    "wei chuan dragons":            "WC",
}

_SL_API_URL  = "https://api2.sportslottery.com.tw/sport/events?sport=baseball&league=cpbl"
_SL_HTML_URL = "https://www.sportslottery.com.tw/sport/baseball/cpbl"
_OP_URL      = "https://www.oddsportal.com/baseball/taiwan/cpbl/"

_ODDS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "Referer":         "https://www.sportslottery.com.tw/",
}


def _sl_code(name: str) -> str:
    """模糊比對隊名 → 代碼"""
    name = name.strip()
    for k, v in _SL_TEAM_MAP.items():
        if k in name or name in k:
            return v
    return ""


def _op_code(name: str) -> str:
    name = name.lower().strip()
    for k, v in _OP_TEAM_MAP.items():
        if k in name or name in k:
            return v
    return ""


def _make_odds_entry(away_odds: float, home_odds: float,
                     open_away: float = None, open_home: float = None,
                     run_line: float = -1.5,
                     rl_home: float = 1.90, rl_away: float = 1.90,
                     total: float = 8.5,
                     over_o: float = 1.90, under_o: float = 1.90,
                     pub_home: int = 50, source: str = "local", note: str = "") -> dict:
    if open_away is None: open_away = away_odds
    if open_home is None: open_home = home_odds
    vig = round((1 / home_odds + 1 / away_odds - 1) * 100, 2) if home_odds > 1 and away_odds > 1 else 7.5
    return {
        "source":          source,
        "curr_away_odds":  round(away_odds, 3),
        "curr_home_odds":  round(home_odds, 3),
        "open_away_odds":  round(open_away,  3),
        "open_home_odds":  round(open_home,  3),
        "run_line":        run_line,
        "rl_home_odds":    round(rl_home,  3),
        "rl_away_odds":    round(rl_away,  3),
        "total":           total,
        "over_odds":       round(over_o,   3),
        "under_odds":      round(under_o,  3),
        "public_home_pct": pub_home,
        "public_away_pct": 100 - pub_home,
        "vig_pct":         vig,
        "bookmakers":      [source],
        "note":            note,
    }


def _scrape_sl_api(session: requests.Session) -> dict:
    """台灣運彩 JSON API"""
    try:
        r = session.get(_SL_API_URL, timeout=12, headers=_ODDS_HEADERS)
        if r.status_code == 403:
            log.warning("台灣運彩 API 403 — 嘗試 HTML")
            return {}
        r.raise_for_status()
        data = r.json()
        result = {}
        for event in data.get("events", data.get("data", [])):
            teams = event.get("teams", event.get("competitors", []))
            if len(teams) < 2:
                continue
            # 嘗試識別主客隊
            away_name = teams[0].get("name", "")
            home_name = teams[1].get("name", "")
            away_code = _sl_code(away_name)
            home_code = _sl_code(home_name)
            if not away_code or not home_code:
                continue
            game_key = f"{away_code}-{home_code}"

            # 解析各種賠率類型
            ah = hh = None      # away/home h2h
            run_line = -1.5
            rl_h = rl_a = 1.90
            total = 8.5
            over_o = under_o = 1.90
            open_a = open_h = None
            pub_home = 50

            for o in event.get("odds", event.get("markets", [])):
                kind = o.get("kind", o.get("marketType", "")).lower()
                if kind in ("win", "moneyline", "h2h", "1x2"):
                    ah = float(o.get("awayOdds", o.get("oddAway", o.get("away", ah or 1.90))))
                    hh = float(o.get("homeOdds", o.get("oddHome", o.get("home", hh or 1.90))))
                    open_a = float(o.get("openAwayOdds", o.get("openAway", ah)))
                    open_h = float(o.get("openHomeOdds", o.get("openHome", hh)))
                elif kind in ("runline", "run_line", "spread", "handicap"):
                    run_line = float(o.get("line", o.get("spread", -1.5)))
                    rl_h = float(o.get("homeOdds", o.get("home", 1.90)))
                    rl_a = float(o.get("awayOdds", o.get("away", 1.90)))
                elif kind in ("total", "totals", "ou"):
                    total = float(o.get("line", o.get("total", 8.5)))
                    over_o  = float(o.get("overOdds",  o.get("over",  1.90)))
                    under_o = float(o.get("underOdds", o.get("under", 1.90)))
                elif kind in ("public", "public_bet_pct"):
                    pub_home = int(o.get("homePct", o.get("home_pct", 50)))

            if ah and hh:
                result[game_key] = _make_odds_entry(
                    ah, hh, open_a, open_h,
                    run_line, rl_h, rl_a,
                    total, over_o, under_o,
                    pub_home, source="台灣運彩",
                    note="台灣運彩 API",
                )
        if result:
            log.info("台灣運彩 API: %d 場賠率", len(result))
        return result
    except Exception as e:
        log.debug("台灣運彩 API 失敗: %s", e)
        return {}


def _scrape_sl_html(session: requests.Session) -> dict:
    """台灣運彩 HTML 解析"""
    try:
        r = session.get(_SL_HTML_URL, timeout=15, headers=_ODDS_HEADERS)
        if r.status_code == 403:
            log.warning("台灣運彩 HTML 403")
            return {}
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        result = {}

        # 嘗試多種 CSS 選擇器（台灣運彩改版頻繁）
        game_selectors = [
            ".game-item", ".match-item", ".event-item",
            "[data-event-id]", ".game-row",
        ]
        for sel in game_selectors:
            items = soup.select(sel)
            if not items:
                continue
            for item in items:
                text = item.get_text(" ", strip=True)
                teams_found = []
                for k in _SL_TEAM_MAP:
                    if k in text:
                        teams_found.append(_SL_TEAM_MAP[k])
                if len(teams_found) < 2:
                    continue
                # 取賠率數字
                vals = []
                for el in item.select(".odds, .odd-value, td.odds, [class*='odd'], [class*='price']"):
                    try:
                        vals.append(float(el.get_text(strip=True)))
                    except ValueError:
                        pass
                if len(vals) >= 2:
                    away_c, home_c = teams_found[0], teams_found[1]
                    game_key = f"{away_c}-{home_c}"
                    result[game_key] = _make_odds_entry(
                        vals[0], vals[1],
                        source="台灣運彩",
                        note="台灣運彩 HTML",
                    )
            if result:
                log.info("台灣運彩 HTML: %d 場賠率", len(result))
                return result
        return result
    except Exception as e:
        log.debug("台灣運彩 HTML 失敗: %s", e)
        return {}


def _scrape_sl_playwright(game_date_str: str) -> dict:
    """Playwright 動態渲染台灣運彩（JS 重度渲染時用）"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {}
    try:
        result = {}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page    = browser.new_page(extra_http_headers={
                "Accept-Language": "zh-TW,zh;q=0.9",
            })
            page.goto(_SL_HTML_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
        soup = BeautifulSoup(html, "html.parser")

        # 從頁面提取 JSON 資料（常見 Next.js / Vue 應用注入 window.__data__ 等）
        for script in soup.find_all("script"):
            text = script.string or ""
            if "homeOdds" in text or "awayOdds" in text:
                import re as _re
                # 嘗試抓 JSON blob
                matches = _re.findall(r'\{[^{}]*"homeOdds"\s*:[^{}]+\}', text)
                for m in matches:
                    try:
                        obj = json.loads(m)
                        ah  = float(obj.get("awayOdds", 0))
                        hh  = float(obj.get("homeOdds", 0))
                        if ah > 1 and hh > 1:
                            away_n = obj.get("awayTeam", obj.get("away", ""))
                            home_n = obj.get("homeTeam", obj.get("home", ""))
                            ac = _sl_code(away_n)
                            hc = _sl_code(home_n)
                            if ac and hc:
                                result[f"{ac}-{hc}"] = _make_odds_entry(
                                    ah, hh, source="台灣運彩",
                                    note="台灣運彩 Playwright",
                                )
                    except Exception:
                        pass

        # 也嘗試 HTML 解析
        if not result:
            result = _scrape_sl_html_from_rendered(soup)

        if result:
            log.info("台灣運彩 Playwright: %d 場賠率", len(result))
        return result
    except Exception as e:
        log.debug("台灣運彩 Playwright 失敗: %s", e)
        return {}


def _scrape_sl_html_from_rendered(soup: BeautifulSoup) -> dict:
    result = {}
    for row in soup.find_all(["tr", "div"], class_=lambda c: c and any(
            x in c for x in ("game", "match", "event", "odd"))):
        text = row.get_text(" ", strip=True)
        found = [_SL_TEAM_MAP[k] for k in _SL_TEAM_MAP if k in text]
        if len(found) < 2:
            continue
        nums = []
        for x in text.replace("@", " ").split():
            try:
                v = float(x)
                if 1.01 < v < 20.0:
                    nums.append(v)
            except ValueError:
                pass
        if len(nums) >= 2:
            result[f"{found[0]}-{found[1]}"] = _make_odds_entry(
                nums[0], nums[1], source="台灣運彩", note="HTML 解析",
            )
    return result


def _scrape_oddsportal(session: requests.Session) -> dict:
    """oddsportal CPBL 賠率（備援）"""
    try:
        r = session.get(_OP_URL, timeout=15, headers={
            **_ODDS_HEADERS,
            "Referer": "https://www.oddsportal.com/",
        })
        if r.status_code == 403:
            log.warning("oddsportal 403")
            return {}
        r.raise_for_status()
        soup   = BeautifulSoup(r.text, "html.parser")
        result = {}

        # oddsportal 通常用 JSON 嵌入頁面
        for script in soup.find_all("script"):
            text = script.string or ""
            if '"odds"' in text and '"home-odds"' in text.replace("-", "_").replace('"', '"'):
                try:
                    import re as _re
                    m = _re.search(r'var\s+page_vars\s*=\s*(\{.*?\});', text, _re.DOTALL)
                    if m:
                        data = json.loads(m.group(1))
                        for ev in data.get("events", {}).values():
                            home_n = ev.get("home_name", "")
                            away_n = ev.get("away_name", "")
                            hc = _op_code(home_n)
                            ac = _op_code(away_n)
                            if hc and ac:
                                odds_raw = ev.get("odds", {})
                                ah = float(odds_raw.get("away", 1.90))
                                hh = float(odds_raw.get("home", 1.90))
                                result[f"{ac}-{hc}"] = _make_odds_entry(
                                    ah, hh, source="oddsportal",
                                    note="oddsportal.com",
                                )
                except Exception:
                    pass

        # 也嘗試 HTML 表格
        if not result:
            for row in soup.select(".eventRow, [class*='eventRow']"):
                teams = row.select(".participant-name, .team-name")
                if len(teams) < 2:
                    continue
                ac = _op_code(teams[0].get_text(strip=True))
                hc = _op_code(teams[1].get_text(strip=True))
                if not ac or not hc:
                    continue
                odds_els = row.select(".odds-nowrp, .oddsValueInner, [class*='odds']")
                nums = []
                for el in odds_els:
                    try:
                        nums.append(float(el.get_text(strip=True)))
                    except ValueError:
                        pass
                if len(nums) >= 2:
                    result[f"{ac}-{hc}"] = _make_odds_entry(
                        nums[0], nums[1], source="oddsportal",
                        note="oddsportal HTML",
                    )
        if result:
            log.info("oddsportal: %d 場賠率", len(result))
        return result
    except Exception as e:
        log.debug("oddsportal 失敗: %s", e)
        return {}


def scrape_odds(game_date_str: str, session: requests.Session,
                use_playwright: bool = True) -> dict:
    """
    抓今日 CPBL 賠率，嘗試順序：
      1. 台灣運彩 API
      2. 台灣運彩 HTML
      3. 台灣運彩 Playwright（JS 渲染）
      4. oddsportal

    回傳 {game_key: odds_dict}
    """
    print("  嘗試台灣運彩 API...")
    result = _scrape_sl_api(session)
    if result:
        return result

    print("  嘗試台灣運彩 HTML...")
    result = _scrape_sl_html(session)
    if result:
        return result

    if use_playwright:
        print("  嘗試台灣運彩 Playwright（JS 渲染）...")
        result = _scrape_sl_playwright(game_date_str)
        if result:
            return result

    print("  嘗試 oddsportal...")
    result = _scrape_oddsportal(session)
    return result


def save_odds(odds: dict, game_date_str: str, source: str = "local", dry: bool = False):
    payload = {
        "game_date":  game_date_str,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source":     source,
        "odds":       odds,
    }
    if dry:
        log.info("[DRY] 會寫入 %s（%d 場）", ODDS_FILE, len(odds))
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ODDS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("寫入 %s（%d 場）", ODDS_FILE, len(odds))


# ─────────────────────────────────────────────────────────────
# 6. 合併 + 寫入
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
    ap.add_argument("--dry",          action="store_true", help="只爬不寫入")
    ap.add_argument("--push",         action="store_true", help="完成後自動 git commit + push")
    ap.add_argument("--year",         type=int, default=datetime.date.today().year)
    ap.add_argument("--months",       nargs="+", type=int,
                    default=[datetime.date.today().month,
                             min(12, datetime.date.today().month + 1)],
                    help="要抓的月份（預設：本月+下月）")
    ap.add_argument("--skip-schedule", action="store_true", help="跳過賽程爬取")
    ap.add_argument("--skip-odds",     action="store_true", help="跳過賠率爬取")
    ap.add_argument("--odds-only",     action="store_true", help="只爬賠率，不爬投手/賽程")
    ap.add_argument("--no-playwright", action="store_true", help="停用 Playwright（只用靜態 HTTP）")
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

    today_str = datetime.date.today().isoformat()
    live_stats = {}

    # ── 投手成績：多來源 ──
    if not args.odds_only:
        print("\n[1/4] 抓取投手成績...")
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
        for name in list(merged.keys())[:3]:
            p = merged[name]
            print(f"  {name}: ERA={p.get('era')} FIP={p.get('fip')} K%={p.get('k_pct')}% BB%={p.get('bb_pct')}%")

        # ── 儲存投手成績 ──
        print("\n[2/4] 儲存投手成績...")
        save_stats(merged, dry=args.dry)

        # ── 賽程 ──
        if not args.skip_schedule:
            print(f"\n[3/4] 抓取 {args.months} 月份賽程...")
            games = scrape_schedule(args.year, args.months, session)
            update_schedule(games, dry=args.dry)
        else:
            print("\n[3/4] 跳過賽程爬取")
    else:
        print("\n[--odds-only] 跳過投手成績與賽程爬取")

    # ── 賠率 ──
    step = "4/4" if not args.odds_only else "1/1"
    if not args.skip_odds:
        print(f"\n[{step}] 抓取今日賠率（{today_str}）...")
        use_pw = not args.no_playwright
        odds = scrape_odds(today_str, session, use_playwright=use_pw)
        if odds:
            sources = {v.get("source", "?") for v in odds.values()}
            print(f"  ✅ {len(odds)} 場賠率 [來源: {', '.join(sources)}]")
            for k, v in list(odds.items())[:3]:
                ah = v.get("curr_away_odds", "-")
                hh = v.get("curr_home_odds", "-")
                print(f"  {k}: 客隊 {ah} / 主隊 {hh} (vig {v.get('vig_pct','?')}%)")
            source_str = ", ".join(sources)
        else:
            print("  ⚠️ 所有賠率來源失敗")
            print("  提示：")
            print("    - 確認在個人電腦（非雲端機房）執行")
            print("    - 嘗試：python scripts/update_stats.py --odds-only --no-playwright")
            print("    - 台灣運彩需要 VPN 或居家網路（封鎖雲端 IP）")
            source_str = "none"
            odds = {}

        print(f"\n[{step}] 儲存賠率...")
        save_odds(odds, today_str, source=source_str, dry=args.dry)
    else:
        print(f"\n[{step}] 跳過賠率爬取")

    # ── git push ──
    if args.push and not args.dry:
        print("\n[git] commit + push...")
        import subprocess
        files_to_add = []
        if not args.odds_only:
            files_to_add += ["data/pitcher_stats.json", "data/schedule.json"]
        if not args.skip_odds:
            files_to_add.append("data/odds_today.json")
        subprocess.run(["git", "add"] + files_to_add,
                       cwd=os.path.join(os.path.dirname(__file__), ".."),
                       check=False)
        subprocess.run(["git", "commit", "-m",
                        f"data: update stats+odds {today_str} [skip ci]"],
                       cwd=os.path.join(os.path.dirname(__file__), ".."),
                       check=False)
        subprocess.run(["git", "push"],
                       cwd=os.path.join(os.path.dirname(__file__), ".."),
                       check=False)
        print("  ✅ 推送完成")

    print("\n完成！")


if __name__ == "__main__":
    main()
