"""
CPBL V1.0 勝負預測模型

權重分配：
  先發投手   35%
  打線       20%
  牛棚       15%
  主客場      8%
  近期狀態    8%
  對戰紀錄    5%
  傷兵        4%
  天氣        3%
  守備        2%
"""
from .elo import ELOSystem
from .mock_data import PITCHERS, TEAM_STATS, H2H, VENUE_FACTORS

WEIGHTS = {
    "starter":     0.35,
    "lineup":      0.20,
    "bullpen":     0.15,
    "home_away":   0.08,
    "recent_form": 0.08,
    "h2h":         0.05,
    "injuries":    0.04,
    "weather":     0.03,
    "defense":     0.02,
}

LEAGUE_AVG_ERA = 3.80
LEAGUE_AVG_OPS = 0.760


class PredictionModel:
    def __init__(self, elo: ELOSystem | None = None):
        self.elo = elo or ELOSystem()

    def predict(self, game: dict, weather: dict | None = None) -> dict:
        ht = game["home"]
        at = game["away"]
        if not ht or not at:
            return {}

        hp = PITCHERS.get(game.get("home_pitcher") or "", {})
        ap = PITCHERS.get(game.get("away_pitcher") or "", {})

        factors: dict[str, dict] = {}

        # ── 1. 先發投手 ────────────────────────────
        home_ps = _pitcher_score(hp)
        away_ps = _pitcher_score(ap)
        factors["starter"] = {
            "label": "先發投手",
            "home_score": home_ps,
            "away_score": away_ps,
            "advantage": home_ps - away_ps,   # +正 = 主隊佔優
            "detail": _pitcher_detail(hp, ap),
        }

        # ── 2. 打線強度 ────────────────────────────
        home_bat = _lineup_score(ht)
        away_bat = _lineup_score(at)
        factors["lineup"] = {
            "label": "打線強度",
            "home_score": home_bat,
            "away_score": away_bat,
            "advantage": home_bat - away_bat,
            "detail": _lineup_detail(ht, at),
        }

        # ── 3. 牛棚戰力 ────────────────────────────
        home_bp = _bullpen_score(ht)
        away_bp = _bullpen_score(at)
        factors["bullpen"] = {
            "label": "牛棚戰力",
            "home_score": home_bp,
            "away_score": away_bp,
            "advantage": home_bp - away_bp,
            "detail": _bullpen_detail(ht, at),
        }

        # ── 4. 主客場 ──────────────────────────────
        venue = game.get("venue", "")
        home_ha = _home_away_score(ht, at, venue)
        factors["home_away"] = {
            "label": "主客場",
            "home_score": 55 + home_ha,
            "away_score": 45 - home_ha,
            "advantage": home_ha * 2,
            "detail": _ha_detail(ht, at, venue),
        }

        # ── 5. 近期狀態 ────────────────────────────
        home_rf = _recent_form_score(ht)
        away_rf = _recent_form_score(at)
        factors["recent_form"] = {
            "label": "近期狀態",
            "home_score": home_rf,
            "away_score": away_rf,
            "advantage": home_rf - away_rf,
            "detail": _form_detail(ht, at),
        }

        # ── 6. 對戰紀錄 ────────────────────────────
        h2h_adv = _h2h_score(at, ht)
        factors["h2h"] = {
            "label": "對戰紀錄",
            "home_score": 50 + h2h_adv,
            "away_score": 50 - h2h_adv,
            "advantage": h2h_adv * 2,
            "detail": _h2h_detail(at, ht),
        }

        # ── 7. 傷兵 ────────────────────────────────
        home_inj = _injury_score(ht)
        away_inj = _injury_score(at)
        factors["injuries"] = {
            "label": "傷兵狀況",
            "home_score": home_inj,
            "away_score": away_inj,
            "advantage": home_inj - away_inj,
            "detail": _injury_detail(ht, at),
        }

        # ── 8. 天氣 ────────────────────────────────
        w_adv = _weather_score(weather, venue)
        factors["weather"] = {
            "label": "天氣",
            "home_score": 50 + w_adv,
            "away_score": 50 - w_adv,
            "advantage": w_adv * 2,
            "detail": _weather_detail(weather),
        }

        # ── 9. 守備 ────────────────────────────────
        home_def = _defense_score(ht)
        away_def = _defense_score(at)
        factors["defense"] = {
            "label": "守備能力",
            "home_score": home_def,
            "away_score": away_def,
            "advantage": home_def - away_def,
            "detail": _defense_detail(ht, at),
        }

        # ── 整合勝率 ───────────────────────────────
        # 以 ELO 為基礎，各因子進行調整
        elo_base = self.elo.win_probability(
            ht, at,
            hp.get("era"),
            ap.get("era"),
        )
        home_prob = elo_base

        for key, w in WEIGHTS.items():
            adv = factors[key]["advantage"]       # -100 ~ +100
            adj = (adv / 100.0) * w * 0.5        # 最大調整 ±w/2
            home_prob += adj

        home_prob = max(0.05, min(0.95, home_prob))

        return {
            "home_win_prob": round(home_prob, 4),
            "away_win_prob": round(1.0 - home_prob, 4),
            "elo_base": round(elo_base, 4),
            "factors": factors,
            "winner":  "home" if home_prob >= 0.5 else "away",
            "confidence": round(abs(home_prob - 0.5) * 200, 1),  # 0~100
            "home_elo": self.elo.get(ht),
            "away_elo": self.elo.get(at),
        }


# ──────────────────────────────────────────────
# 各因子評分函式（0~100，50=平均）
# ──────────────────────────────────────────────

def _pitcher_score(p: dict) -> float:
    if not p:
        return 50.0
    s = 50.0
    era = p.get("era", LEAGUE_AVG_ERA)
    fip = p.get("fip", LEAGUE_AVG_ERA)
    k9  = p.get("k9", 7.5)
    bb9 = p.get("bb9", 3.2)
    recent5 = p.get("recent_5_era", era)

    s += (LEAGUE_AVG_ERA - era) * 8      # ERA 比聯盟平均好+分
    s += (LEAGUE_AVG_ERA - fip) * 5      # FIP
    s += (k9 - 7.5) * 1.5               # 三振率
    s -= (bb9 - 3.2) * 2.0              # 四壞球率
    s += (era - recent5) * 4            # 近況加成（負=狀態下滑）
    return max(10.0, min(90.0, s))


def _pitcher_detail(hp: dict, ap: dict) -> str:
    if not hp or not ap:
        return "先發投手資料不完整"
    lines = []
    for label, p in [("主隊", hp), ("客隊", ap)]:
        t = _trend_label(p.get("era", 3.8), p.get("recent_5_era", 3.8))
        lines.append(
            f"{label} ERA {p.get('era','-')} / FIP {p.get('fip','-')} "
            f"/ 近5場ERA {p.get('recent_5_era','-')} {t}"
        )
    return " | ".join(lines)


def _trend_label(season: float, recent: float) -> str:
    d = season - recent
    if d > 0.5: return "🔥 熱門"
    if d < -0.5: return "❄️ 降溫"
    return "➡️ 穩定"


def _lineup_score(team: str) -> float:
    b = TEAM_STATS.get(team, {}).get("batting", {})
    if not b:
        return 50.0
    s = 50.0
    s += (b.get("ops", LEAGUE_AVG_OPS) - LEAGUE_AVG_OPS) * 60
    s += (b.get("wrc_plus", 100) - 100) * 0.4
    r7 = b.get("recent_7_ops", b.get("ops", LEAGUE_AVG_OPS))
    s += (r7 - LEAGUE_AVG_OPS) * 20   # 近7天加成
    return max(10.0, min(90.0, s))


def _lineup_detail(ht: str, at: str) -> str:
    bh = TEAM_STATS.get(ht, {}).get("batting", {})
    ba = TEAM_STATS.get(at, {}).get("batting", {})
    return (
        f"主隊OPS {bh.get('ops','-')} wRC+ {bh.get('wrc_plus','-')} "
        f"| 客隊OPS {ba.get('ops','-')} wRC+ {ba.get('wrc_plus','-')}"
    )


def _bullpen_score(team: str) -> float:
    bp = TEAM_STATS.get(team, {}).get("bullpen", {})
    if not bp:
        return 50.0
    s = 50.0
    s += (LEAGUE_AVG_ERA - bp.get("era", LEAGUE_AVG_ERA)) * 7
    s += (LEAGUE_AVG_ERA - bp.get("fip", LEAGUE_AVG_ERA)) * 4
    fatigue = bp.get("fatigue_score", 50)
    s -= (fatigue - 30) * 0.3          # 疲勞扣分
    consec = bp.get("closer_consecutive_days", 0)
    s -= consec * 5                    # 連續出賽 closer 扣分
    return max(10.0, min(90.0, s))


def _bullpen_detail(ht: str, at: str) -> str:
    bh = TEAM_STATS.get(ht, {}).get("bullpen", {})
    ba = TEAM_STATS.get(at, {}).get("bullpen", {})
    return (
        f"主隊牛棚ERA {bh.get('era','-')} 疲勞指數 {bh.get('fatigue_score','-')} "
        f"| 客隊牛棚ERA {ba.get('era','-')} 疲勞指數 {ba.get('fatigue_score','-')}"
    )


def _home_away_score(ht: str, at: str, venue: str) -> float:
    """主場加成 + 球場環境因子，回傳 -25~+25"""
    home_rec = TEAM_STATS.get(ht, {}).get("record", {})
    away_rec = TEAM_STATS.get(at, {}).get("record", {})
    hw = home_rec.get("home_w", 0)
    hl = home_rec.get("home_l", 1)
    aw = away_rec.get("away_w", 0)
    al = away_rec.get("away_l", 1)
    home_wpct = hw / (hw + hl)
    away_wpct = aw / (aw + al)
    adv = (home_wpct - away_wpct) * 20   # -20~+20
    vf = VENUE_FACTORS.get(venue, {}).get("run_factor", 1.0)
    # 較多得分的球場對打線更好的隊有利
    adv += (vf - 1.0) * 5
    return max(-25.0, min(25.0, adv))


def _ha_detail(ht: str, at: str, venue: str) -> str:
    hr = TEAM_STATS.get(ht, {}).get("record", {})
    ar = TEAM_STATS.get(at, {}).get("record", {})
    vf = VENUE_FACTORS.get(venue, {}).get("note", "")
    return (
        f"主隊主場 {hr.get('home_w',0)}勝{hr.get('home_l',0)}敗 "
        f"| 客隊客場 {ar.get('away_w',0)}勝{ar.get('away_l',0)}敗 "
        f"| {venue} {vf}"
    )


def _recent_form_score(team: str) -> float:
    rec = TEAM_STATS.get(team, {}).get("record", {})
    last10 = rec.get("last10", [])
    if not last10:
        return 50.0
    win_rate = sum(last10) / len(last10)
    run_diff = rec.get("run_diff", 0)
    s = 50.0
    s += (win_rate - 0.5) * 60
    s += min(15, run_diff / 8)
    return max(10.0, min(90.0, s))


def _form_detail(ht: str, at: str) -> str:
    rh = TEAM_STATS.get(ht, {}).get("record", {})
    ra = TEAM_STATS.get(at, {}).get("record", {})
    lh = rh.get("last5", [])
    la = ra.get("last5", [])
    def fmt(ls): return "".join("●" if r else "○" for r in ls)
    return (
        f"主隊近5場 {fmt(lh)} 得失分差 {rh.get('run_diff',0):+d} "
        f"| 客隊近5場 {fmt(la)} 得失分差 {ra.get('run_diff',0):+d}"
    )


def _h2h_score(away_team: str, home_team: str) -> float:
    """主場隊在對戰中的優勢 (-15~+15)"""
    record = H2H.get(away_team, {}).get(home_team, [5, 5])
    away_w, home_w = record[0], record[1]
    total = away_w + home_w
    if total == 0:
        return 0.0
    home_rate = home_w / total
    return (home_rate - 0.5) * 30


def _h2h_detail(away_team: str, home_team: str) -> str:
    rec = H2H.get(away_team, {}).get(home_team, [5, 5])
    return f"本季對戰：客隊 {rec[0]} 勝 vs 主隊 {rec[1]} 勝"


def _injury_score(team: str) -> float:
    injuries = TEAM_STATS.get(team, {}).get("injuries", [])
    if not injuries:
        return 50.0
    return max(10.0, 50.0 - len(injuries) * 8)


def _injury_detail(ht: str, at: str) -> str:
    hi = TEAM_STATS.get(ht, {}).get("injuries", [])
    ai = TEAM_STATS.get(at, {}).get("injuries", [])
    h_str = "、".join(hi) if hi else "無傷兵"
    a_str = "、".join(ai) if ai else "無傷兵"
    return f"主隊：{h_str} | 客隊：{a_str}"


def _weather_score(weather: dict | None, venue: str) -> float:
    """天氣對主隊的影響 (-15~+15)"""
    if not weather:
        return 0.0
    temp = weather.get("temp_c", 25)
    wind_kph = weather.get("wind_kph", 10)
    humidity = weather.get("humidity", 70)
    score = 0.0
    if temp > 30:
        score += 3   # 高溫有利打擊
    if wind_kph > 30:
        score -= 2   # 強風增加不確定性（略不利主隊）
    if humidity > 85:
        score -= 1
    return max(-15.0, min(15.0, score))


def _weather_detail(weather: dict | None) -> str:
    if not weather:
        return "天氣資料無法取得"
    return (
        f"{weather.get('condition','未知')} "
        f"氣溫 {weather.get('temp_c','-')}°C "
        f"風速 {weather.get('wind_kph','-')}km/h "
        f"濕度 {weather.get('humidity','-')}%"
    )


def _defense_score(team: str) -> float:
    d = TEAM_STATS.get(team, {}).get("defense", {})
    if not d:
        return 50.0
    s = 50.0
    s += (d.get("fielding_pct", 0.980) - 0.980) * 800
    s += d.get("drs", 0) * 0.8
    return max(10.0, min(90.0, s))


def _defense_detail(ht: str, at: str) -> str:
    dh = TEAM_STATS.get(ht, {}).get("defense", {})
    da = TEAM_STATS.get(at, {}).get("defense", {})
    return (
        f"主隊守備率 {dh.get('fielding_pct','-')} DRS {dh.get('drs','-'):+} "
        f"| 客隊守備率 {da.get('fielding_pct','-')} DRS {da.get('drs','-'):+}"
    )
