"""
NPB / KBO 賠率模組

資料來源優先順序：
  1. data/odds_today.json（本地 scripts/update_stats.py 抓取後儲存）
  2. The Odds API  (the-odds-api.com)  — KBO: baseball_kbo（需 ODDS_API_KEY）
  3. Mock 資料  — Demo 模式 / 以上都失敗時

The Odds API 免費方案：500 req/月 (夠每天用)
申請 Key：https://the-odds-api.com/  → Get API Key (Free)
"""
import os
import re
import json
import logging
import requests
from bs4 import BeautifulSoup
from datetime import date, timezone, datetime
from typing import Optional

log = logging.getLogger(__name__)

# ── The Odds API ──────────────────────────────
_ODDS_API_BASE   = "https://api.the-odds-api.com/v4"
_KBO_SPORT_KEY   = "baseball_kbo"         # KBO は The Odds API でサポート
_PREFERRED_BMS   = ["pinnacle", "bet365", "betway", "unibet"]  # 越前越優先

# The Odds API 英文隊名 → 我們的代碼  (KBO)
_EN_TO_CODE: dict[str, str] = {
    # KBO
    "samsung lions":        "SSL",
    "lg twins":             "LGT",
    "doosan bears":         "DSB",
    "kt wiz":               "KTW",
    "ssg landers":          "SSG",
    "nc dinos":             "NCD",
    "kia tigers":           "KIA",
    "lotte giants":         "LTG",
    "hanwha eagles":        "HWE",
    "kiwoom heroes":        "KWH",
    # NPB (The Odds API may carry these under baseball_npb or similar)
    "yomiuri giants":       "GNT",
    "hanshin tigers":       "HNS",
    "hiroshima carp":       "HRC",
    "yokohama dena baystars":"YDB",
    "yakult swallows":      "YKL",
    "chunichi dragons":     "CND",
    "fukuoka softbank hawks":"SBH",
    "orix buffaloes":       "ORX",
    "rakuten eagles":       "RKT",
    "chiba lotte marines":  "LTT",
    "saitama seibu lions":  "SEI",
    "hokkaido nippon-ham fighters": "HAM",
}

# ── 台灣運彩 (已不支援 NPB/KBO，保留架構供未來擴展) ────
_SL_URL = "https://www.sportslottery.com.tw/sport/baseball"
_SL_API = "https://api2.sportslottery.com.tw/sport/events?sport=baseball&league=kbo"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": "https://www.sportslottery.com.tw/",
}

# ── 開盤賠率快取 (當天第一次抓 = 開盤) ────────
_opening_cache: dict[str, dict] = {}


# ──────────────────────────────────────────────
# Mock 資料  (game_key = "AWAY_CODE-HOME_CODE")
# ──────────────────────────────────────────────
def _mock(away_odds: float, home_odds: float, total: float = 8.5, note: str = "") -> dict:
    """Generate a mock odds entry from decimal odds."""
    home_impl = round(1 / home_odds * 100, 1)
    away_impl = round(1 / away_odds * 100, 1)
    return {
        "source": "mock",
        "open_away_odds": away_odds,
        "open_home_odds": home_odds,
        "curr_away_odds": away_odds,
        "curr_home_odds": home_odds,
        "run_line": -1.5,
        "rl_home_odds": 1.90,
        "rl_away_odds": 1.90,
        "total": total,
        "over_odds": 1.90,
        "under_odds": 1.90,
        "public_home_pct": round(home_impl / (home_impl + away_impl) * 100),
        "public_away_pct": round(away_impl / (home_impl + away_impl) * 100),
        "vig_pct": 7.5,
        "bookmakers": ["mock"],
        "note": note,
    }


MOCK_ODDS: dict[str, dict] = {
    # ── NPB Central League ─────────────────────
    "YDB-GNT": _mock(2.15, 1.75, 7.5, "橫浜主場打者有利，大分進攻"),
    "HNS-HRC": _mock(1.88, 1.98, 7.0, "甲子園投手有利"),
    "YKL-CND": _mock(1.95, 1.92, 8.0, ""),
    "GNT-YKL": _mock(1.72, 2.18, 7.5, "巨人主場強勢"),
    "HRC-YDB": _mock(2.05, 1.82, 7.5, "廣島主場均衡"),
    "CND-HNS": _mock(2.20, 1.70, 7.0, ""),
    "GNT-HNS": _mock(1.95, 1.92, 7.5, "頂級對決"),
    "GNT-HRC": _mock(1.80, 2.08, 7.5, ""),
    "HNS-YDB": _mock(1.92, 1.95, 8.0, ""),
    "YDB-HNS": _mock(2.10, 1.78, 8.0, ""),
    "HRC-GNT": _mock(2.12, 1.76, 7.5, ""),
    "YDB-YKL": _mock(1.75, 2.15, 8.0, ""),
    "YKL-GNT": _mock(2.35, 1.62, 8.0, ""),
    "CND-GNT": _mock(2.40, 1.60, 7.5, ""),
    "CND-YDB": _mock(2.25, 1.68, 7.5, ""),
    # ── NPB Pacific League ─────────────────────
    "ORX-SBH": _mock(2.25, 1.68, 7.0, "兩強對決，投手戰"),
    "LTT-RKT": _mock(1.92, 1.95, 8.5, ""),
    "SEI-HAM": _mock(1.98, 1.90, 9.0, "エスコン打者天堂"),
    "SBH-LTT": _mock(1.72, 2.18, 7.5, "ソフトバンク主場強"),
    "RKT-SEI": _mock(1.85, 2.02, 8.0, ""),
    "HAM-ORX": _mock(2.05, 1.82, 8.5, ""),
    "SBH-HAM": _mock(1.68, 2.22, 7.5, ""),
    "ORX-RKT": _mock(1.88, 1.98, 7.5, ""),
    "LTT-SEI": _mock(1.90, 1.96, 8.5, ""),
    "SBH-ORX": _mock(1.75, 2.12, 7.0, ""),
    # ── KBO ─────────────────────────────────────
    "KIA-LGT": _mock(2.05, 1.82, 9.5, "兩強對決"),
    "KTW-SSL": _mock(1.92, 1.95, 9.0, ""),
    "NCD-SSG": _mock(2.10, 1.78, 9.5, ""),
    "HWE-DSB": _mock(1.98, 1.90, 9.0, ""),
    "LTG-KWH": _mock(1.88, 1.98, 9.5, ""),
    "LGT-SSL": _mock(1.72, 2.18, 10.0, "LG 主場強勢"),
    "SSG-KTW": _mock(1.90, 1.96, 9.5, ""),
    "KIA-NCD": _mock(1.78, 2.10, 9.5, ""),
    "DSB-KWH": _mock(1.85, 2.02, 9.0, ""),
    "KTW-HWE": _mock(1.82, 2.05, 9.5, ""),
    "LGT-KIA": _mock(1.75, 2.12, 10.0, "首位爭奪"),
    "SSL-SSG": _mock(1.95, 1.92, 9.5, ""),
    "NCD-KTW": _mock(2.00, 1.88, 9.0, ""),
    "KWH-DSB": _mock(1.98, 1.90, 9.5, ""),
    "HWE-LTG": _mock(1.95, 1.92, 9.0, ""),
    "SSG-LGT": _mock(2.08, 1.80, 9.5, ""),
    "KTW-KIA": _mock(2.12, 1.76, 9.5, ""),
    "SSL-LGT": _mock(2.20, 1.72, 10.0, ""),
    "NCD-KIA": _mock(2.15, 1.75, 9.5, ""),
    "KWH-SSG": _mock(2.18, 1.72, 9.5, ""),
    "LTG-SSL": _mock(2.05, 1.82, 9.5, ""),
    "HWE-NCD": _mock(2.10, 1.78, 9.0, ""),
    "DSB-LGT": _mock(2.25, 1.68, 9.5, ""),
}


# ──────────────────────────────────────────────
# The Odds API  ★ 主要來源
# ──────────────────────────────────────────────

class TheOddsAPIClient:
    """
    The Odds API 客戶端。
    免費方案：500 req/month
    每次呼叫費用：1 req (h2h) + 1 req (spreads) + 1 req (totals) = 3 req/天
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._s      = requests.Session()
        self._s.headers.update({"User-Agent": "CPBL-Protector/1.0"})

    # ── 取得今日所有 KBO 賽事賠率 ───────────
    def fetch_all(self) -> dict[str, dict]:
        """
        回傳 {game_key: odds_dict}，game_key = "AWAY_CODE-HOME_CODE"
        只抓 h2h（1次 API 請求），省配額。
        spreads/totals 留空，由 mock 填補。
        """
        # 只拿 h2h（勝負），節省 API 配額
        h2h_data = self._fetch_market("h2h")
        if not h2h_data:
            return {}

        spreads_map = {}
        totals_map  = {}

        result: dict[str, dict] = {}
        for event in h2h_data:
            home_en = event.get("home_team", "").lower()
            away_en = event.get("away_team", "").lower()
            home_code = _en_to_code(home_en)
            away_code = _en_to_code(away_en)
            if not home_code or not away_code:
                log.debug(f"Unknown team: {home_en} / {away_en}")
                continue

            game_key = f"{away_code}-{home_code}"
            parsed   = self._parse_event(
                event,
                spreads_map.get(event["id"]),
                totals_map.get(event["id"]),
                home_code, away_code,
                event.get("home_team", ""), event.get("away_team", ""),
            )
            if parsed:
                # 第一次抓的 = 開盤賠率（快取起來）
                if game_key not in _opening_cache:
                    _opening_cache[game_key] = {
                        "open_home_odds": parsed["curr_home_odds"],
                        "open_away_odds": parsed["curr_away_odds"],
                    }
                parsed["open_home_odds"] = _opening_cache[game_key]["open_home_odds"]
                parsed["open_away_odds"] = _opening_cache[game_key]["open_away_odds"]
                result[game_key] = parsed

        log.info(f"The Odds API: {len(result)} KBO games fetched")
        return result

    def _fetch_market(self, market: str) -> list:
        url = f"{_ODDS_API_BASE}/sports/{_KBO_SPORT_KEY}/odds/"
        params = {
            "apiKey":      self.api_key,
            "regions":     "eu,us,uk,au",
            "markets":     market,
            "oddsFormat":  "decimal",
            "dateFormat":  "iso",
        }
        try:
            resp = self._s.get(url, params=params, timeout=10)
            if resp.status_code == 401:
                log.error("The Odds API: 無效的 API Key")
                return []
            if resp.status_code == 422:
                log.warning(f"The Odds API: KBO 不在此方案涵蓋範圍（{resp.text[:100]}）")
                return []
            resp.raise_for_status()
            remaining = resp.headers.get("x-requests-remaining", "?")
            log.info(f"The Odds API [{market}] OK — 剩餘配額: {remaining}")
            return resp.json()
        except requests.RequestException as e:
            log.warning(f"The Odds API [{market}] 失敗: {e}")
            return []

    def _parse_event(
        self, h2h_ev: dict, sp_ev: dict | None, tot_ev: dict | None,
        home_code: str, away_code: str,
        home_en: str, away_en: str,
    ) -> Optional[dict]:
        bms_used = []

        # ── h2h 賠率 (best available across bookmakers) ──
        home_h2h = away_h2h = None
        for bm in _sorted_bms(h2h_ev.get("bookmakers", [])):
            for mkt in bm.get("markets", []):
                if mkt["key"] != "h2h":
                    continue
                o = {x["name"].lower(): x["price"] for x in mkt["outcomes"]}
                h = o.get(home_en.lower())
                a = o.get(away_en.lower())
                if h and a:
                    if home_h2h is None or h > home_h2h:
                        home_h2h = h
                    if away_h2h is None or a > away_h2h:
                        away_h2h = a
                    bms_used.append(bm["title"])
                    break

        if not home_h2h:
            return None

        # ── 讓分 (run line) ──────────────────────
        run_line = rl_home = rl_away = None
        if sp_ev:
            for bm in _sorted_bms(sp_ev.get("bookmakers", [])):
                for mkt in bm.get("markets", []):
                    if mkt["key"] != "spreads":
                        continue
                    for out in mkt["outcomes"]:
                        if out["name"].lower() == home_en.lower():
                            run_line = out.get("point")
                            rl_home  = out["price"]
                        elif out["name"].lower() == away_en.lower():
                            rl_away = out["price"]
                    if rl_home:
                        break
                if rl_home:
                    break

        # ── 大小分 (totals) ───────────────────────
        total_line = over_o = under_o = None
        if tot_ev:
            for bm in _sorted_bms(tot_ev.get("bookmakers", [])):
                for mkt in bm.get("markets", []):
                    if mkt["key"] != "totals":
                        continue
                    for out in mkt["outcomes"]:
                        if out["name"] == "Over":
                            total_line = out.get("point")
                            over_o     = out["price"]
                        elif out["name"] == "Under":
                            under_o = out["price"]
                    if over_o:
                        break
                if over_o:
                    break

        # ── 估計抽水率 ────────────────────────────
        vig = round((1/home_h2h + 1/away_h2h - 1) * 100, 2) if home_h2h and away_h2h else 7.5

        note = f"來源：{', '.join(set(bms_used[:3]))} via The Odds API"

        return {
            "source":           "the-odds-api",
            "curr_home_odds":   round(home_h2h, 3),
            "curr_away_odds":   round(away_h2h, 3),
            "run_line":         run_line,
            "rl_home_odds":     round(rl_home,  3) if rl_home  else None,
            "rl_away_odds":     round(rl_away,  3) if rl_away  else None,
            "total":            total_line,
            "over_odds":        round(over_o,   3) if over_o   else None,
            "under_odds":       round(under_o,  3) if under_o  else None,
            "public_home_pct":  50,   # The Odds API 免費版無投注比例
            "public_away_pct":  50,
            "vig_pct":          vig,
            "bookmakers":       list(set(bms_used)),
            "note":             note,
        }

    # ── 查詢剩餘配額 ──────────────────────────
    def check_quota(self) -> dict:
        url = f"{_ODDS_API_BASE}/sports"
        try:
            resp = self._s.get(url, params={"apiKey": self.api_key}, timeout=8)
            return {
                "remaining":  resp.headers.get("x-requests-remaining", "?"),
                "used":       resp.headers.get("x-requests-used", "?"),
                "status":     resp.status_code,
            }
        except Exception as e:
            return {"error": str(e)}


def _en_to_code(name_lower: str) -> Optional[str]:
    for k, v in _EN_TO_CODE.items():
        if k in name_lower:
            return v
    return None


def _sorted_bms(bookmakers: list) -> list:
    """偏好 Pinnacle > Bet365 > 其他（Pinnacle 賠率最無抽水）"""
    def rank(bm):
        k = bm.get("key", "")
        for i, pref in enumerate(_PREFERRED_BMS):
            if k == pref:
                return i
        return len(_PREFERRED_BMS)
    return sorted(bookmakers, key=rank)


# ──────────────────────────────────────────────
# 台灣運彩爬蟲  (Fallback #2)
# ──────────────────────────────────────────────

class SportslotteryScraper:
    def __init__(self):
        self._s = requests.Session()
        self._s.headers.update(_HEADERS)

    def fetch(self, away_code: str, home_code: str) -> Optional[dict]:
        try:
            r = self._try_api(away_code, home_code)
            if r:
                return r
        except Exception:
            pass
        try:
            r = self._try_html(away_code, home_code)
            if r:
                return r
        except Exception:
            pass
        return None

    def _try_api(self, away: str, home: str) -> Optional[dict]:
        resp = self._s.get(_SL_API, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        for event in data.get("events", []):
            teams = event.get("teams", [])
            names = [t.get("name", "") for t in teams]
            if _team_match(away, names) and _team_match(home, names):
                return _parse_sl_event(event, away, home)
        return None

    def _try_html(self, away: str, home: str) -> Optional[dict]:
        resp = self._s.get(_SL_URL, timeout=10)
        resp.raise_for_status()
        return _parse_sl_html(BeautifulSoup(resp.text, "html.parser"), away, home)


def _team_match(code: str, names: list[str]) -> bool:
    from .mock_data import TEAM_INFO
    full  = TEAM_INFO.get(code, {}).get("name", "")
    short = TEAM_INFO.get(code, {}).get("short", "")
    return any(full in n or short in n for n in names)


def _parse_sl_event(event: dict, away: str, home: str) -> Optional[dict]:
    result: dict = {"source": "sportslottery"}
    for o in event.get("odds", []):
        kind = o.get("kind", "")
        if kind == "win":
            result.update({
                "curr_away_odds": float(o.get("awayOdds", 1.90)),
                "curr_home_odds": float(o.get("homeOdds", 1.90)),
                "open_away_odds": float(o.get("openAwayOdds", o.get("awayOdds", 1.90))),
                "open_home_odds": float(o.get("openHomeOdds", o.get("homeOdds", 1.90))),
            })
        elif kind == "runline":
            result["run_line"]     = float(o.get("line", -1.5))
            result["rl_home_odds"] = float(o.get("homeOdds", 1.90))
            result["rl_away_odds"] = float(o.get("awayOdds", 1.90))
        elif kind == "total":
            result["total"]      = float(o.get("line", 8.5))
            result["over_odds"]  = float(o.get("overOdds", 1.90))
            result["under_odds"] = float(o.get("underOdds", 1.90))
    result.setdefault("public_home_pct", 50)
    result.setdefault("public_away_pct", 50)
    result.setdefault("vig_pct", 7.5)
    result.setdefault("bookmakers", ["台灣運彩"])
    result.setdefault("note", "來自台灣運彩 API")
    return result if "curr_home_odds" in result else None


def _parse_sl_html(soup: BeautifulSoup, away: str, home: str) -> Optional[dict]:
    from .mock_data import TEAM_INFO
    hn = TEAM_INFO.get(home, {}).get("short", "")
    an = TEAM_INFO.get(away, {}).get("short", "")
    for row in soup.select(".game-row, .match-item, tr"):
        text = row.get_text()
        if hn in text and an in text:
            vals = []
            for el in row.select(".odds, .odd-value, td.odds"):
                try:
                    vals.append(float(el.get_text(strip=True)))
                except ValueError:
                    pass
            if len(vals) >= 2:
                return {
                    "source":          "sportslottery-html",
                    "curr_away_odds":  vals[0],
                    "curr_home_odds":  vals[1],
                    "open_away_odds":  vals[0],
                    "open_home_odds":  vals[1],
                    "run_line":        -1.5,
                    "rl_home_odds":     1.90,
                    "rl_away_odds":     1.90,
                    "total":            8.5,
                    "over_odds":        1.90,
                    "under_odds":       1.90,
                    "public_home_pct":  50,
                    "public_away_pct":  50,
                    "vig_pct":          7.5,
                    "bookmakers":      ["台灣運彩"],
                    "note":            "來自台灣運彩網頁（HTML 解析）",
                }
    return None


# ──────────────────────────────────────────────
# 統一入口  OddsFetcher
# ──────────────────────────────────────────────

class OddsFetcher:
    """
    優先順序：The Odds API → 台灣運彩 → Mock
    用法：
        fetcher = OddsFetcher()
        all_odds = fetcher.fetch_all()   # {game_key: odds_dict}
        odds = fetcher.get(away, home)
    """
    def __init__(self):
        api_key = os.environ.get("ODDS_API_KEY", "")
        self._odds_api    = TheOddsAPIClient(api_key) if api_key else None
        self._sl_scraper  = SportslotteryScraper()
        self._cache: dict[str, dict] = {}

    def fetch_all(self, game_date: str = None) -> dict[str, dict]:
        """一次抓今日所有比賽賠率，快取起來

        優先順序：
          0. data/odds_today.json（本地腳本 scripts/update_stats.py 抓取後儲存）
          1. The Odds API（需 ODDS_API_KEY）
          2. Mock 資料
        """
        if game_date is None:
            game_date = str(date.today())

        # 0. 本地預存賠率（由 scripts/update_stats.py 在個人電腦執行後產生）
        _odds_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "data", "odds_today.json"
        )
        if os.path.exists(_odds_file):
            try:
                with open(_odds_file, encoding="utf-8") as f:
                    saved = json.load(f)
                if saved.get("game_date") == game_date and saved.get("odds"):
                    self._cache = saved["odds"]
                    log.info(
                        "OddsFetcher: 使用本地 odds_today.json (%s) — %d 場 [來源: %s]",
                        game_date, len(self._cache), saved.get("source", "?"),
                    )
                    return self._cache
                else:
                    log.info(
                        "OddsFetcher: odds_today.json 日期 %s ≠ 今日 %s，略過",
                        saved.get("game_date", "?"), game_date,
                    )
            except Exception as e:
                log.warning("OddsFetcher: 讀取 odds_today.json 失敗 → %s", e)

        # 1. The Odds API
        if self._odds_api:
            try:
                data = self._odds_api.fetch_all()
                if data:
                    self._cache = data
                    log.info("OddsFetcher: The Odds API 成功，%d 場比賽", len(data))
                    return data
            except Exception as e:
                log.warning("OddsFetcher: The Odds API 失敗 → %s", e)

        log.info("OddsFetcher: 使用 Mock 資料（執行 scripts/update_stats.py --odds 可取得真實賠率）")
        self._cache = dict(MOCK_ODDS)
        return self._cache

    def get(self, away_code: str, home_code: str) -> Optional[dict]:
        """取得單場賠率（先查快取，再個別抓）"""
        key = f"{away_code}-{home_code}"

        # 快取命中
        if key in self._cache:
            return self._cache[key]

        # The Odds API 逐場模式（如果 fetch_all 沒事先跑）
        if self._odds_api:
            try:
                all_data = self._odds_api.fetch_all()
                self._cache.update(all_data)
                if key in self._cache:
                    return self._cache[key]
            except Exception:
                pass

        # 台灣運彩
        try:
            r = self._sl_scraper.fetch(away_code, home_code)
            if r:
                self._cache[key] = r
                return r
        except Exception:
            pass

        # Mock fallback
        return MOCK_ODDS.get(key)

    def quota(self) -> dict:
        """查詢 The Odds API 剩餘配額"""
        if self._odds_api:
            return self._odds_api.check_quota()
        return {"error": "ODDS_API_KEY 未設定"}


# ──────────────────────────────────────────────
# 盤口分析（不變）
# ──────────────────────────────────────────────

# 保留舊介面供 predictor 呼叫
OddsScraper = OddsFetcher   # alias


def analyze(odds: dict, model_home_prob: float) -> dict:
    """
    輸入賠率資料 + 模型主隊勝率
    回傳盤口分析結果，advantage 範圍 -50~+50
    """
    h   = float(odds.get("curr_home_odds", 1.90))
    a   = float(odds.get("curr_away_odds", 1.90))
    oh  = float(odds.get("open_home_odds", h))
    oa  = float(odds.get("open_away_odds", a))
    pub_h = float(odds.get("public_home_pct", 50)) / 100.0

    raw_h = 1.0 / h
    raw_a = 1.0 / a
    market_prob = raw_h / (raw_h + raw_a)

    value_gap = model_home_prob - market_prob

    h_move = oh - h        # 正 = 縮短 = 看好主隊
    a_move = oa - a

    rlm_against_home = (pub_h > 0.55 and h_move < -0.03)
    rlm_for_home     = (pub_h < 0.45 and a_move < -0.03)

    run_line = float(odds.get("run_line") or -1.5)
    rl_signal = max(-1.0, min(1.0, -run_line / 3.0))

    adv = 0.0
    adv += value_gap * 100.0
    adv += h_move    * 20.0
    adv += rl_signal * 15.0
    if rlm_for_home:
        adv += 12.0
    elif rlm_against_home:
        adv -= 12.0
    adv = max(-50.0, min(50.0, adv))

    signals = []
    if abs(value_gap) > 0.08:
        if value_gap > 0:
            signals.append(f"📈 模型比市場高估主隊 {value_gap*100:.0f}% (Value)")
        else:
            signals.append(f"📉 市場比模型更看好主隊 {abs(value_gap)*100:.0f}%")
    if abs(h_move) > 0.03:
        if h_move > 0:
            signals.append(f"📉 主隊賠率縮短 {oh}→{h} (莊家看好主隊)")
        else:
            signals.append(f"📈 主隊賠率拉長 {oh}→{h} (莊家看衰主隊)")
    if rlm_for_home:
        signals.append("⚡ 逆向盤口：資金流入主隊")
    elif rlm_against_home:
        signals.append("⚡ 逆向盤口：資金流入客隊")

    # 莊家資訊
    bms = odds.get("bookmakers", [])
    source = odds.get("source", "?")
    bm_str = f"來源：{source}  莊家：{', '.join(bms[:3])}" if bms else f"來源：{source}"

    return {
        "market_home_prob": round(market_prob * 100, 1),
        "value_gap":        round(value_gap * 100, 1),
        "h_movement":       round(h_move, 3),
        "a_movement":       round(a_move, 3),
        "rlm_for_home":     rlm_for_home,
        "rlm_against_home": rlm_against_home,
        "signals":          signals,
        "advantage":        round(adv, 1),
        "detail": (
            f"主隊賠率 {h} (開 {oh}) | 客隊賠率 {a} (開 {oa}) | "
            f"讓分 {run_line:+.1f} | "
            f"大小 {odds.get('total', '-')} | "
            f"公眾 主{int(pub_h*100)}% 客{100-int(pub_h*100)}% | "
            f"{odds.get('note', '')} | {bm_str}"
        ),
    }
