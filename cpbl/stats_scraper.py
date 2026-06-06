"""
NPB Stats Scraper — 日本職棒專用數據抓取器

資料來源：
  投手成績: npbdata.jp (pd.read_html) → nk-datasets (fallback)
  賽程:     Yahoo Japan Baseball → npb.jp 官方 → 日刊體育 → The Odds API
  先發投手: Yahoo Japan 予告先発頁面
"""
import io
import os
import re
import math
import time
import random
import logging
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 常數
# ─────────────────────────────────────────────────────────────

PITCHER_URL = "https://npbdata.jp/stats/pitcher"
BATTER_URL  = "https://npbdata.jp/stats/fielder"

_FIP_CONSTANT_NPB = 3.20
_FIP_CONSTANT     = 3.20

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "ja,en-US;q=0.8",
}

_NPBDATA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9",
    "Referer": "https://npbdata.jp/",
}

_YAHOO_JP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
    "Referer": "https://baseball.yahoo.co.jp/",
}

_NIKKANSPORTS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "ja,en-US;q=0.8",
    "Referer": "https://www.nikkansports.com/",
}

# NPB team code maps
_NPB_TEAM_MAP = {
    "Yomiuri Giants":               "GNT", "Giants":              "GNT",
    "Hanshin Tigers":               "HNS", "Tigers":              "HNS",
    "Hiroshima Toyo Carp":          "HRC", "Hiroshima Carp":      "HRC", "Carp": "HRC",
    "Yokohama DeNA BayStars":       "YDB", "DeNA BayStars":       "YDB", "BayStars": "YDB",
    "Tokyo Yakult Swallows":        "YKL", "Yakult Swallows":     "YKL", "Swallows": "YKL",
    "Chunichi Dragons":             "CND", "Dragons":             "CND",
    "Fukuoka SoftBank Hawks":       "SBH", "SoftBank Hawks":      "SBH", "Hawks": "SBH",
    "Orix Buffaloes":               "ORX", "Buffaloes":           "ORX",
    "Tohoku Rakuten Golden Eagles": "RKT", "Rakuten Eagles":      "RKT", "Eagles": "RKT",
    "Chiba Lotte Marines":          "LTT", "Lotte Marines":       "LTT", "Marines": "LTT",
    "Saitama Seibu Lions":          "SEI", "Seibu Lions":         "SEI", "Lions": "SEI",
    "Hokkaido Nippon-Ham Fighters": "HAM", "Nippon-Ham Fighters": "HAM", "Fighters": "HAM",
}

# Yahoo Japan 日文隊名 → 內部代碼
_YAHOO_NPB_TEAM_MAP = {
    "巨人":       "GNT", "読売":    "GNT", "読売ジャイアンツ": "GNT",
    "阪神":       "HNS", "タイガース": "HNS",
    "広島":       "HRC", "カープ":  "HRC",
    "ＤｅＮＡ":  "YDB", "DeNA":   "YDB", "ベイスターズ": "YDB",
    "ヤクルト":   "YKL", "スワローズ": "YKL",
    "中日":       "CND", "ドラゴンズ": "CND",
    "ソフトバンク": "SBH", "ホークス": "SBH", "福岡": "SBH",
    "オリックス": "ORX", "バファローズ": "ORX",
    "楽天":       "RKT", "イーグルス": "RKT",
    "ロッテ":     "LTT", "マリーンズ": "LTT",
    "西武":       "SEI", "ライオンズ": "SEI",
    "日本ハム":   "HAM", "ファイターズ": "HAM",
}

# npbdata.jp チーム名 → 内部コード (英語・日本語両方)
_NPBDATA_TEAM_MAP = {
    # 英語
    "Giants": "GNT", "Tigers": "HNS", "Carp": "HRC", "BayStars": "YDB",
    "Swallows": "YKL", "Dragons": "CND", "Hawks": "SBH", "Buffaloes": "ORX",
    "Eagles": "RKT", "Marines": "LTT", "Lions": "SEI", "Fighters": "HAM",
    # 略称
    "G": "GNT", "T": "HNS", "C": "HRC", "DB": "YDB",
    "S": "YKL", "D": "CND", "H": "SBH", "B": "ORX",
    "E": "RKT", "M": "LTT", "L": "SEI", "F": "HAM",
    # 日本語
    "読売": "GNT", "巨人": "GNT",
    "阪神": "HNS",
    "広島": "HRC",
    "DeNA": "YDB", "ＤｅＮＡ": "YDB",
    "ヤクルト": "YKL",
    "中日": "CND",
    "ソフトバンク": "SBH",
    "オリックス": "ORX",
    "楽天": "RKT",
    "ロッテ": "LTT",
    "西武": "SEI",
    "日本ハム": "HAM",
}

# nk-datasets teamID → 本系統 team code
_NK_NPB_TEAM = {
    "YOMIURI": "GNT", "HANSHIN": "HNS", "HIROSHIMA": "HRC",
    "DENA": "YDB",    "YAKULT":  "YKL", "CHUNICHI":  "CND",
    "SOFTBANK":"SBH",  "ORIX":   "ORX", "RAKUTEN":   "RKT",
    "LOTTE":   "LTT",  "SEIBU":  "SEI", "NIPPON-HAM":"HAM",
}

# 投手日文名 → 中文名
_JP_PITCHER_NAME_MAP = {
    "菅野智之": "菅野智之", "戸郷翔征": "戶鄉翔征", "グリフィン": "葛瑞芬",
    "赤星優志": "赤星優志",
    "才木浩人": "才木浩人", "村上頌樹": "村上頌樹", "西勇輝": "西勇輝",
    "ビーズリー": "比茲利",
    "大瀬良大地": "大瀨良大地", "床田寛樹": "床田寬樹", "九里亜蓮": "九里亞蓮",
    "ハーン": "漢恩",
    "東克樹": "東克樹", "石田裕太郎": "石田裕太郎", "大貫晋一": "大貫晉一",
    "ジャクソン": "傑克森",
    "小川泰弘": "小川泰弘", "高橋奎二": "高橋奎二", "サイスニード": "賽斯尼德",
    "吉村貢司郎": "吉村貢司郎",
    "大野雄大": "大野雄大", "柳裕也": "柳裕也", "メヒア": "梅希亞",
    "涌井秀章": "涌井秀章",
    "モイネロ": "莫伊內羅", "有原航平": "有原航平", "東浜巨": "東濱巨",
    "スチュワート・ジュニア": "史都華特二世",
    "山下舜平大": "山下舜平太", "田嶋大樹": "田嶋大樹", "宮城大弥": "宮城大彌",
    "エスピノーザ": "艾斯皮諾薩",
    "早川隆久": "早川隆久", "岸孝之": "岸孝之", "ターリー": "塔利",
    "田中将大": "田中將大",
    "佐々木朗希": "佐佐木朗希", "小島和哉": "小島和哉", "種市篤暉": "種市篤暉",
    "メルセデス": "梅賽德斯",
    "高橋光成": "高橋光成", "平良海馬": "平良海馬", "今井達也": "今井達也",
    "ボー・タカハシ": "寶高橋",
    "伊藤大海": "伊藤大海", "加藤貴之": "加藤貴之", "金村尚真": "金村尚真",
    "マルティネス": "馬丁尼斯",
}

# 中文投手名 → NPB 球隊代碼
_NPB_PITCHER_TEAM: dict[str, str] = {
    "菅野智之": "GNT", "戶鄉翔征": "GNT", "葛瑞芬": "GNT", "赤星優志": "GNT",
    "才木浩人": "HNS", "村上頌樹": "HNS", "西勇輝": "HNS", "比茲利": "HNS",
    "大瀨良大地": "HRC", "床田寬樹": "HRC", "九里亞蓮": "HRC", "漢恩": "HRC",
    "東克樹": "YDB", "石田裕太郎": "YDB", "傑克森": "YDB", "大貫晉一": "YDB",
    "小川泰弘": "YKL", "高橋奎二": "YKL", "賽斯尼德": "YKL", "吉村貢司郎": "YKL",
    "大野雄大": "CND", "柳裕也": "CND", "梅希亞": "CND", "涌井秀章": "CND",
    "莫伊內羅": "SBH", "有原航平": "SBH", "史都華特二世": "SBH", "東濱巨": "SBH",
    "山下舜平太": "ORX", "田嶋大樹": "ORX", "宮城大彌": "ORX", "艾斯皮諾薩": "ORX",
    "早川隆久": "RKT", "岸孝之": "RKT", "田中將大": "RKT", "塔利": "RKT",
    "佐佐木朗希": "LTT", "小島和哉": "LTT", "種市篤暉": "LTT", "梅賽德斯": "LTT",
    "高橋光成": "SEI", "平良海馬": "SEI", "今井達也": "SEI", "寶高橋": "SEI",
    "伊藤大海": "HAM", "加藤貴之": "HAM", "金村尚真": "HAM", "馬丁尼斯": "HAM",
}


# ─────────────────────────────────────────────────────────────
# 數學輔助函數
# ─────────────────────────────────────────────────────────────

def calc_fip(hr: float, bb: float, k: float, ip: float,
             hbp: float = 0.0, constant: float = _FIP_CONSTANT) -> Optional[float]:
    """FIP = (13×HR + 3×(BB+HBP) - 2×K) / IP + constant"""
    if ip <= 0:
        return None
    return round((13 * hr + 3 * (bb + hbp) - 2 * k) / ip + constant, 2)


def calc_k_pct(k9: float, bb9: float, ip: float = 0) -> tuple[float, float]:
    k_pct  = round(k9 / (k9 + 18) * 100, 1) if k9 > 0 else 0.0
    bb_pct = round(bb9 / (bb9 + 18) * 100, 1) if bb9 > 0 else 0.0
    return k_pct, bb_pct


def calc_xfip(k: float, bb: float, fb: float, ip: float,
              lg_hr_fb: float = 0.115) -> Optional[float]:
    if ip <= 0 or fb < 0:
        return None
    exp_hr = fb * lg_hr_fb
    return round((13 * exp_hr + 3 * bb - 2 * k) / ip + _FIP_CONSTANT, 2)


def enrich_pitcher(p: dict) -> dict:
    ip  = float(p.get("innings", p.get("ip", 0)))
    k9  = float(p.get("k9",  0))
    bb9 = float(p.get("bb9", 0))
    era = float(p.get("era", 4.0))

    k_total  = round(k9  * ip / 9, 1) if ip > 0 else 0
    bb_total = round(bb9 * ip / 9, 1) if ip > 0 else 0

    if "k_pct" not in p:
        k_pct, bb_pct = calc_k_pct(k9, bb9, ip)
        p["k_pct"]  = k_pct
        p["bb_pct"] = bb_pct

    if "fip" not in p:
        hr9 = float(p.get("hr9", p.get("hr_per9", 1.0)))
        hr  = round(hr9 * ip / 9, 1) if ip > 0 else 0
        fip = calc_fip(hr, bb_total, k_total, ip)
        if fip is not None:
            p["fip"] = fip
            p.setdefault("xfip", round(fip * 0.97, 2))

    if "babip" not in p:
        fip = p.get("fip", era)
        p["babip"] = round(max(0.200, min(0.380, 0.300 + (era - fip) * 0.04)), 3)

    if "lob_pct" not in p:
        p["lob_pct"] = round(max(55.0, min(85.0, 72.0 + (p.get("fip", era) - era) * 4.0)), 1)

    if "k_bb_pct" not in p:
        p["k_bb_pct"] = round(p.get("k_pct", 0) - p.get("bb_pct", 0), 1)

    return p


def _safe(val, default=0.0):
    try:
        v = float(val)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _calc_fip(hr, bb, hbp, k, ip_val, fip_c=_FIP_CONSTANT_NPB):
    if ip_val <= 0:
        return None
    return round(((hr * 13 + (bb + hbp) * 3 - k * 2) / ip_val) + fip_c, 3)


# ─────────────────────────────────────────────────────────────
# npbdata.jp — 主要投打數據來源（pd.read_html）
# ─────────────────────────────────────────────────────────────

def _npbdata_team_code(raw: str) -> str:
    raw = str(raw).strip()
    return _NPBDATA_TEAM_MAP.get(raw, "")


def _find_col(df_cols, candidates: list[str]) -> str:
    """在 DataFrame 欄位中尋找第一個匹配的候選欄位名稱。"""
    cols_lower = {c.lower(): c for c in df_cols}
    for c in candidates:
        if c in df_cols:
            return c
        if c.lower() in cols_lower:
            return cols_lower[c.lower()]
    return ""


def fetch_npbdata_jp_pitchers(year: int | None = None) -> dict:
    """
    npbdata.jp から NPB 投手成績を取得 (pd.read_html 使用)。

    Returns: dict {player_name: {team, era, fip, whip, k9, bb9, ...}}
    """
    try:
        import pandas as pd
    except ImportError:
        log.warning("pandas not installed — pip install pandas")
        return {}

    _year = year or date.today().year
    url = PITCHER_URL

    try:
        time.sleep(random.uniform(0.5, 1.5))
        resp = requests.get(url, headers=_NPBDATA_HEADERS, timeout=30)
        if resp.status_code != 200:
            log.warning("npbdata.jp pitcher HTTP %s", resp.status_code)
            return {}
        resp.encoding = resp.apparent_encoding or "utf-8"
        tables = pd.read_html(io.StringIO(resp.text))
    except Exception as e:
        log.warning("npbdata.jp pitcher fetch failed: %s", e)
        return {}

    if not tables:
        log.warning("npbdata.jp: no tables found")
        return {}

    # 最大の表を使う（投手成績テーブルは通常最大）
    df = max(tables, key=len)

    result: dict = {}

    # 欄位名候補
    name_col  = _find_col(df.columns, ["名前", "選手名", "投手名", "Name", "Player"])
    team_col  = _find_col(df.columns, ["チーム", "球団", "Team", "Tm"])
    era_col   = _find_col(df.columns, ["防御率", "ERA"])
    ip_col    = _find_col(df.columns, ["投球回", "IP", "innings", "投球回数"])
    so_col    = _find_col(df.columns, ["奪三振", "SO", "K", "三振"])
    bb_col    = _find_col(df.columns, ["四球", "BB", "四死球", "与四球"])
    hr_col    = _find_col(df.columns, ["本塁打", "HR", "被本塁打"])
    h_col     = _find_col(df.columns, ["被安打", "H", "安打", "被打安打数"])
    er_col    = _find_col(df.columns, ["自責点", "ER"])
    g_col     = _find_col(df.columns, ["試合", "G", "登板"])
    gs_col    = _find_col(df.columns, ["先発", "GS", "先発登板"])
    w_col     = _find_col(df.columns, ["勝", "W", "勝利"])
    l_col     = _find_col(df.columns, ["敗", "L", "敗戦"])
    whip_col  = _find_col(df.columns, ["WHIP"])
    hbp_col   = _find_col(df.columns, ["死球", "HBP"])

    if not name_col:
        # 最初の文字列カラムを名前として使う
        str_cols = [c for c in df.columns if df[c].dtype == object]
        if str_cols:
            name_col = str_cols[0]
        else:
            log.warning("npbdata.jp: cannot identify name column in %s", list(df.columns))
            return {}

    for _, row in df.iterrows():
        name = str(row.get(name_col, "")).strip()
        if not name or name in ("nan", "選手名", "名前", "投手名", "Player"):
            continue

        team_raw  = str(row.get(team_col, "")) if team_col else ""
        team_code = _npbdata_team_code(team_raw)

        # IP 変換 (7.1 → 7.33, etc.)
        ip_raw = _safe(row.get(ip_col, 0) if ip_col else 0, 0.0)
        ip = _convert_jp_ip(ip_raw)

        if ip < 1.0:
            continue

        era_raw = _safe(row.get(era_col, 0) if era_col else 0, 0.0)
        so      = _safe(row.get(so_col, 0) if so_col else 0, 0.0)
        bb      = _safe(row.get(bb_col, 0) if bb_col else 0, 0.0)
        hr      = _safe(row.get(hr_col, 0) if hr_col else 0, 0.0)
        h       = _safe(row.get(h_col, 0) if h_col else 0, 0.0)
        er      = _safe(row.get(er_col, 0) if er_col else 0, 0.0)
        g       = max(1, int(_safe(row.get(g_col, 1) if g_col else 1, 1.0)))
        gs      = _safe(row.get(gs_col, 0) if gs_col else 0, 0.0)
        hbp     = _safe(row.get(hbp_col, 0) if hbp_col else 0, 0.0)

        era   = era_raw if era_raw > 0 else (round(er / ip * 9, 3) if ip > 0 else None)
        whip  = _safe(row.get(whip_col, 0) if whip_col else 0, 0.0)
        if whip == 0 and ip > 0:
            whip = round((h + bb) / ip, 3)
        k9    = round(so / ip * 9, 3) if ip > 0 else None
        bb9   = round(bb / ip * 9, 3) if ip > 0 else None
        hr9   = round(hr / ip * 9, 3) if ip > 0 else None
        fip   = _calc_fip(hr, bb, hbp, so, ip)
        is_starter = (gs >= g * 0.5) if gs > 0 else ((ip / g) >= 4.5)

        entry = {
            "team":       team_code,
            "league":     "NPB",
            "year":       _year,
            "era":        era,
            "fip":        fip,
            "whip":       whip if whip > 0 else None,
            "k9":         k9,
            "bb9":        bb9,
            "hr9":        hr9,
            "ip":         round(ip, 1),
            "g":          g,
            "is_starter": bool(is_starter),
            "source":     "npbdata.jp",
        }
        if w_col:
            entry["wins"]   = int(_safe(row.get(w_col, 0), 0))
        if l_col:
            entry["losses"] = int(_safe(row.get(l_col, 0), 0))

        result[name] = entry

    log.info("npbdata.jp pitcher: %d entries", len(result))
    return result


def fetch_npbdata_jp_batters(year: int | None = None) -> dict:
    """
    npbdata.jp から NPB 打者成績を取得 (pd.read_html 使用)。

    Returns: dict {team_code: {ops, avg, hr_per_game, ...}}
    """
    try:
        import pandas as pd
    except ImportError:
        return {}

    _year = year or date.today().year
    url = BATTER_URL

    try:
        time.sleep(random.uniform(0.5, 1.5))
        resp = requests.get(url, headers=_NPBDATA_HEADERS, timeout=30)
        if resp.status_code != 200:
            log.warning("npbdata.jp batter HTTP %s", resp.status_code)
            return {}
        resp.encoding = resp.apparent_encoding or "utf-8"
        tables = pd.read_html(io.StringIO(resp.text))
    except Exception as e:
        log.warning("npbdata.jp batter fetch failed: %s", e)
        return {}

    if not tables:
        return {}

    df = max(tables, key=len)
    result: dict = {}

    name_col = _find_col(df.columns, ["名前", "選手名", "打者名", "Name", "Player"])
    team_col = _find_col(df.columns, ["チーム", "球団", "Team", "Tm"])
    ops_col  = _find_col(df.columns, ["OPS"])
    avg_col  = _find_col(df.columns, ["打率", "AVG", "BA"])
    hr_col   = _find_col(df.columns, ["本塁打", "HR"])
    g_col    = _find_col(df.columns, ["試合", "G"])
    ab_col   = _find_col(df.columns, ["打数", "AB"])
    h_col    = _find_col(df.columns, ["安打", "H"])

    if not team_col:
        return {}

    # チームごとに集計
    team_data: dict[str, list] = {}
    for _, row in df.iterrows():
        team_raw = str(row.get(team_col, "")).strip()
        tc = _npbdata_team_code(team_raw)
        if not tc:
            continue
        ops = _safe(row.get(ops_col, 0) if ops_col else 0, 0.0)
        hr  = _safe(row.get(hr_col, 0) if hr_col else 0, 0.0)
        g   = max(1, int(_safe(row.get(g_col, 1) if g_col else 1, 1.0)))
        ab  = _safe(row.get(ab_col, 0) if ab_col else 0, 0.0)
        h   = _safe(row.get(h_col, 0) if h_col else 0, 0.0)
        team_data.setdefault(tc, []).append({"ops": ops, "hr": hr, "g": g, "ab": ab, "h": h})

    for tc, rows in team_data.items():
        total_ab = sum(r["ab"] for r in rows)
        total_hr = sum(r["hr"] for r in rows)
        total_g  = max(1, sum(r["g"] for r in rows) // len(rows))
        ops_list = [r["ops"] for r in rows if r["ops"] > 0.1]
        ops_avg  = round(sum(ops_list) / len(ops_list), 4) if ops_list else None
        result[tc] = {
            "league":      "NPB",
            "year":        _year,
            "hr_per_game": round(total_hr / total_g, 3) if total_g > 0 else 0.0,
            "source":      "npbdata.jp",
        }
        if ops_avg:
            result[tc]["ops"] = ops_avg

    log.info("npbdata.jp batter team stats: %d teams", len(result))
    return result


def _convert_jp_ip(ip_raw: float) -> float:
    """
    日本の投球回表記変換: 7.1 → 7.33, 7.2 → 7.67 (整数部+小数部/3)
    """
    if ip_raw <= 0:
        return 0.0
    whole = int(ip_raw)
    frac  = round(ip_raw - whole, 2)
    if frac == 0.1:
        return whole + 1/3
    elif frac == 0.2:
        return whole + 2/3
    else:
        return float(ip_raw)


# ─────────────────────────────────────────────────────────────
# nk-datasets — NPB 投打数据（フォールバック）
# ─────────────────────────────────────────────────────────────

def fetch_pitcher_stats_nk(year: int | None = None) -> dict:
    """nk-datasets から NPB 投手成績を取得 (fallback)。"""
    try:
        import nk
        import pandas as pd
    except ImportError:
        log.warning("nk-datasets not installed — pip install nk-datasets pandas")
        return {}

    import warnings
    warnings.filterwarnings("ignore")

    current_year = year or date.today().year
    prev_year    = current_year - 1
    result: dict = {}

    def _process(df_pit, df_people):
        for yr in [current_year, prev_year]:
            mask  = pd.to_numeric(df_pit.get("yearID", pd.Series(dtype=str)), errors="coerce") == yr
            yr_df = df_pit[mask].copy()
            if yr_df.empty:
                continue

            people_cols = [c for c in ["playerID", "nameLast", "nameFirst"] if c in df_people.columns]
            if len(people_cols) >= 1:
                yr_df = yr_df.merge(df_people[people_cols], on="playerID", how="left")
                yr_df["_name"] = (yr_df.get("nameFirst", pd.Series([""] * len(yr_df))).fillna("") +
                                  " " +
                                  yr_df.get("nameLast", pd.Series([""] * len(yr_df))).fillna("")).str.strip()
            else:
                yr_df["_name"] = yr_df["playerID"].astype(str)

            for _, row in yr_df.iterrows():
                name = str(row.get("_name", "")).strip()
                if not name or name == "nan":
                    continue
                tid  = str(row.get("teamID", "")).strip()
                tc   = _NK_NPB_TEAM.get(tid, "")
                if not tc:
                    continue

                ipo = _safe(row.get("IPouts"), 0.0)
                ip  = ipo / 3.0
                if ip < 3.0:
                    continue

                er  = _safe(row.get("ER"),  0.0)
                so  = _safe(row.get("SO"),  0.0)
                bb  = _safe(row.get("BB"),  0.0)
                hbp = _safe(row.get("HBP"), 0.0)
                hr  = _safe(row.get("HR"),  0.0)
                h   = _safe(row.get("H"),   0.0)
                g   = max(1, int(_safe(row.get("G"), 1.0)))
                gs  = _safe(row.get("GS"),  None)

                era  = round(er / ip * 9, 3)       if ip > 0 else None
                whip = round((h + bb) / ip, 3)     if ip > 0 else None
                k9   = round(so / ip * 9, 3)       if ip > 0 else None
                bb9  = round(bb / ip * 9, 3)       if ip > 0 else None
                hr9  = round(hr / ip * 9, 3)       if ip > 0 else None
                fip  = _calc_fip(hr, bb, hbp, so, ip)
                is_starter = (gs >= g * 0.5) if gs is not None else ((ip / g) >= 4.5)

                entry = {
                    "team": tc, "league": "NPB", "year": int(yr),
                    "era": era, "fip": fip, "whip": whip,
                    "k9": k9, "bb9": bb9, "hr9": hr9,
                    "ip": round(ip, 1), "g": g,
                    "is_starter": bool(is_starter),
                    "source": "nk-datasets",
                }
                existing = result.get(name, {})
                if not existing or existing.get("year", 0) <= yr:
                    result[name] = entry

    try:
        npb_pit    = nk.load_npb_pitching()
        npb_people = nk.load_npb_people()
        _process(npb_pit, npb_people)
        log.info("nk-datasets NPB pitchers: %d entries", len(result))
    except Exception as e:
        log.warning("nk-datasets NPB pitching failed: %s", e)

    return result


def fetch_team_stats_nk(year: int | None = None) -> dict:
    """nk-datasets から NPB チーム打撃/投球成績を取得。"""
    try:
        import nk
        import pandas as pd
    except ImportError:
        return {}

    import warnings
    warnings.filterwarnings("ignore")

    current_year = year or date.today().year
    prev_year    = current_year - 1
    result: dict = {}

    def _team_bat(df_bat):
        for yr in [current_year, prev_year]:
            mask  = pd.to_numeric(df_bat.get("yearID", pd.Series(dtype=str)), errors="coerce") == yr
            yr_df = df_bat[mask].copy()
            if yr_df.empty:
                continue
            for col in ["AB", "H", "HR", "BB", "TB", "R", "G", "OPS"]:
                if col in yr_df.columns:
                    yr_df[col] = pd.to_numeric(yr_df[col], errors="coerce").fillna(0)
            for tid, grp in yr_df.groupby("teamID"):
                tc = _NK_NPB_TEAM.get(tid, "")
                if not tc:
                    continue
                total_ab = grp["AB"].sum()
                total_hr = grp["HR"].sum()
                total_g  = max(1, int(grp["G"].sum() // len(grp)))
                ops = None
                if "OPS" in grp.columns and total_ab > 0:
                    raw = float((grp["OPS"] * grp["AB"]).sum() / total_ab)
                    if raw > 0.01:
                        ops = raw
                bat: dict = {
                    "hr_per_game":   round(float(total_hr) / total_g, 3),
                    "runs_per_game": round(float(grp["R"].sum()) / total_g, 3),
                    "year":          int(yr),
                }
                if ops:
                    bat["ops"] = round(ops, 4)
                existing = result.setdefault(tc, {})
                if not existing.get("batting") or existing["batting"].get("year", 0) <= yr:
                    existing["batting"] = bat
                    existing["league"]  = "NPB"

    def _team_pit(df_pit):
        for yr in [current_year, prev_year]:
            mask  = pd.to_numeric(df_pit.get("yearID", pd.Series(dtype=str)), errors="coerce") == yr
            yr_df = df_pit[mask].copy()
            if yr_df.empty:
                continue
            for col in ["IPouts", "ER", "SO", "BB", "HBP", "HR", "H"]:
                if col in yr_df.columns:
                    yr_df[col] = pd.to_numeric(yr_df[col], errors="coerce").fillna(0)
            for tid, grp in yr_df.groupby("teamID"):
                tc = _NK_NPB_TEAM.get(tid, "")
                if not tc:
                    continue
                ip   = grp["IPouts"].sum() / 3.0
                er   = grp["ER"].sum()
                so   = grp["SO"].sum()
                bb   = grp["BB"].sum()
                hbp  = grp["HBP"].sum()
                hr   = grp["HR"].sum()
                h    = grp["H"].sum()
                era  = round(er / max(1, ip) * 9,  3)
                whip = round((h + bb) / max(1, ip), 3)
                k9   = round(so / max(1, ip) * 9,  3)
                bb9  = round(bb / max(1, ip) * 9,  3)
                fip  = _calc_fip(hr, bb, hbp, so, ip)
                pit  = {"era": era, "whip": whip, "k9": k9, "bb9": bb9, "fip": fip, "year": int(yr)}
                existing = result.setdefault(tc, {})
                if not existing.get("pitching") or existing["pitching"].get("year", 0) <= yr:
                    existing["pitching"] = pit

    try:
        npb_bat = nk.load_npb_batting()
        npb_pit = nk.load_npb_pitching()
        _team_bat(npb_bat)
        _team_pit(npb_pit)
    except Exception as e:
        log.warning("nk-datasets NPB team stats failed: %s", e)

    log.info("nk-datasets NPB team stats: %d teams", len(result))
    return result


# ─────────────────────────────────────────────────────────────
# NPB 賽程 — Yahoo Japan Baseball
# ─────────────────────────────────────────────────────────────

def _pair_team_codes(codes: list[str], date_str: str, source: str) -> list[dict]:
    games: list[dict] = []
    seen:  set[tuple] = set()
    i = 0
    while i < len(codes) - 1:
        c1, c2 = codes[i], codes[i + 1]
        if c1 != c2:
            key = tuple(sorted((c1, c2)))
            if key not in seen:
                seen.add(key)
                games.append({
                    "game_id":      f"{date_str}-{c1}-{c2}",
                    "date":         date_str,
                    "time":         "",
                    "away":         c1,
                    "away_name":    "",
                    "home":         c2,
                    "home_name":    "",
                    "venue":        "",
                    "league":       "NPB",
                    "status":       "預定",
                    "away_score":   None,
                    "home_score":   None,
                    "away_pitcher": "",
                    "home_pitcher": "",
                    "_source":      source,
                })
            i += 2
        else:
            i += 1
    return games


def _translate_jp_pitcher(jp_name: str) -> str:
    return _JP_PITCHER_NAME_MAP.get(jp_name.strip(), jp_name.strip())


def fetch_yahoo_npb_schedule(game_date: date) -> list[dict]:
    """
    baseball.yahoo.co.jp から NPB 賽程與先發投手を取得。
    日付固定 URL のみ試行 — 汎用URLは今日のデータを返すため使用不可。
    """
    date_str = game_date.isoformat()
    y, m, d  = game_date.year, game_date.month, game_date.day
    urls = [
        f"https://baseball.yahoo.co.jp/npb/schedule/{y:04d}{m:02d}{d:02d}/",
        f"https://baseball.yahoo.co.jp/npb/schedule/?date={y:04d}{m:02d}{d:02d}",
    ]
    for url in urls:
        try:
            time.sleep(random.uniform(1.0, 3.0))
            resp = requests.get(url, headers=_YAHOO_JP_HEADERS, timeout=15)
            if resp.status_code == 403:
                log.warning("Yahoo Japan NPB 403 for %s", url)
                continue
            if resp.status_code != 200:
                log.warning("Yahoo Japan NPB HTTP %s for %s", resp.status_code, url)
                continue
            resp.encoding = resp.apparent_encoding or "utf-8"
            games = _parse_yahoo_npb_html(resp.text, date_str)
            if games:
                log.info("Yahoo Japan NPB: %d games from %s", len(games), url)
                return games
            log.warning("Yahoo Japan NPB: 0 games parsed from %s", url)
        except Exception as e:
            log.debug("Yahoo Japan NPB %s: %s", url, e)
    return []


def _parse_yahoo_npb_html(html: str, date_str: str) -> list[dict]:
    # Phase 0.1: decode \\uXXXX escapes
    decoded = re.sub(r'\\u([0-9a-fA-F]{4})',
                     lambda m: chr(int(m.group(1), 16)), html)
    sorted_team_keys = sorted(_YAHOO_NPB_TEAM_MAP.keys(), key=len, reverse=True)
    team_pattern = re.compile('(' + '|'.join(re.escape(k) for k in sorted_team_keys) + ')')

    codes_from_decoded: list[str] = []
    for m in team_pattern.finditer(decoded):
        code = _YAHOO_NPB_TEAM_MAP[m.group()]
        if not codes_from_decoded or codes_from_decoded[-1] != code:
            codes_from_decoded.append(code)

    # Phase 0.2: Yahoo Japan team URL patterns
    _YAHOO_URL_CODE: dict[str, str] = {
        "g": "GNT", "t": "HNS", "c": "HRC", "db": "YDB",
        "s": "YKL", "d": "CND", "sb": "SBH", "b": "ORX",
        "e": "RKT", "m": "LTT", "l": "SEI", "f": "HAM",
    }
    _team_url_re = re.compile(r'/npb/(?:team|teams)/([a-z]+)(?:/|")')
    codes_from_urls: list[str] = []
    for m in _team_url_re.finditer(html):
        code = _YAHOO_URL_CODE.get(m.group(1))
        if code and (not codes_from_urls or codes_from_urls[-1] != code):
            codes_from_urls.append(code)

    soup = BeautifulSoup(html, "html.parser")

    # Phase 0: script tags — pitcher names
    sorted_pitcher_keys = sorted(_JP_PITCHER_NAME_MAP.keys(), key=len, reverse=True)
    pitcher_pattern = re.compile('(' + '|'.join(re.escape(k) for k in sorted_pitcher_keys) + ')')
    found_in_scripts: set[str] = set()
    for script in soup.find_all('script'):
        for m in pitcher_pattern.finditer(script.get_text() or ""):
            found_in_scripts.add(_JP_PITCHER_NAME_MAP[m.group()])

    # Phase 0.5: script tags — team codes
    codes_from_scripts: list[str] = []
    for script in soup.find_all('script'):
        sc = script.get_text() or ""
        for m in team_pattern.finditer(sc):
            code = _YAHOO_NPB_TEAM_MAP[m.group()]
            if not codes_from_scripts or codes_from_scripts[-1] != code:
                codes_from_scripts.append(code)

    # Choose best seed
    if codes_from_decoded:
        seed_codes = codes_from_decoded
    elif codes_from_scripts:
        seed_codes = codes_from_scripts
    else:
        seed_codes = codes_from_urls

    for tag in soup.find_all(['script', 'style', 'noscript', 'head', 'nav', 'footer']):
        tag.decompose()

    # Phase 1: text nodes
    codes_in_order: list[str] = list(seed_codes)
    for node in soup.find_all(string=True):
        text = node.strip()
        if not text or len(text) > 50:
            continue
        for m in team_pattern.finditer(text):
            code = _YAHOO_NPB_TEAM_MAP[m.group()]
            if not codes_in_order or codes_in_order[-1] != code:
                codes_in_order.append(code)

    games = _pair_team_codes(codes_in_order, date_str, "yahoo_jp")

    # Phase 2: pitcher assignment
    if games:
        found_zh: set[str] = set(found_in_scripts)
        for node in soup.find_all(string=True):
            text = node.strip()
            if not text or len(text) > 50:
                continue
            for m in pitcher_pattern.finditer(text):
                found_zh.add(_JP_PITCHER_NAME_MAP[m.group()])

        for g in games:
            for zh in found_zh:
                team = _NPB_PITCHER_TEAM.get(zh, "")
                if team == g["away"] and not g["away_pitcher"]:
                    g["away_pitcher"] = zh
                elif team == g["home"] and not g["home_pitcher"]:
                    g["home_pitcher"] = zh

    valid = [g for g in games if g["away"] in _YAHOO_NPB_TEAM_MAP.values()
             and g["home"] in _YAHOO_NPB_TEAM_MAP.values()]
    return valid


# ─────────────────────────────────────────────────────────────
# NPB 賽程 — npb.jp 官方月賽程
# ─────────────────────────────────────────────────────────────

def fetch_npb_official_schedule(game_date: date) -> list[dict]:
    """npb.jp 官方月賽程頁面から指定日の NPB 賽程を取得。"""
    date_str = game_date.isoformat()
    url = (f"https://npb.jp/games/{game_date.year}/"
           f"schedule_{game_date.month:02d}_detail.html")
    try:
        resp = requests.get(url, headers=_YAHOO_JP_HEADERS, timeout=15)
        if resp.status_code != 200:
            log.warning("NPB official HTTP %s for %s", resp.status_code, url)
            return []
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        sorted_pk  = sorted(_JP_PITCHER_NAME_MAP.keys(), key=len, reverse=True)
        pitcher_pat = re.compile('(' + '|'.join(re.escape(k) for k in sorted_pk) + ')')
        found_zh: set[str] = set()
        for script in soup.find_all('script'):
            for m in pitcher_pat.finditer(script.get_text() or ""):
                found_zh.add(_JP_PITCHER_NAME_MAP[m.group()])

        sorted_tk = sorted(_YAHOO_NPB_TEAM_MAP.keys(), key=len, reverse=True)
        team_pat  = re.compile('(' + '|'.join(re.escape(k) for k in sorted_tk) + ')')

        target_day_jp = f"{game_date.month}月{game_date.day}日"
        in_target     = False
        codes: list[str] = []
        date_re_jp    = re.compile(r'\d+月\d+日')

        for tag in soup.find_all(['script', 'style', 'noscript', 'head', 'nav', 'footer']):
            tag.decompose()

        for node in soup.find_all(string=True):
            text = node.strip()
            if not text:
                continue
            if target_day_jp in text:
                in_target = True
                continue
            if in_target and date_re_jp.search(text) and target_day_jp not in text:
                break
            if not in_target or len(text) > 50:
                continue
            for m in team_pat.finditer(text):
                code = _YAHOO_NPB_TEAM_MAP[m.group()]
                if not codes or codes[-1] != code:
                    codes.append(code)

        if not codes:
            return []

        games = _pair_team_codes(codes, date_str, "npb_official")
        for zh in found_zh:
            team = _NPB_PITCHER_TEAM.get(zh, "")
            for g in games:
                if team == g["away"] and not g.get("away_pitcher"):
                    g["away_pitcher"] = zh
                elif team == g["home"] and not g.get("home_pitcher"):
                    g["home_pitcher"] = zh

        log.info("NPB official: %d games for %s", len(games), game_date)
        return games
    except Exception as e:
        log.debug("NPB official fetch failed: %s", e)
        return []


def fetch_npb_official_pitchers(game_date: date, games: list[dict]) -> None:
    """先發投手補強 — npb.jp 官方。缺失投手欄位のみ埋める。"""
    if not games:
        return
    enriched = fetch_npb_official_schedule(game_date)
    if not enriched:
        return
    by_id = {g["game_id"]: g for g in enriched}
    for g in games:
        src = by_id.get(g["game_id"])
        if src:
            if src.get("away_pitcher") and not g.get("away_pitcher"):
                g["away_pitcher"] = src["away_pitcher"]
            if src.get("home_pitcher") and not g.get("home_pitcher"):
                g["home_pitcher"] = src["home_pitcher"]


# ─────────────────────────────────────────────────────────────
# NPB 賽程 — 日刊體育 nikkansports.com
# ─────────────────────────────────────────────────────────────

def fetch_nikkansports_npb(game_date: date) -> list[dict]:
    """日刊體育 nikkansports.com 月賽程ページから NPB 賽程と予告先発を取得。"""
    date_str = game_date.isoformat()
    y, m = game_date.year, game_date.month
    urls = [
        f"https://www.nikkansports.com/baseball/professional/schedule/{y}/{m:02d}/",
        f"https://www.nikkansports.com/baseball/professional/schedule/{y}/",
        "https://www.nikkansports.com/baseball/professional/schedule/",
    ]
    for url in urls:
        try:
            time.sleep(random.uniform(1.0, 2.5))
            resp = requests.get(url, headers=_NIKKANSPORTS_HEADERS, timeout=15)
            if resp.status_code != 200:
                log.debug("Nikkansports HTTP %s for %s", resp.status_code, url)
                continue
            resp.encoding = resp.apparent_encoding or "utf-8"
            games = _parse_nikkansports_html(resp.text, date_str)
            if games:
                log.info("Nikkansports NPB: %d games for %s", len(games), date_str)
                return games
        except Exception as e:
            log.debug("Nikkansports %s: %s", url, e)
    return []


def _parse_nikkansports_html(html: str, date_str: str) -> list[dict]:
    game_date = date.fromisoformat(date_str)
    sorted_team_keys = sorted(_YAHOO_NPB_TEAM_MAP.keys(), key=len, reverse=True)
    team_pattern = re.compile('(' + '|'.join(re.escape(k) for k in sorted_team_keys) + ')')

    soup = BeautifulSoup(html, "html.parser")

    sorted_pitcher_keys = sorted(_JP_PITCHER_NAME_MAP.keys(), key=len, reverse=True)
    pitcher_pat = re.compile('(' + '|'.join(re.escape(k) for k in sorted_pitcher_keys) + ')')
    found_pitchers: set[str] = set()
    for script in soup.find_all('script'):
        for m in pitcher_pat.finditer(script.get_text() or ""):
            found_pitchers.add(_JP_PITCHER_NAME_MAP[m.group()])

    for tag in soup.find_all(['script', 'style', 'noscript', 'head', 'nav', 'footer']):
        tag.decompose()

    in_section = False
    codes: list[str] = []
    date_re = re.compile(r'(\d{1,2})月(\d{1,2})日')

    for node in soup.find_all(string=True):
        text = node.strip()
        if not text:
            continue
        dm = date_re.search(text)
        if dm:
            in_section = (int(dm.group(1)) == game_date.month and
                          int(dm.group(2)) == game_date.day)
        if not in_section or len(text) > 50:
            continue
        for m in team_pattern.finditer(text):
            code = _YAHOO_NPB_TEAM_MAP[m.group()]
            if not codes or codes[-1] != code:
                codes.append(code)

    if not codes:
        return []

    games = _pair_team_codes(codes, date_str, "nikkansports")
    for g in games:
        for zh in found_pitchers:
            team = _NPB_PITCHER_TEAM.get(zh, "")
            if team == g["away"] and not g.get("away_pitcher"):
                g["away_pitcher"] = zh
            elif team == g["home"] and not g.get("home_pitcher"):
                g["home_pitcher"] = zh
    return games


# ─────────────────────────────────────────────────────────────
# NPB 先發投手 — Yahoo Japan 予告先発ページ
# ─────────────────────────────────────────────────────────────

def fetch_yahoo_npb_starter_page(game_date: date) -> list[dict]:
    """Yahoo Japan 予告先発ページから先発投手を取得。"""
    urls = [
        "https://baseball.yahoo.co.jp/npb/starter/",
        f"https://baseball.yahoo.co.jp/npb/starter/?date={game_date.year:04d}{game_date.month:02d}{game_date.day:02d}",
    ]
    for url in urls:
        try:
            time.sleep(random.uniform(0.5, 1.5))
            resp = requests.get(url, headers=_YAHOO_JP_HEADERS, timeout=15)
            if resp.status_code != 200:
                log.debug("Yahoo starter page HTTP %s for %s", resp.status_code, url)
                continue
            resp.encoding = resp.apparent_encoding or "utf-8"
            results = _parse_yahoo_starter_html(resp.text, game_date)
            if results:
                log.info("Yahoo starter page: %d pairs for %s", len(results), game_date)
                return results
        except Exception as e:
            log.debug("Yahoo starter page %s: %s", url, e)
    return []


def _parse_yahoo_starter_html(html: str, game_date: date) -> list[dict]:
    date_str = game_date.isoformat()
    soup = BeautifulSoup(html, "html.parser")

    team_keys_sorted = sorted(_YAHOO_NPB_TEAM_MAP.keys(), key=len, reverse=True)
    team_pat = re.compile("(" + "|".join(re.escape(k) for k in team_keys_sorted) + ")")
    jp_name_pat = re.compile(r'[一-鿿぀-ゟ゠-ヿ＀-￯]{2,8}')

    for tag in soup.find_all(["script", "style", "noscript", "head", "nav", "footer"]):
        tag.decompose()

    results: list[dict] = []

    candidate_containers = (
        soup.find_all("li", class_=re.compile(r"game|match|card|starter", re.I))
        or soup.find_all("div", class_=re.compile(r"game|match|card|starter", re.I))
        or soup.find_all("tr", class_=re.compile(r"game|match|starter", re.I))
    )

    for container in candidate_containers:
        text = container.get_text(" ", strip=True)
        teams = team_pat.findall(text)
        if len(teams) < 2:
            continue
        away_code = _YAHOO_NPB_TEAM_MAP.get(teams[0], "")
        home_code = _YAHOO_NPB_TEAM_MAP.get(teams[-1], "")
        if not away_code or not home_code or away_code == home_code:
            continue
        all_jp = jp_name_pat.findall(text)
        candidates = [n for n in all_jp if not team_pat.match(n) and len(n) >= 2]
        results.append({
            "date":            date_str,
            "away":            away_code,
            "home":            home_code,
            "away_pitcher_jp": candidates[0] if len(candidates) > 0 else "",
            "home_pitcher_jp": candidates[1] if len(candidates) > 1 else "",
        })

    if results:
        return results

    # Fallback: text-scan
    text_nodes = [n.strip() for n in soup.find_all(string=True) if n.strip()]
    gathered: list[tuple[str, str]] = []
    i = 0
    while i < len(text_nodes):
        m = team_pat.search(text_nodes[i])
        if m:
            code = _YAHOO_NPB_TEAM_MAP[m.group()]
            pitcher = ""
            for j in range(i + 1, min(i + 4, len(text_nodes))):
                candidate = text_nodes[j].strip()
                if team_pat.search(candidate):
                    break
                if jp_name_pat.match(candidate) and len(candidate) <= 8 and not re.search(r'\d', candidate):
                    pitcher = candidate
                    break
            gathered.append((code, pitcher))
        i += 1

    j = 0
    while j + 1 < len(gathered):
        away_code, away_pitcher = gathered[j]
        home_code, home_pitcher = gathered[j + 1]
        if away_code != home_code:
            results.append({
                "date":            date_str,
                "away":            away_code,
                "home":            home_code,
                "away_pitcher_jp": away_pitcher,
                "home_pitcher_jp": home_pitcher,
            })
            j += 2
        else:
            j += 1

    return results


def enrich_schedule_with_starters(game_date: date, games: list[dict]) -> None:
    """Yahoo Japan 予告先発ページで games 内の先発投手欄を補完（in-place）。"""
    if not games:
        return
    starters = fetch_yahoo_npb_starter_page(game_date)
    if not starters:
        log.info("enrich_schedule_with_starters: no starters found for %s", game_date)
        return

    starter_map = {(s["away"], s["home"]): s for s in starters}
    enriched = 0
    for g in games:
        if g.get("league") != "NPB":
            continue
        s = starter_map.get((g.get("away", ""), g.get("home", "")))
        if not s:
            continue
        if s.get("away_pitcher_jp") and not g.get("away_pitcher"):
            g["away_pitcher"] = _translate_jp_pitcher(s["away_pitcher_jp"])
            enriched += 1
        if s.get("home_pitcher_jp") and not g.get("home_pitcher"):
            g["home_pitcher"] = _translate_jp_pitcher(s["home_pitcher_jp"])
            enriched += 1

    if enriched:
        log.info("enrich_schedule_with_starters: filled %d pitcher slots for %s",
                 enriched, game_date)


# ─────────────────────────────────────────────────────────────
# The Odds API — NPB 賽程保底（無先發）
# ─────────────────────────────────────────────────────────────

def fetch_odds_api_schedule(game_date: date, api_key: str = "") -> list[dict]:
    """The Odds API /events から NPB 賽程を取得（NPB のみ）。"""
    if not api_key:
        api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        return []

    date_str   = game_date.isoformat()
    tw_midnight = datetime(game_date.year, game_date.month, game_date.day,
                           tzinfo=timezone(timedelta(hours=8)))
    from_utc = tw_midnight.astimezone(timezone.utc)
    to_utc   = (tw_midnight + timedelta(hours=24)).astimezone(timezone.utc)

    results: list[dict] = []
    url = "https://api.the-odds-api.com/v4/sports/baseball_npb/events"
    params = {
        "apiKey":           api_key,
        "dateFormat":       "iso",
        "commenceTimeFrom": from_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commenceTimeTo":   to_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=10)
        if resp.status_code == 404:
            log.debug("Odds API: baseball_npb not found")
            return []
        if resp.status_code == 401:
            log.warning("Odds API: invalid API key")
            return []
        if resp.status_code != 200:
            log.debug("Odds API NPB: HTTP %s", resp.status_code)
            return []
        events = resp.json()
        if not isinstance(events, list):
            return []
        for ev in events:
            home_name = ev.get("home_team", "")
            away_name = ev.get("away_team", "")
            home_code = _NPB_TEAM_MAP.get(home_name)
            away_code = _NPB_TEAM_MAP.get(away_name)
            if not home_code:
                hl = home_name.lower()
                for k, v in _NPB_TEAM_MAP.items():
                    if k.lower() in hl:
                        home_code = v; break
            if not away_code:
                al = away_name.lower()
                for k, v in _NPB_TEAM_MAP.items():
                    if k.lower() in al:
                        away_code = v; break
            if not home_code or not away_code:
                continue
            game_time = ""
            try:
                dt_utc = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
                dt_tw  = dt_utc.astimezone(timezone(timedelta(hours=8)))
                game_time = dt_tw.strftime("%H:%M")
            except Exception:
                pass
            results.append({
                "game_id":      f"{date_str}-{away_code}-{home_code}",
                "date":         date_str,
                "time":         game_time,
                "away":         away_code,
                "away_name":    away_name,
                "home":         home_code,
                "home_name":    home_name,
                "venue":        "",
                "league":       "NPB",
                "status":       "預定",
                "away_score":   None,
                "home_score":   None,
                "away_pitcher": "",
                "home_pitcher": "",
                "_source":      "odds_api_events",
            })
        log.info("Odds API NPB events: %d games", len(results))
    except Exception as e:
        log.debug("Odds API NPB: %s", e)

    return results


# ─────────────────────────────────────────────────────────────
# 多來源賽程彙整
# ─────────────────────────────────────────────────────────────

def fetch_schedule_multi(game_date: date, odds_api_key: str = "") -> list[dict]:
    """
    NPB 多來源賽程，優先順序：
      1. Yahoo Japan Baseball
      2. npb.jp 官方月賽程
      3. 日刊體育 nikkansports.com
      4. The Odds API /events（保底，無先發）
    """
    games: list[dict] = []

    # 1. Yahoo Japan
    try:
        g = fetch_yahoo_npb_schedule(game_date)
        if g:
            games = g
            log.info("Schedule NPB from Yahoo Japan: %d games", len(games))
    except Exception as e:
        log.warning("Yahoo Japan schedule exception: %s", e)

    # 2. npb.jp 官方
    if not games:
        try:
            g = fetch_npb_official_schedule(game_date)
            if g:
                games = g
                log.info("Schedule NPB from npb.jp official: %d games", len(games))
        except Exception as e:
            log.debug("npb.jp official failed: %s", e)

    # 3. 日刊體育
    if not games:
        try:
            g = fetch_nikkansports_npb(game_date)
            if g:
                games = g
                log.info("Schedule NPB from Nikkansports: %d games", len(games))
        except Exception as e:
            log.debug("Nikkansports failed: %s", e)

    # 4. The Odds API 保底
    if not games:
        try:
            g = fetch_odds_api_schedule(game_date, api_key=odds_api_key)
            if g:
                games = g
                log.info("Schedule NPB from Odds API: %d games", len(games))
        except Exception as e:
            log.debug("Odds API schedule failed: %s", e)

    # 先發投手補強
    if games and any(not g.get("away_pitcher") or not g.get("home_pitcher") for g in games):
        fetch_npb_official_pitchers(game_date, games)

    if not games:
        log.warning("All NPB schedule sources failed for %s", game_date)

    return games
