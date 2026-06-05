#!/usr/bin/env python3
"""
NPB / KBO 數據本地更新腳本 — 在你的電腦執行，把數據推上 GitHub

使用方式：
  python scripts/update_stats.py          # 更新投手+賽程
  python scripts/update_stats.py --dry    # 只爬不寫入
  python scripts/update_stats.py --push   # 爬完自動 git commit + push
  python scripts/update_stats.py --odds-only --push  # 只更新賠率

資料來源：
  - 投手統計：ESPN API (jlb/kor)，不受 WAF 封鎖
  - 賽程：ESPN API
  - 賠率：The Odds API (baseball_kbo) / oddsportal
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
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "ja,ko,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

BASE_ESPN_NPB = "https://site.api.espn.com/apis/site/v2/sports/baseball/jlb"
BASE_ESPN_KBO = "https://site.api.espn.com/apis/site/v2/sports/baseball/kor"

# ─────────────────────────────────────────────────────────────
# 1. ESPN 投手成績 (NPB + KBO)
# ─────────────────────────────────────────────────────────────

def scrape_espn_pitchers(year: int, session: requests.Session) -> dict:
    """
    從 ESPN API 抓 NPB + KBO 先發投手成績。
    不受 WAF 封鎖，可在任何環境執行。
    """
    from cpbl.stats_scraper import fetch_all_pitcher_stats
    try:
        stats = fetch_all_pitcher_stats(year)
        log.info("ESPN: 抓到 %d 名投手", len(stats))
        return stats
    except Exception as e:
        log.warning("ESPN 投手統計失敗: %s", e)
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
# 2. NPB 官方網站  npb.jp
# ─────────────────────────────────────────────────────────────

# npb.jp 球隊英文縮寫 → 我們的代碼
_NPB_ABBR_MAP = {
    "G": "GNT", "T": "HNS", "C": "HRC", "DB": "YDB",
    "S": "YKL", "D": "CND",                               # CL
    "H": "SBH", "B": "ORX", "E": "RKT",
    "M": "LTT", "L": "SEI", "F": "HAM",                   # PL
    # 英文全名備用
    "Giants": "GNT", "Tigers": "HNS", "Carp": "HRC",
    "BayStars": "YDB", "Swallows": "YKL", "Dragons": "CND",
    "Hawks": "SBH", "Buffaloes": "ORX", "Eagles": "RKT",
    "Marines": "LTT", "Lions": "SEI", "Fighters": "HAM",
}


def scrape_npb_pitchers(year: int, session: requests.Session) -> dict:
    """
    從 npb.jp 官方網站抓 NPB 投手成績。
    必須在個人電腦（非雲端）執行。

    資料包含：ERA, W, L, G, GS, IP, H, R, ER, BB, HBP, SO, HR, WHIP
    衍生：K/9, BB/9, K%, BB%, FIP
    """
    # npb.jp 提供英文版和日文版統計頁
    urls_to_try = [
        f"https://npb.jp/bis/eng/{year}/stats/idb1_b.html",   # 英文 投手成績
        f"https://npb.jp/bis/eng/{year}/stats/idb1_p.html",   # 英文 先發
        f"https://npb.jp/bis/{year}/stats/idb1_b.html",       # 日文版
        f"https://npb.jp/statistics/{year}/",                  # 新版統計頁
    ]

    for url in urls_to_try:
        try:
            log.info("NPB: 嘗試 %s", url)
            r = session.get(url, timeout=15)
            if r.status_code == 403:
                log.warning("npb.jp 403 — 若在個人電腦仍被擋，請稍後再試")
                continue
            if r.status_code != 200:
                continue
            r.encoding = r.apparent_encoding or "utf-8"
            stats = _parse_npb_html(r.text)
            if stats:
                log.info("npb.jp: 抓到 %d 名投手 from %s", len(stats), url)
                return stats
        except Exception as e:
            log.debug("npb.jp %s: %s", url, e)

    return {}


def _parse_npb_html(html: str) -> dict:
    """解析 npb.jp 投手成績 HTML 表格。"""
    from cpbl.stats_scraper import enrich_pitcher, calc_fip as _calc_fip
    soup  = BeautifulSoup(html, "html.parser")
    stats = {}

    # npb.jp 欄位對照（英文版）
    col_map = {
        # 英文版欄位名
        "Name":   "name",  "Player": "name",
        "Team":   "team",  "Club":   "team",
        "ERA":    "era",
        "W":      "wins",  "L": "losses",
        "G":      "g",     "GS": "gs",     "CG": "cg",  "SHO": "sho",
        "SV":     "sv",    "HLD": "hld",
        "IP":     "innings",
        "H":      "_h",    "R": "_r",      "ER": "_er",
        "BB":     "_bb",   "IBB": "_ibb",  "HBP": "_hbp",
        "SO":     "_k",    "K":  "_k",
        "HR":     "_hr",   "HR9": "hr9",
        "WHIP":   "whip",
        "K/9":    "k9",    "BB/9": "bb9",
        "K%":     "k_pct", "BB%": "bb_pct",
        "FIP":    "fip",   "xFIP": "xfip",
        "BABIP":  "babip", "LOB%": "lob_pct",
        # 日文版欄位名
        "選手名": "name",  "氏名": "name",
        "チーム": "team",  "球団": "team",
        "防御率": "era",   "ERA": "era",
        "勝":     "wins",  "敗": "losses",
        "試合":   "g",     "先発": "gs",
        "完投":   "cg",    "完封": "sho",
        "セーブ": "sv",    "HP":  "hld",
        "投球回": "innings",
        "被安打": "_h",    "失点": "_r",   "自責点": "_er",
        "四球":   "_bb",   "死球": "_hbp",
        "三振":   "_k",    "被本塁打": "_hr",
        "WHIP":   "whip",
    }

    for table in soup.find_all("table"):
        # 找 header 行
        header_row = None
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
        if not header_row:
            rows = table.find_all("tr")
            header_row = rows[0] if rows else None
        if not header_row:
            continue

        raw_hdrs = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
        hdrs = [col_map.get(h, h.lower()) for h in raw_hdrs]

        if "name" not in hdrs or "era" not in hdrs:
            continue

        data_rows = table.select("tbody tr") or table.find_all("tr")[1:]
        for row in data_rows:
            tds = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if not tds or len(tds) < 3:
                continue
            try:
                name = tds[hdrs.index("name")].strip()
            except (ValueError, IndexError):
                continue
            if not name or name in ("合計", "Total", "平均", "計", ""):
                continue

            p: dict = {}
            # 取球隊
            if "team" in hdrs:
                try:
                    raw_team = tds[hdrs.index("team")].strip()
                    p["team_abbr"] = _NPB_ABBR_MAP.get(raw_team, raw_team)
                except Exception:
                    pass

            for field in ("era", "whip", "k9", "bb9", "hr9", "k_pct", "bb_pct",
                          "fip", "xfip", "babip", "lob_pct",
                          "wins", "losses", "g", "gs", "sv",
                          "_k", "_bb", "_hr", "_hbp", "_h", "_er"):
                if field not in hdrs:
                    continue
                raw_val = tds[hdrs.index(field)]
                raw_val = (raw_val.replace("⅓", ".33").replace("⅔", ".67")
                           .replace("%", "").replace(",", "").strip())
                try:
                    p[field] = float(raw_val)
                except (ValueError, TypeError):
                    pass

            if "era" not in p:
                continue

            # 處理 innings (IP 格式: "120.1" 或 "120⅓")
            if "innings" in hdrs:
                raw_ip = tds[hdrs.index("innings")]
                raw_ip = raw_ip.replace("⅓", ".33").replace("⅔", ".67").strip()
                try:
                    p["innings"] = float(raw_ip)
                except (ValueError, TypeError):
                    pass

            ip = p.get("innings", 0)
            if ip > 0:
                k   = p.pop("_k",   0)
                bb  = p.pop("_bb",  0)
                hr  = p.pop("_hr",  0)
                hbp = p.pop("_hbp", 0)
                if k  > 0 and "k9"    not in p: p["k9"]    = round(k  / ip * 9, 2)
                if bb > 0 and "bb9"   not in p: p["bb9"]   = round(bb / ip * 9, 2)
                if k  > 0 and "k_pct" not in p: p["k_pct"] = round(k  / (ip * 4.3) * 100, 1)
                if bb > 0 and "bb_pct"not in p: p["bb_pct"]= round(bb / (ip * 4.3) * 100, 1)
                if hr > 0 and "fip"   not in p:
                    fip_val = _calc_fip(hr, bb + hbp, k, ip, constant=3.20)
                    if fip_val: p["fip"] = fip_val
                # 保留原始數據
                p["_raw"] = {"k": k, "bb": bb, "hr": hr, "hbp": hbp}

            enrich_pitcher(p)
            stats[name] = p

    return stats


# ─────────────────────────────────────────────────────────────
# 3. KBO 官方網站  koreabaseball.com
# ─────────────────────────────────────────────────────────────

# KBO 球隊名稱 → 代碼
_KBO_NAME_TO_CODE = {
    "삼성": "SSL", "Samsung": "SSL",
    "LG":   "LGT",
    "두산": "DSB", "Doosan": "DSB",
    "KT":   "KTW",
    "SSG":  "SSG",
    "NC":   "NCD",
    "KIA":  "KIA",
    "롯데": "LTG", "Lotte": "LTG",
    "한화": "HWE", "Hanwha": "HWE",
    "키움": "KWH", "Kiwoom": "KWH",
}


def scrape_kbo_pitchers(year: int, session: requests.Session) -> dict:
    """
    從 koreabaseball.com 抓 KBO 投手成績。
    必須在個人電腦（非雲端）執行。

    同時嘗試 statiz.co.kr 取得進階數據 (FIP/K%/BB%)。
    """
    stats = {}

    # ── 3a. koreabaseball.com 基本成績 ──────────
    kbo_urls = [
        f"https://www.koreabaseball.com/Record/Player/PitcherBasic/Basic1.aspx?gyear={year}",
        f"https://www.koreabaseball.com/Record/Player/PitcherBasic/Basic2.aspx?gyear={year}",
        "https://www.koreabaseball.com/Record/Player/PitcherBasic/Basic1.aspx",
    ]
    for url in kbo_urls:
        try:
            log.info("KBO: 嘗試 %s", url)
            r = session.get(url, timeout=15)
            if r.status_code == 403:
                log.warning("koreabaseball.com 403 — 若在個人電腦仍被擋，請確認沒用 VPN")
                break
            if r.status_code != 200:
                continue
            r.encoding = r.apparent_encoding or "utf-8"
            parsed = _parse_kbo_html(r.text)
            if parsed:
                stats.update(parsed)
                log.info("koreabaseball.com: 抓到 %d 名投手", len(parsed))
                break
        except Exception as e:
            log.debug("koreabaseball.com %s: %s", url, e)

    # ── 3b. statiz.co.kr 進階成績 (FIP/K%/BB%) ──
    statiz_urls = [
        f"https://statiz.co.kr/stat.php?opt=0&sopt=0&year={year}&sy={year}&ey={year}&pos=1&eas=&pa=0",
        f"https://statiz.co.kr/stat.php?opt=0&sopt=0&year={year}&pos=1&pa=0",
    ]
    for url in statiz_urls:
        try:
            r = session.get(url, timeout=15, headers={**_HEADERS, "Referer": "https://statiz.co.kr/"})
            if r.status_code != 200:
                continue
            r.encoding = r.apparent_encoding or "utf-8"
            adv = _parse_statiz_html(r.text)
            if adv:
                # 把進階數據 merge 進基本成績
                for name, p in adv.items():
                    if name in stats:
                        stats[name].update({k: v for k, v in p.items() if k not in stats[name]})
                    else:
                        stats[name] = p
                log.info("statiz.co.kr: 補充 %d 名投手進階數據", len(adv))
            break
        except Exception as e:
            log.debug("statiz.co.kr %s: %s", url, e)

    return stats


def _parse_kbo_html(html: str) -> dict:
    """解析 koreabaseball.com 投手成績頁面。"""
    from cpbl.stats_scraper import enrich_pitcher, calc_fip as _calc_fip
    soup  = BeautifulSoup(html, "html.parser")
    stats = {}

    # 欄位對照（韓文 + 英文）
    col_map = {
        "선수명": "name",  "이름": "name",   "Name": "name",
        "팀명":   "team",  "팀":   "team",   "Team": "team",
        "ERA":    "era",   "평균자책점": "era",
        "승":     "wins",  "W": "wins",
        "패":     "losses","L": "losses",
        "경기":   "g",     "G": "g",
        "선발":   "gs",    "GS": "gs",
        "이닝":   "innings","IP": "innings",
        "삼진":   "_k",    "SO": "_k",   "K": "_k",
        "사사구": "_bb",   "BB": "_bb",
        "피홈런": "_hr",   "HR": "_hr",
        "사구":   "_hbp",  "HBP": "_hbp",
        "WHIP":   "whip",
        "K/9":    "k9",    "9이닝삼진": "k9",
        "BB/9":   "bb9",
        "FIP":    "fip",
        "K%":     "k_pct", "BB%": "bb_pct",
    }

    for table in soup.find_all("table"):
        header_row = None
        thead = table.find("thead")
        if thead:
            header_row = thead.find("tr")
        if not header_row:
            rows = table.find_all("tr")
            header_row = rows[0] if rows else None
        if not header_row:
            continue

        raw_hdrs = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
        hdrs = [col_map.get(h, h.lower()) for h in raw_hdrs]

        if "name" not in hdrs or "era" not in hdrs:
            continue

        data_rows = table.select("tbody tr") or table.find_all("tr")[1:]
        for row in data_rows:
            tds = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if not tds or len(tds) < 3:
                continue
            try:
                name = tds[hdrs.index("name")].strip()
            except (ValueError, IndexError):
                continue
            if not name or name in ("합계", "평균", "Total", ""):
                continue

            p: dict = {}
            if "team" in hdrs:
                try:
                    raw_team = tds[hdrs.index("team")].strip()
                    p["team_abbr"] = _KBO_NAME_TO_CODE.get(raw_team, raw_team)
                except Exception:
                    pass

            for field in ("era", "whip", "k9", "bb9", "k_pct", "bb_pct",
                          "fip", "wins", "losses", "g", "gs",
                          "_k", "_bb", "_hr", "_hbp"):
                if field not in hdrs:
                    continue
                raw_val = tds[hdrs.index(field)]
                raw_val = raw_val.replace("%", "").replace(",", "").strip()
                try:
                    p[field] = float(raw_val)
                except (ValueError, TypeError):
                    pass

            if "era" not in p:
                continue

            if "innings" in hdrs:
                raw_ip = tds[hdrs.index("innings")]
                raw_ip = raw_ip.replace("⅓", ".33").replace("⅔", ".67").replace("2/3", ".67").replace("1/3", ".33").strip()
                try:
                    p["innings"] = float(raw_ip)
                except (ValueError, TypeError):
                    pass

            ip = p.get("innings", 0)
            if ip > 0:
                k   = p.pop("_k",   0)
                bb  = p.pop("_bb",  0)
                hr  = p.pop("_hr",  0)
                hbp = p.pop("_hbp", 0)
                if k  > 0 and "k9"    not in p: p["k9"]    = round(k  / ip * 9, 2)
                if bb > 0 and "bb9"   not in p: p["bb9"]   = round(bb / ip * 9, 2)
                if k  > 0 and "k_pct" not in p: p["k_pct"] = round(k  / (ip * 4.3) * 100, 1)
                if bb > 0 and "bb_pct"not in p: p["bb_pct"]= round(bb / (ip * 4.3) * 100, 1)
                if hr > 0 and "fip"   not in p:
                    fip_val = _calc_fip(hr, bb + hbp, k, ip, constant=3.60)
                    if fip_val: p["fip"] = fip_val
                p["_raw"] = {"k": k, "bb": bb, "hr": hr, "hbp": hbp}

            enrich_pitcher(p)
            stats[name] = p

    return stats


def _parse_statiz_html(html: str) -> dict:
    """解析 statiz.co.kr 進階投手數據（FIP/xFIP/K%/BB%/BABIP 等）。"""
    from cpbl.stats_scraper import enrich_pitcher
    soup  = BeautifulSoup(html, "html.parser")
    stats = {}

    col_map = {
        "이름": "name", "선수": "name",
        "팀":  "team",
        "ERA": "era",   "FIP": "fip",   "xFIP": "xfip",
        "K%":  "k_pct", "BB%": "bb_pct","K-BB%": "k_bb_pct",
        "BABIP": "babip","LOB%": "lob_pct",
        "K/9": "k9",    "BB/9": "bb9",  "HR/9": "hr9",
        "WHIP": "whip", "IP": "innings",
        "W": "wins",    "L": "losses",
    }

    for table in soup.find_all("table"):
        thead = table.find("thead")
        header_row = thead.find("tr") if thead else (table.find_all("tr") or [None])[0]
        if not header_row:
            continue
        raw_hdrs = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
        hdrs = [col_map.get(h, h.lower()) for h in raw_hdrs]
        if "name" not in hdrs:
            continue

        for row in table.select("tbody tr") or table.find_all("tr")[1:]:
            tds = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if not tds:
                continue
            try:
                name = tds[hdrs.index("name")].strip()
            except (ValueError, IndexError):
                continue
            if not name or name in ("합계", "평균", ""):
                continue

            p: dict = {}
            for field in ("era", "fip", "xfip", "k_pct", "bb_pct", "k_bb_pct",
                          "babip", "lob_pct", "k9", "bb9", "hr9", "whip",
                          "innings", "wins", "losses"):
                if field not in hdrs:
                    continue
                raw_val = tds[hdrs.index(field)].replace("%", "").replace(",", "").strip()
                try:
                    p[field] = float(raw_val)
                except (ValueError, TypeError):
                    pass

            if p:
                enrich_pitcher(p)
                stats[name] = p

    return stats


# ─────────────────────────────────────────────────────────────
# 4. Baseball Reference（備援，兩聯盟都有）
# ─────────────────────────────────────────────────────────────

def scrape_bbref(year: int, session: requests.Session) -> dict:
    """
    從 baseball-reference.com 抓 NPB + KBO 投手成績。
    資料最完整（ERA/FIP/WHIP/K9/BB9/K%/BB% 全部有）。
    若 npb.jp 和 koreabaseball.com 都失敗，用這個當備援。
    """
    stats = {}

    for league_code, league_name in [("NPB", "NPB"), ("KBO", "KBO")]:
        urls = [
            f"https://www.baseball-reference.com/register/league.cgi?code={league_code}&class=Fgn&year={year}&stat=pitch&CSV=Y",
            f"https://www.baseball-reference.com/register/league.cgi?code={league_code}&class=Fgn&year={year}&stat=pitch",
        ]
        for url in urls:
            try:
                log.info("BB-Ref [%s]: 嘗試 %s", league_name, url)
                r = session.get(url, timeout=15)
                if r.status_code == 403:
                    log.warning("baseball-reference.com 403 — IP 被封鎖")
                    break
                if r.status_code != 200:
                    continue

                # CSV 直接下載
                if "CSV=Y" in url and r.text.startswith("Rk,"):
                    parsed = _parse_bbref_csv(r.text, league_code)
                else:
                    parsed = _parse_bbref_html(r.text, league_code)

                if parsed:
                    stats.update(parsed)
                    log.info("BB-Ref [%s]: 抓到 %d 名投手", league_name, len(parsed))
                    break
            except Exception as e:
                log.debug("BB-Ref %s: %s", url, e)

    return stats


def _parse_bbref_csv(csv_text: str, league: str = "") -> dict:
    """解析 baseball-reference CSV 格式。"""
    from cpbl.stats_scraper import enrich_pitcher, calc_fip as _calc_fip
    import csv, io
    stats = {}
    reader = csv.DictReader(io.StringIO(csv_text))

    for row in reader:
        name = row.get("Name", "").strip()
        if not name or name in ("", "Name", "Rk"):
            continue
        try:
            era = float(row.get("ERA", "") or 0)
        except ValueError:
            continue
        if era <= 0:
            continue

        try:
            ip  = float(str(row.get("IP", "0")).replace("⅓", ".33").replace("⅔", ".67") or 0)
            k   = float(row.get("SO", 0) or 0)
            bb  = float(row.get("BB", 0) or 0)
            hr  = float(row.get("HR", 0) or 0)
            hbp = float(row.get("HBP", 0) or 0)
        except (ValueError, TypeError):
            ip = k = bb = hr = hbp = 0

        p: dict = {"era": era}
        for field, key in [("W", "wins"), ("L", "losses"), ("G", "g"), ("GS", "gs"),
                           ("WHIP", "whip"), ("FIP", "fip"), ("K/9", "k9"), ("BB/9", "bb9"),
                           ("K%", "k_pct"), ("BB%", "bb_pct"), ("BABIP", "babip")]:
            raw = str(row.get(field, "") or "").replace("%", "").strip()
            try:
                p[key] = float(raw)
            except (ValueError, TypeError):
                pass

        if ip > 0:
            p["innings"] = ip
            if k  > 0 and "k9"    not in p: p["k9"]    = round(k  / ip * 9, 2)
            if bb > 0 and "bb9"   not in p: p["bb9"]   = round(bb / ip * 9, 2)
            if k  > 0 and "k_pct" not in p: p["k_pct"] = round(k  / (ip * 4.3) * 100, 1)
            if bb > 0 and "bb_pct"not in p: p["bb_pct"]= round(bb / (ip * 4.3) * 100, 1)
            fip_c = 3.20 if league == "NPB" else 3.60
            if hr > 0 and "fip" not in p:
                fip_val = _calc_fip(hr, bb + hbp, k, ip, constant=fip_c)
                if fip_val: p["fip"] = fip_val

        p["league"] = league
        enrich_pitcher(p)
        stats[name] = p

    return stats


def _parse_bbref_html(html: str, league: str = "") -> dict:
    """解析 baseball-reference HTML 統計表格。"""
    from cpbl.stats_scraper import enrich_pitcher
    soup  = BeautifulSoup(html, "html.parser")
    stats = {}

    for table in soup.find_all("table", id=lambda x: x and "pitching" in x.lower()):
        thead = table.find("thead")
        if not thead:
            continue
        header_row = thead.find("tr")
        if not header_row:
            continue
        raw_hdrs = [th.get("data-stat", th.get_text(strip=True))
                    for th in header_row.find_all(["th", "td"])]
        for row in table.select("tbody tr:not(.thead)"):
            name_el = row.find(["td", "th"], {"data-stat": "player"})
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name:
                continue

            p = {}
            stat_map = {
                "earned_run_avg": "era", "whip": "whip", "fip": "fip",
                "strikeouts_per_nine": "k9", "bases_on_balls_per_nine": "bb9",
                "strikeout_perc": "k_pct", "bases_on_balls_perc": "bb_pct",
                "IP": "innings", "win": "wins", "loss": "losses",
                "games": "g", "games_started": "gs",
            }
            for td in row.find_all(["td"]):
                ds = td.get("data-stat", "")
                key = stat_map.get(ds)
                if key:
                    raw = td.get_text(strip=True).replace("%", "")
                    try:
                        p[key] = float(raw)
                    except (ValueError, TypeError):
                        pass

            if "era" in p:
                p["league"] = league
                enrich_pitcher(p)
                stats[name] = p

    return stats


def _parse_json_pitchers(data) -> dict:
    """解析 JSON 格式的投手數據（通用格式）。"""
    from cpbl.stats_scraper import enrich_pitcher
    stats = {}
    items = data if isinstance(data, list) else data.get("data", data.get("pitchers", []))
    for item in items:
        name = item.get("name") or item.get("playerName") or item.get("displayName", "")
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


# ─────────────────────────────────────────────────────────────
# 4. CPBL 賽程
# ─────────────────────────────────────────────────────────────

def scrape_schedule(year: int, months: list[int], session: requests.Session) -> list:
    """從 ESPN API 抓 NPB + KBO 滾動日期窗口的賽程（昨天 ~ 14 天後）。"""
    from cpbl.stats_scraper import fetch_schedule_multi
    import datetime

    all_games = []
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date()
    start = today - datetime.timedelta(days=1)
    end   = today + datetime.timedelta(days=14)

    odds_key = os.environ.get("ODDS_API_KEY", "")
    current = start
    while current <= end:
        games = fetch_schedule_multi(current, odds_api_key=odds_key)
        all_games.extend(games)
        time.sleep(0.3)
        current += datetime.timedelta(days=1)

    log.info("賽程: 共 %d 場（%s ~ %s）", len(all_games), start, end)
    return all_games


# ─────────────────────────────────────────────────────────────
# 5. 賠率爬取（台灣運彩 / oddsportal）
# ─────────────────────────────────────────────────────────────

# KBO 隊名對照（The Odds API / oddsportal 使用）
_KBO_TEAM_MAP = {
    "samsung lions":  "SSL", "samsung":  "SSL",
    "lg twins":       "LGT", "lg":       "LGT",
    "doosan bears":   "DSB", "doosan":   "DSB",
    "kt wiz":         "KTW", "kt":       "KTW",
    "ssg landers":    "SSG", "ssg":      "SSG",
    "nc dinos":       "NCD", "nc":       "NCD",
    "kia tigers":     "KIA", "kia":      "KIA",
    "lotte giants":   "LTG", "lotte":    "LTG",
    "hanwha eagles":  "HWE", "hanwha":   "HWE",
    "kiwoom heroes":  "KWH", "kiwoom":   "KWH",
}

# NPB 隊名對照（oddsportal / The Odds API）
_NPB_TEAM_MAP = {
    "yomiuri giants":       "GNT", "giants":      "GNT",
    "hanshin tigers":       "HNS", "hanshin":     "HNS",
    "hiroshima carp":       "HRC", "hiroshima":   "HRC",
    "yokohama dena baystars":"YDB", "baystars":    "YDB",
    "yakult swallows":      "YKL", "yakult":      "YKL",
    "chunichi dragons":     "CND", "chunichi":    "CND",
    "softbank hawks":       "SBH", "softbank":    "SBH",
    "orix buffaloes":       "ORX", "orix":        "ORX",
    "rakuten eagles":       "RKT", "rakuten":     "RKT",
    "lotte marines":        "LTT", "marines":     "LTT",
    "seibu lions":          "SEI", "seibu":       "SEI",
    "nippon-ham fighters":  "HAM", "fighters":    "HAM",
}

_OP_URL_KBO = "https://www.oddsportal.com/baseball/south-korea/kbo-league/"
_OP_URL_NPB = "https://www.oddsportal.com/baseball/japan/npb/"
_THE_ODDS_KBO_KEY = "baseball_kbo"

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


def _any_code(name: str) -> str:
    """模糊比對隊名 → 代碼（合併 NPB + KBO 查詢表）"""
    n = name.lower().strip()
    for mapping in (_KBO_TEAM_MAP, _NPB_TEAM_MAP):
        for k, v in mapping.items():
            if k in n or n in k:
                return v
    return ""

# Keep old aliases for compatibility
_sl_code = _any_code
_op_code = _any_code


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
    """The Odds API — KBO"""
    import os
    api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        log.warning("ODDS_API_KEY 未設定，跳過 The Odds API")
        return {}
    url = f"https://api.the-odds-api.com/v4/sports/{_THE_ODDS_KBO_KEY}/odds/?apiKey={api_key}&regions=eu,us&markets=h2h&oddsFormat=decimal"
    try:
        r = session.get(url, timeout=12, headers=_ODDS_HEADERS)
        if r.status_code == 403:
            log.warning("台灣運彩 API 403 — 嘗試 HTML")
            return {}
        r.raise_for_status()
        data = r.json()
        result = {}
        data = r.json()
        result = {}
        for event in data if isinstance(data, list) else []:
            home_en = event.get("home_team", "").lower()
            away_en = event.get("away_team", "").lower()
            home_code = _any_code(home_en)
            away_code = _any_code(away_en)
            if not home_code or not away_code:
                continue
            game_key = f"{away_code}-{home_code}"
            # Parse h2h odds from bookmakers
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
                result[game_key] = _make_odds_entry(
                    ah, hh, source="The Odds API (KBO)",
                    note="The Odds API baseball_kbo",
                )
        if result:
            log.info("The Odds API KBO: %d 場賠率", len(result))
        return result
    except Exception as e:
        log.debug("The Odds API 失敗: %s", e)
        return {}


def _scrape_sl_html(session: requests.Session) -> dict:
    """oddsportal KBO / NPB HTML 解析 (備援)"""
    result = {}
    for league_url in [_OP_URL_KBO, _OP_URL_NPB]:
        try:
            r = session.get(league_url, timeout=15, headers=_ODDS_HEADERS)
            if r.status_code == 403:
                log.warning("oddsportal 403 — 跳過")
                continue
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for row in soup.select(".eventRow, [class*='eventRow']"):
                teams = row.select(".participant-name, .team-name")
                if len(teams) < 2:
                    continue
                ac = _any_code(teams[0].get_text(strip=True))
                hc = _any_code(teams[1].get_text(strip=True))
                if not ac or not hc:
                    continue
                nums = []
                for el in row.select(".odds-nowrp, .oddsValueInner, [class*='odds']"):
                    try:
                        nums.append(float(el.get_text(strip=True)))
                    except ValueError:
                        pass
                if len(nums) >= 2:
                    result[f"{ac}-{hc}"] = _make_odds_entry(
                        nums[0], nums[1], source="oddsportal", note="oddsportal HTML",
                    )
        except Exception as e:
            log.debug("oddsportal %s 失敗: %s", league_url, e)
    if result:
        log.info("oddsportal: %d 場賠率", len(result))
    return result


def _scrape_sl_playwright(game_date_str: str) -> dict:
    """Playwright 動態渲染 oddsportal（JS 重度渲染時用）"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {}
    result = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for league_url in [_OP_URL_KBO, _OP_URL_NPB]:
                page = browser.new_page()
                page.goto(league_url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
                html = page.content()
                page.close()
                soup = BeautifulSoup(html, "html.parser")
                partial = _scrape_sl_html_from_rendered(soup)
                result.update(partial)
            browser.close()
        if result:
            log.info("oddsportal Playwright: %d 場賠率", len(result))
    except Exception as e:
        log.debug("oddsportal Playwright 失敗: %s", e)
    return result


def _scrape_sl_html_from_rendered(soup: BeautifulSoup) -> dict:
    result = {}
    for row in soup.find_all(["tr", "div"], class_=lambda c: c and any(
            x in c for x in ("game", "match", "event", "odd", "eventRow"))):
        text = row.get_text(" ", strip=True)
        found = []
        for k in {**_KBO_TEAM_MAP, **_NPB_TEAM_MAP}:
            if k in text.lower():
                found.append({**_KBO_TEAM_MAP, **_NPB_TEAM_MAP}[k])
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
                nums[0], nums[1], source="oddsportal", note="HTML 解析",
            )
    return result


def _scrape_oddsportal(session: requests.Session) -> dict:
    """oddsportal NPB/KBO 賠率（備援，已在 _scrape_sl_html 處理）"""
    return _scrape_sl_html(session)


def scrape_odds(game_date_str: str, session: requests.Session,
                use_playwright: bool = True) -> dict:
    """
    抓今日 NPB/KBO 賠率，嘗試順序：
      1. The Odds API (baseball_kbo)
      2. oddsportal (KBO/NPB) HTML
      3. oddsportal Playwright（JS 渲染）

    回傳 {game_key: odds_dict}
    """
    print("  嘗試 The Odds API (KBO)...")
    result = _scrape_sl_api(session)
    if result:
        return result

    print("  嘗試 oddsportal HTML...")
    result = _scrape_sl_html(session)
    if result:
        return result

    if use_playwright:
        print("  嘗試 oddsportal Playwright（JS 渲染）...")
        result = _scrape_sl_playwright(game_date_str)
        if result:
            return result

    return {}


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
    """將爬到的賽程寫入 schedule.json（只保留有 league 欄位的 NPB/KBO 資料）。"""
    if not games:
        log.info("update_schedule: 無新賽程，schedule.json 不變")
        return
    import datetime
    cutoff = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()

    try:
        with open(SCHED_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {"games": []}

    # 保留：有 league 欄位（NPB/KBO）且日期 >= cutoff 的舊資料
    kept = [
        g for g in existing.get("games", [])
        if g.get("league") and g.get("date", "") >= cutoff
    ]

    # Index by game_id for O(1) lookup and in-place updates
    kept_by_id: dict[str, dict] = {
        g.get("game_id") or f"{g['date']}-{g['away']}-{g['home']}": g
        for g in kept
    }

    added = 0
    updated = 0
    for g in games:
        gid = g.get("game_id") or f"{g['date']}-{g['away']}-{g['home']}"
        if gid not in kept_by_id:
            kept.append(g)
            kept_by_id[gid] = g
            added += 1
        else:
            # Update existing entry when new data fills in missing fields
            existing_g = kept_by_id[gid]
            changed = False
            # Fill in pitcher names if previously empty
            if g.get("away_pitcher") and not existing_g.get("away_pitcher"):
                existing_g["away_pitcher"] = g["away_pitcher"]
                changed = True
            if g.get("home_pitcher") and not existing_g.get("home_pitcher"):
                existing_g["home_pitcher"] = g["home_pitcher"]
                changed = True
            # Fill in game time if previously empty
            if g.get("time") and not existing_g.get("time"):
                existing_g["time"] = g["time"]
                changed = True
            # Update score/status if game has been played
            if g.get("away_score") is not None and existing_g.get("away_score") is None:
                existing_g["away_score"] = g["away_score"]
                existing_g["home_score"] = g["home_score"]
                existing_g["status"] = g.get("status", existing_g.get("status", "終了"))
                changed = True
            if changed:
                updated += 1

    kept.sort(key=lambda x: (x.get("date", ""), x.get("time", "")))
    payload = {"games": kept, "updated_at": datetime.date.today().isoformat()}
    if dry:
        log.info("[DRY] 新增 %d 場、更新 %d 場到 schedule.json（總計 %d 場）",
                 added, updated, len(kept))
        return
    with open(SCHED_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("schedule.json 新增 %d 場、更新 %d 場（總計 %d 場）",
             added, updated, len(kept))


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    _TW_TZ = datetime.timezone(datetime.timedelta(hours=8))
    _now_tw = datetime.datetime.now(_TW_TZ)
    ap = argparse.ArgumentParser(description="NPB/KBO 數據更新腳本")
    ap.add_argument("--dry",          action="store_true", help="只爬不寫入")
    ap.add_argument("--push",         action="store_true", help="完成後自動 git commit + push")
    ap.add_argument("--year",         type=int, default=_now_tw.year)
    ap.add_argument("--months",       nargs="+", type=int,
                    default=[_now_tw.month, min(12, _now_tw.month + 1)],
                    help="要抓的月份（預設：本月+下月）")
    ap.add_argument("--skip-schedule", action="store_true", help="跳過賽程爬取")
    ap.add_argument("--skip-odds",     action="store_true", help="跳過賠率爬取")
    ap.add_argument("--odds-only",     action="store_true", help="只爬賠率，不爬投手/賽程")
    ap.add_argument("--no-playwright", action="store_true", help="停用 Playwright（只用靜態 HTTP）")
    args = ap.parse_args()

    print("=" * 60)
    print(f"NPB/KBO 數據更新 — {args.year}年 | dry={args.dry}")
    print("=" * 60)

    session = requests.Session()
    session.headers.update(_HEADERS)

    today_str = _now_tw.date().isoformat()
    live_stats = {}

    # ── 投手成績：NPB → KBO → BB-Ref 補漏 ──
    if not args.odds_only:
        print("\n[1/4] 抓取 NPB 投手成績（npb.jp）...")
        npb_stats = scrape_npb_pitchers(args.year, session)
        npb_ok = bool(npb_stats)
        if npb_ok:
            live_stats.update(npb_stats)
            print(f"  ✅ npb.jp: {len(npb_stats)} 名投手 "
                  f"（ERA/WHIP/K9/BB9/K%/BB%/FIP）")
        else:
            print("  ⚠️ npb.jp 失敗 → 將用 baseball-reference 補 NPB 數據")

        print("\n     抓取 KBO 投手成績（koreabaseball.com）...")
        kbo_stats = scrape_kbo_pitchers(args.year, session)
        kbo_ok = bool(kbo_stats)
        if kbo_ok:
            live_stats.update(kbo_stats)
            print(f"  ✅ koreabaseball.com + statiz.co.kr: {len(kbo_stats)} 名投手 "
                  f"（ERA/WHIP/K9/BB9/K%/BB%/FIP/xFIP）")
        else:
            print("  ⚠️ koreabaseball.com 失敗 → 將用 baseball-reference 補 KBO 數據")

        # 任一聯盟失敗就用 baseball-reference 補（NPB 在 GH Actions 常被擋）
        if not npb_ok or not kbo_ok:
            missing = []
            if not npb_ok: missing.append("NPB")
            if not kbo_ok: missing.append("KBO")
            print(f"\n     baseball-reference 補充 {'+'.join(missing)} 數據...")
            bbref_stats = scrape_bbref(args.year, session)
            if bbref_stats:
                # 只補沒有抓到的那個聯盟
                added = 0
                for name, p in bbref_stats.items():
                    if p.get("league") in missing or not live_stats.get(name):
                        live_stats[name] = p
                        added += 1
                print(f"  ✅ BB-Ref: 補充 {added} 名投手")
            else:
                print("  ⚠️ BB-Ref 亦失敗；使用 mock 數據（加上衍生指標計算）")

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
            print("    - 設定 ODDS_API_KEY 環境變數（The Odds API）")
            print("    - 嘗試：python scripts/update_stats.py --odds-only --no-playwright")
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
