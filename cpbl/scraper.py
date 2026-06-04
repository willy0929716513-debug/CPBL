"""
CPBL 網頁爬蟲 — 一軍 (kind=A) 賽程
策略：requests → Playwright → 拋出例外（呼叫端決定 fallback）
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
from datetime import date
from typing import Optional

log = logging.getLogger(__name__)

BASE = "https://www.cpbl.com.tw"
WEATHER_API = "https://wttr.in"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# 球隊中文名稱 → 代碼
TEAM_CODE_MAP = {
    "中信兄弟": "AEL", "兄弟": "AEL",
    "統一7-ELEVEn獅": "CT", "統一獅": "CT", "統一": "CT",
    "富邦悍將": "FG", "悍將": "FG", "富邦": "FG",
    "樂天桃猿": "WL", "桃猿": "WL", "樂天": "WL",
    "台鋼雄鷹": "TSG", "雄鷹": "TSG", "台鋼": "TSG",
    "味全龍": "WC", "龍": "WC", "味全": "WC",
    # English names (from international sports sites)
    "Chinatrust Brothers": "AEL", "Brothers": "AEL",
    "Uni-President Lions": "CT", "Uni Lions": "CT", "Uni-President 7-Eleven Lions": "CT",
    "Fubon Guardians": "FG", "Guardians": "FG",
    "Rakuten Monkeys": "WL", "Monkeys": "WL",
    "TSG Eagles": "TSG", "Taiwan Steel Eagles": "TSG", "TSG Hawks": "TSG",
    "Wei Chuan Dragons": "WC", "Dragons": "WC",
}

CITY_MAP = {
    "洲際棒球場": "台中",
    "台南棒球場": "台南",
    "新莊棒球場": "新北",
    "桃園棒球場": "桃園",
    "澄清湖棒球場": "高雄",
    "天母棒球場": "台北",
}


class CPBLScraper:
    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        try:
            r = self._session.get(BASE, timeout=8)
            if r.status_code == 200:
                time.sleep(0.3)
        except Exception:
            pass

    # ── 主要入口：一軍賽程 ────────────────────────
    def fetch_schedule(self, game_date: date) -> list[dict]:
        """
        回傳今日一軍賽程。
        先嘗試 requests，若 403/空 則改用 Playwright。
        全部失敗則拋出例外，由呼叫端決定是否用 mock。
        """
        # 1. 快速 requests 嘗試
        try:
            games = self._fetch_requests(game_date)
            if games:
                log.info("Scraper(requests): %d games", len(games))
                return games
            log.warning("requests returned 0 games, trying Playwright")
        except Exception as e:
            log.warning("requests failed (%s), trying Playwright", e)

        # 2. Playwright fallback
        games = self._fetch_playwright(game_date)
        log.info("Scraper(Playwright): %d games", len(games))
        return games

    # ── requests 方式 ─────────────────────────────
    def _fetch_requests(self, game_date: date) -> list[dict]:
        url = (
            f"{BASE}/schedule/lists"
            f"?year={game_date.year}"
            f"&month={game_date.month:02d}"
            f"&kind=A"
        )
        self._session.headers["Referer"] = f"{BASE}/schedule"
        resp = self._session.get(url, timeout=12)
        resp.raise_for_status()
        return self._parse_schedule(resp.text, game_date)

    # ── Playwright 方式 ───────────────────────────
    def _fetch_playwright(self, game_date: date) -> list[dict]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError("playwright not installed") from e

        # 嘗試兩種 URL 格式（/schedule/lists 和 /schedule）
        urls = [
            f"{BASE}/schedule/lists?year={game_date.year}&month={game_date.month:02d}&kind=A",
            f"{BASE}/schedule?year={game_date.year}&month={game_date.month:02d}&kind=A",
        ]

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=_HEADERS["User-Agent"],
                locale="zh-TW",
                extra_http_headers={"Accept-Language": "zh-TW,zh;q=0.9"},
            )
            page = ctx.new_page()

            html = ""
            for url in urls:
                try:
                    page.goto(url, wait_until="networkidle", timeout=30_000)
                    # 等待賽程 div 出現
                    try:
                        page.wait_for_selector("div.date, div.game, .ScheduleTableList", timeout=8_000)
                    except Exception:
                        log.warning("Playwright: selector timeout for %s", url)
                    html = page.content()

                    # debug：記錄找到的關鍵 element 數量
                    from bs4 import BeautifulSoup as _BS
                    _s = _BS(html, "html.parser")
                    n_date = len(_s.find_all("div", class_="date"))
                    n_game = len(_s.find_all("div", class_="game"))
                    n_tr   = len(_s.select("table tbody tr"))
                    log.info("Playwright(%s): div.date=%d div.game=%d tr=%d",
                             url.split("?")[0], n_date, n_game, n_tr)

                    if n_game > 0:
                        break   # 找到賽程就不再嘗試第二個 URL
                except Exception as e:
                    log.warning("Playwright URL %s failed: %s", url, e)

            browser.close()

        if not html:
            return []
        games = self._parse_schedule(html, game_date)

        # 若仍為 0，印出 div.date 的 data-date 值供 debug
        if not games:
            from bs4 import BeautifulSoup as _BS
            _s = _BS(html, "html.parser")
            dates_found = [
                d.get("data-date", "?")
                for d in _s.find_all("div", class_="date")
            ]
            log.warning("Playwright: 0 games parsed. div.date data-date values: %s (looking for %s)",
                        dates_found[:15], game_date.day)
            # 額外嘗試：找任何含有球隊名稱的 div
            team_hits = [
                d.get_text(strip=True)[:40]
                for d in _s.find_all("div")
                if any(t in (d.get_text() or "") for t in ("富邦", "樂天", "中信", "統一", "台鋼"))
            ]
            if team_hits:
                log.info("Playwright: found team-related divs: %s", team_hits[:6])

        return games

    # ── HTML 解析（支援 div 結構與 table 結構） ────
    def _parse_schedule(self, html: str, game_date: date) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        games = self._parse_div_structure(soup, game_date)
        if not games:
            games = self._parse_table_structure(soup, game_date)
        return games

    def _parse_div_structure(self, soup: BeautifulSoup, game_date: date) -> list[dict]:
        """
        CPBL 官網 JS 渲染後的結構：
          <div class="date" data-date="4">…</div>  ← 同一個 parent 裡
          <div class="game">
            <div class="team away">富邦悍將</div>
            <div class="team home">樂天桃猿</div>
            <div class="remark">18:35</div>
            <div class="place">桃園棒球場</div>
          </div>
        """
        games: list[dict] = []
        day = game_date.day
        ds  = str(game_date)

        # data-date 可能是 "4"、"04" 或 integer 4，都嘗試
        for fmt in (str(day), f"{day:02d}"):
            day_divs = soup.find_all("div", class_="date", attrs={"data-date": fmt})
            if day_divs:
                break
        if not day_divs:
            return games

        day_div = day_divs[-1] if day >= 25 else day_divs[0]
        container = day_div.parent
        if container is None:
            return games

        for game_div in container.find_all("div", class_="game"):
            away_el   = game_div.find("div", class_=lambda c: c and "team" in c and "away" in c)
            home_el   = game_div.find("div", class_=lambda c: c and "team" in c and "home" in c)
            remark_el = game_div.find("div", class_="remark")
            place_el  = game_div.find("div", class_="place")

            if not (away_el and home_el):
                continue

            away_name = re.sub(r"\s{2,}", " ", away_el.get_text(strip=True))
            home_name = re.sub(r"\s{2,}", " ", home_el.get_text(strip=True))
            if not away_name or not home_name:
                continue

            away_code = TEAM_CODE_MAP.get(away_name, away_name)
            home_code = TEAM_CODE_MAP.get(home_name, home_name)
            game_time = re.sub(r"\s{2,}", " ", remark_el.get_text(strip=True)) if remark_el else ""
            venue     = place_el.get_text(strip=True) if place_el else ""

            # 比賽結果（若已開打）
            score_m = re.search(r"(\d+)\s*[:\-]\s*(\d+)", game_time)
            status  = "結束" if score_m else "預定"

            games.append({
                "game_id":    f"{ds}-{away_code}-{home_code}",
                "date":       ds,
                "time":       game_time if not score_m else "",
                "away":       away_code,
                "away_name":  away_name,
                "home":       home_code,
                "home_name":  home_name,
                "venue":      venue,
                "league":     "A",
                "status":     status,
                "away_score": int(score_m.group(1)) if score_m else None,
                "home_score": int(score_m.group(2)) if score_m else None,
            })

        return games

    def _parse_table_structure(self, soup: BeautifulSoup, game_date: date) -> list[dict]:
        """靜態 HTML table 備用解析（非 JS 渲染時）"""
        games: list[dict] = []
        ds = str(game_date)
        rows = soup.select(
            ".ScheduleTableList tbody tr, "
            "table.schedule-table tbody tr, "
            "table tbody tr"
        )
        for row in rows:
            cols  = row.find_all("td")
            texts = [c.get_text(" ", strip=True) for c in cols]
            if len(texts) < 4:
                continue
            try:
                gtime     = texts[0].strip()
                away_raw  = texts[1].strip()
                score_raw = texts[2].strip()
                home_raw  = texts[3].strip()
                venue     = texts[4].strip() if len(texts) > 4 else ""

                if not away_raw or not home_raw:
                    continue
                if any(kw in away_raw for kw in ("客隊", "Away", "日期")):
                    continue

                away_code = TEAM_CODE_MAP.get(away_raw, away_raw)
                home_code = TEAM_CODE_MAP.get(home_raw, home_raw)
                m = re.search(r"(\d+)\s*[:\-]\s*(\d+)", score_raw)

                games.append({
                    "game_id":    f"{ds}-{away_code}-{home_code}",
                    "date":       ds,
                    "time":       gtime,
                    "away":       away_code,  "away_name": away_raw,
                    "home":       home_code,  "home_name": home_raw,
                    "venue":      venue,
                    "league":     "A",
                    "status":     "結束" if m else "預定",
                    "away_score": int(m.group(1)) if m else None,
                    "home_score": int(m.group(2)) if m else None,
                })
            except (IndexError, ValueError):
                continue

        return games

    # ── 天氣 ──────────────────────────────────────
    def fetch_weather(self, venue: str) -> Optional[dict]:
        city = CITY_MAP.get(venue)
        if not city:
            return None
        try:
            url  = f"{WEATHER_API}/{city}?format=j1&lang=zh-tw"
            resp = requests.get(url, timeout=6)
            data = resp.json()
            cur  = data["current_condition"][0]
            return {
                "temp_c":    int(cur["temp_C"]),
                "humidity":  int(cur["humidity"]),
                "wind_kph":  int(cur["windspeedKmph"]),
                "condition": cur["weatherDesc"][0]["value"],
                "city":      city,
            }
        except Exception:
            return None


def _f(texts: list, idx: int, default: float = 0.0) -> float:
    try:
        return float(texts[idx].replace("%", ""))
    except (IndexError, ValueError):
        return default


def _i(texts: list, idx: int, default: int = 0) -> int:
    try:
        return int(texts[idx])
    except (IndexError, ValueError):
        return default
