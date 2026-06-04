"""
CPBL 網頁爬蟲
抓取 cpbl.com.tw 的賽程、投手數據、球隊數據。
若抓取失敗會由 main.py 自動 fallback 到 mock_data。
"""
import re
import requests
from bs4 import BeautifulSoup
from datetime import date
from typing import Optional

BASE = "https://www.cpbl.com.tw"
WEATHER_API = "https://wttr.in"   # 無需 API Key

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": BASE + "/",
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
            self._session.get(BASE, timeout=8)   # 取得初始 cookie
        except Exception:
            pass

    # ── 賽程 ──────────────────────────────────
    def fetch_schedule(self, game_date: date) -> list[dict]:
        url = (
            f"{BASE}/schedule/lists"
            f"?year={game_date.year}"
            f"&month={game_date.month:02d}"
            f"&day={game_date.day:02d}"
            f"&kind=A"
        )
        resp = self._session.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse_schedule(soup, game_date)

    def _parse_schedule(self, soup: BeautifulSoup, game_date: date) -> list[dict]:
        games: list[dict] = []
        # 找主要賽程 table
        rows = soup.select("table tbody tr, .game-list tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 4:
                continue
            texts = [c.get_text(" ", strip=True) for c in cols]
            try:
                gtime = texts[0]
                away_raw = texts[1]
                score_raw = texts[2]
                home_raw = texts[3]
                venue = texts[4] if len(texts) > 4 else ""

                m = re.search(r"(\d+)\s*[:\-]\s*(\d+)", score_raw)
                g: dict = {
                    "date": str(game_date),
                    "time": gtime,
                    "away": away_raw,
                    "home": home_raw,
                    "venue": venue,
                    "status": "結束" if m else "預定",
                    "away_score": int(m.group(1)) if m else None,
                    "home_score": int(m.group(2)) if m else None,
                }
                if away_raw or home_raw:
                    games.append(g)
            except (IndexError, ValueError):
                continue
        return games

    # ── 投手數據 ──────────────────────────────
    def fetch_pitcher_stats(self, year: int = 2026) -> list[dict]:
        url = f"{BASE}/stats/pitcher?year={year}&kind=A&cate=all"
        resp = self._session.get(url, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse_pitcher_table(soup)

    def _parse_pitcher_table(self, soup: BeautifulSoup) -> list[dict]:
        pitchers: list[dict] = []
        rows = soup.select("table tbody tr")
        for row in rows:
            cols = row.find_all("td")
            texts = [c.get_text(strip=True) for c in cols]
            if len(texts) < 10:
                continue
            try:
                p = {
                    "name":  texts[1] if len(texts) > 1 else "",
                    "team":  texts[2] if len(texts) > 2 else "",
                    "era":   _f(texts, 5),
                    "whip":  _f(texts, 9),
                    "k9":    _f(texts, 12),
                    "bb9":   _f(texts, 11),
                    "fip":   _f(texts, 14),
                    "gs":    _i(texts, 3),
                }
                if p["name"]:
                    pitchers.append(p)
            except (IndexError, ValueError):
                continue
        return pitchers

    # ── 球隊數據 ──────────────────────────────
    def fetch_team_batting(self, year: int = 2026) -> list[dict]:
        url = f"{BASE}/stats/team?year={year}&kind=A&cate=bat"
        resp = self._session.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse_team_table(soup)

    def _parse_team_table(self, soup: BeautifulSoup) -> list[dict]:
        rows = soup.select("table tbody tr")
        teams = []
        for row in rows:
            cols = row.find_all("td")
            texts = [c.get_text(strip=True) for c in cols]
            if len(texts) < 4:
                continue
            teams.append({
                "team": texts[0],
                "avg":  _f(texts, 3),
                "ops":  _f(texts, 8),
            })
        return teams

    # ── 天氣 ──────────────────────────────────
    def fetch_weather(self, venue: str) -> Optional[dict]:
        city = CITY_MAP.get(venue)
        if not city:
            return None
        try:
            url = f"{WEATHER_API}/{city}?format=j1&lang=zh-tw"
            resp = requests.get(url, timeout=6)
            data = resp.json()
            cur = data["current_condition"][0]
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
