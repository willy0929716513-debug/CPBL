"""
CPBL 賠率模組

資料來源優先順序：
  1. The Odds API  (the-odds-api.com)  — 需設定 ODDS_API_KEY 環境變數
  2. 台灣運彩 API  (sportslottery.com.tw)  — 自動 fallback
  3. Mock 資料  — Demo 模式 / 以上都失敗時

The Odds API 免費方案：500 req/月 (夠每天用)
申請 Key：https://the-odds-api.com/  → Get API Key (Free)
"""
import os
import re
import logging
import requests
from bs4 import BeautifulSoup
from datetime import date, timezone, datetime
from typing import Optional

log = logging.getLogger(__name__)

# ── The Odds API ──────────────────────────────
_ODDS_API_BASE   = "https://api.the-odds-api.com/v4"
_CPBL_SPORT_KEY  = "baseball_cpbl"        # CPBL sport key
_PREFERRED_BMS   = ["pinnacle", "bet365", "betway", "unibet"]  # 越前越優先

# The Odds API 英文隊名 → 我們的代碼
_EN_TO_CODE: dict[str, str] = {
    "rakuten monkeys":              "WL",
    "ctbc brothers":                "AEL",
    "fubon guardians":              "FG",
    "uni-president 7-eleven lions": "CT",
    "uni president 7-eleven lions": "CT",
    "tsg hawks":                    "TSG",
    "taiwan steel hawks":           "TSG",
    "taiwan steel guardians":       "TSG",
}

# ── 台灣運彩 ──────────────────────────────────
_SL_URL = "https://www.sportslottery.com.tw/sport/baseball/cpbl"
_SL_API = "https://api2.sportslottery.com.tw/sport/events?sport=baseball&league=cpbl"

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
MOCK_ODDS: dict[str, dict] = {
    "FG-WL": {
        "source":            "demo",
        "open_away_odds":    2.30,
        "open_home_odds":    1.65,
        "curr_away_odds":    2.45,
        "curr_home_odds":    1.58,
        "run_line":         -1.5,
        "rl_home_odds":      1.82,
        "rl_away_odds":      2.00,
        "total":             8.5,
        "over_odds":         1.85,
        "under_odds":        1.95,
        "public_home_pct":   62,
        "public_away_pct":   38,
        "vig_pct":           7.5,
        "bookmakers":       ["demo"],
        "note": "主隊賠率從 1.65 縮至 1.58 → 莊家更看好主隊；主隊讓 1.5 分受青睞",
    },
    "TSG-AEL": {
        "source":            "demo",
        "open_away_odds":    2.20,
        "open_home_odds":    1.72,
        "curr_away_odds":    2.15,
        "curr_home_odds":    1.72,
        "run_line":         -1.0,
        "rl_home_odds":      1.88,
        "rl_away_odds":      1.92,
        "total":             7.5,
        "over_odds":         1.90,
        "under_odds":        1.90,
        "public_home_pct":   55,
        "public_away_pct":   45,
        "vig_pct":           7.5,
        "bookmakers":       ["demo"],
        "note": "盤口穩定；客隊賠率微縮（2.20→2.15）有部分資金流入客隊",
    },
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

    # ── 取得今日所有 CPBL 賽事賠率 ───────────
    def fetch_all(self) -> dict[str, dict]:
        """
        回傳 {game_key: odds_dict}，game_key = "AWAY_CODE-HOME_CODE"
        同時抓 h2h / spreads / totals，合併成一筆
        """
        # 先拿 h2h（勝負）
        h2h_data = self._fetch_market("h2h")
        if not h2h_data:
            return {}

        # 再拿 spreads（讓分）和 totals（大小分）
        spreads_data = self._fetch_market("spreads")
        totals_data  = self._fetch_market("totals")

        spreads_map = {e["id"]: e for e in spreads_data}
        totals_map  = {e["id"]: e for e in totals_data}

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

        log.info(f"The Odds API: {len(result)} CPBL games fetched")
        return result

    def _fetch_market(self, market: str) -> list:
        url = f"{_ODDS_API_BASE}/sports/{_CPBL_SPORT_KEY}/odds/"
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
                log.warning(f"The Odds API: CPBL 不在此方案涵蓋範圍（{resp.text[:100]}）")
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

    def fetch_all(self) -> dict[str, dict]:
        """一次抓今日所有比賽賠率，快取起來"""
        if self._odds_api:
            try:
                data = self._odds_api.fetch_all()
                if data:
                    self._cache = data
                    log.info(f"OddsFetcher: The Odds API 成功，{len(data)} 場比賽")
                    return data
            except Exception as e:
                log.warning(f"OddsFetcher: The Odds API 失敗 → {e}")
        log.info("OddsFetcher: 使用 Mock 資料")
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
