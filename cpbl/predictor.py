"""
CPBL V2.0 勝負預測模型 — 9大因子 100+變量

權重分配：
  先發投手   35%  ERA/FIP/xFIP/WHIP/BABIP/LOB%/K-BB%/WPA/RE24/近況/洋將
  打線強度   20%  OPS/wOBA/wRC+/得分/全壘打/近7/14/30天OPS趨勢
  牛棚戰力   15%  ERA/FIP/WHIP/救援率/接管率/疲勞指數/連續出賽/近7天用量
  主客場      8%  主場/客場勝率 + 球場環境 + 固定主場加成
  近期狀態    8%  近5/10場勝率 + 得失分差 + 出賽密度疲勞
  對戰紀錄    5%  本季對戰直接紀錄
  傷兵狀況    4%  S/A/B 三級傷兵分類扣分
  天氣影響    3%  氣溫/風速/濕度/降雨
  守備能力    2%  守備率/DRS/UZR/失誤數
"""
from .elo import ELOSystem
from .mock_data import PITCHERS, TEAM_STATS, H2H, VENUE_FACTORS
from . import odds as odds_module

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

LEAGUE_AVG_ERA  = 3.80
LEAGUE_AVG_OPS  = 0.760
LEAGUE_AVG_WOBA = 0.330
LEAGUE_AVG_WRC  = 100
LEAGUE_AVG_RPG  = 4.8
FOREIGN_PREMIUM = 4.0   # 洋將平均表現高於本土投手


class PredictionModel:
    def __init__(self, elo: ELOSystem | None = None):
        self.elo = elo or ELOSystem()

    def predict(self, game: dict, weather: dict | None = None,
                odds_data: dict | None = None) -> dict:
        ht = game["home"]
        at = game["away"]
        if not ht or not at:
            return {}

        # Pitcher name lookup — accept string or dict
        hp_name = game.get("home_pitcher") or ""
        ap_name = game.get("away_pitcher") or ""
        if not hp_name and isinstance(game.get("home_sp"), str):
            hp_name = game["home_sp"]
        if not ap_name and isinstance(game.get("away_sp"), str):
            ap_name = game["away_sp"]
        hp = PITCHERS.get(hp_name, {})
        ap = PITCHERS.get(ap_name, {})

        factors: dict[str, dict] = {}

        # ── 1. 先發投手 (35%) ──────────────────────────
        home_ps = _pitcher_score(hp)
        away_ps = _pitcher_score(ap)
        factors["starter"] = {
            "label": "先發投手",
            "home_score": home_ps,
            "away_score": away_ps,
            "advantage": home_ps - away_ps,
            "detail": _pitcher_detail(hp, ap),
        }

        # ── 2. 打線強度 (20%) ──────────────────────────
        home_bat = _lineup_score(ht)
        away_bat = _lineup_score(at)
        factors["lineup"] = {
            "label": "打線強度",
            "home_score": home_bat,
            "away_score": away_bat,
            "advantage": home_bat - away_bat,
            "detail": _lineup_detail(ht, at),
        }

        # ── 3. 牛棚戰力 (15%) ──────────────────────────
        home_bp = _bullpen_score(ht)
        away_bp = _bullpen_score(at)
        factors["bullpen"] = {
            "label": "牛棚戰力",
            "home_score": home_bp,
            "away_score": away_bp,
            "advantage": home_bp - away_bp,
            "detail": _bullpen_detail(ht, at),
        }

        # ── 4. 主客場 (8%) ─────────────────────────────
        venue = game.get("venue", "")
        home_ha = _home_away_score(ht, at, venue)
        factors["home_away"] = {
            "label": "主客場",
            "home_score": 50 + home_ha,
            "away_score": 50 - home_ha,
            "advantage": home_ha * 2,
            "detail": _ha_detail(ht, at, venue),
        }

        # ── 5. 近期狀態 (8%) ───────────────────────────
        home_rf = _recent_form_score(ht)
        away_rf = _recent_form_score(at)
        factors["recent_form"] = {
            "label": "近期狀態",
            "home_score": home_rf,
            "away_score": away_rf,
            "advantage": home_rf - away_rf,
            "detail": _form_detail(ht, at),
        }

        # ── 6. 對戰紀錄 (5%) ───────────────────────────
        h2h_adv = _h2h_score(at, ht)
        factors["h2h"] = {
            "label": "對戰紀錄",
            "home_score": 50 + h2h_adv,
            "away_score": 50 - h2h_adv,
            "advantage": h2h_adv * 2,
            "detail": _h2h_detail(at, ht),
        }

        # ── 7. 傷兵狀況 (4%) ───────────────────────────
        home_inj = _injury_score(ht)
        away_inj = _injury_score(at)
        factors["injuries"] = {
            "label": "傷兵狀況",
            "home_score": home_inj,
            "away_score": away_inj,
            "advantage": home_inj - away_inj,
            "detail": _injury_detail(ht, at),
        }

        # ── 8. 天氣影響 (3%) ───────────────────────────
        w_adv = _weather_score(weather, venue)
        factors["weather"] = {
            "label": "天氣",
            "home_score": 50 + w_adv,
            "away_score": 50 - w_adv,
            "advantage": w_adv * 2,
            "detail": _weather_detail(weather),
        }

        # ── 9. 守備能力 (2%) ───────────────────────────
        home_def = _defense_score(ht)
        away_def = _defense_score(at)
        factors["defense"] = {
            "label": "守備能力",
            "home_score": home_def,
            "away_score": away_def,
            "advantage": home_def - away_def,
            "detail": _defense_detail(ht, at),
        }

        # ── 整合勝率（ELO 為基底，各因子加權調整）────
        elo_base = self.elo.win_probability(
            ht, at,
            hp.get("era"),
            ap.get("era"),
        )
        home_prob = elo_base
        for key, w in WEIGHTS.items():
            adv = factors[key]["advantage"]
            adj = (adv / 100.0) * w * 0.5
            home_prob += adj
        home_prob = max(0.05, min(0.95, home_prob))

        # ── 盤口資料 (passthrough + 輕微校正) ──────────
        odds_key = f"{at}-{ht}"
        if odds_data is None:
            odds_data = odds_module.MOCK_ODDS.get(odds_key, {})

        if odds_data:
            o_analysis = odds_module.analyze(odds_data, home_prob)
            # 盤口校正：85% 模型 + 15% 市場（市場為百分比需先除以100）
            market_hp = o_analysis.get("market_home_prob", home_prob * 100) / 100.0
            home_prob  = home_prob * 0.85 + market_hp * 0.15
            home_prob  = max(0.05, min(0.95, home_prob))
            factors["odds"] = {
                "label": "盤口 / 賠率",
                "home_score": 50 + o_analysis["advantage"],
                "away_score": 50 - o_analysis["advantage"],
                "advantage":  o_analysis["advantage"],
                "detail":     o_analysis["detail"],
                "analysis":   o_analysis,
                "curr_home_odds":   odds_data.get("curr_home_odds"),
                "curr_away_odds":   odds_data.get("curr_away_odds"),
                "open_home_odds":   odds_data.get("open_home_odds"),
                "open_away_odds":   odds_data.get("open_away_odds"),
                "run_line":         odds_data.get("run_line"),
                "total_line":       odds_data.get("total"),
                "over_odds":        odds_data.get("over_odds"),
                "under_odds":       odds_data.get("under_odds"),
                "public_home_pct":  odds_data.get("public_home_pct"),
                "public_away_pct":  odds_data.get("public_away_pct"),
                "market_home_prob": o_analysis["market_home_prob"],
                "signals":          o_analysis.get("signals", []),
            }
        else:
            factors["odds"] = {
                "label": "盤口 / 賠率",
                "home_score": 50, "away_score": 50,
                "advantage": 0, "detail": "無賠率資料",
                "curr_home_odds": 0, "curr_away_odds": 0,
                "total_line": 8.5, "signals": [],
                "market_home_prob": round(home_prob * 100, 1),
            }

        return {
            "home_win_prob": round(home_prob, 4),
            "away_win_prob": round(1.0 - home_prob, 4),
            "elo_base":  round(elo_base, 4),
            "factors":   factors,
            "winner":    "home" if home_prob >= 0.5 else "away",
            "confidence": round(abs(home_prob - 0.5) * 200, 1),
            "home_elo":  self.elo.get(ht),
            "away_elo":  self.elo.get(at),
        }


# ──────────────────────────────────────────────────────────────────
# 各因子評分函式（0~100，50=聯盟平均）
# ──────────────────────────────────────────────────────────────────

def _pitcher_score(p: dict) -> float:
    """先發投手綜合評分 (0~100)。涵蓋 11 個指標 + 近況趨勢 + 洋將加成。"""
    if not p:
        return 50.0
    s = 50.0

    era   = p.get("era",   LEAGUE_AVG_ERA)
    fip   = p.get("fip",   LEAGUE_AVG_ERA)
    xfip  = p.get("xfip",  LEAGUE_AVG_ERA)
    whip  = p.get("whip",  1.30)
    k9    = p.get("k9",    7.5)
    bb9   = p.get("bb9",   3.2)
    babip = p.get("babip", 0.300)
    lob   = p.get("lob_pct",   72.0)
    k_bb  = p.get("k_bb_pct",  13.0)
    wpa   = p.get("wpa",   0.0)
    re24  = p.get("re24",  0.0)
    r3    = p.get("recent_3_era",  era)
    r5    = p.get("recent_5_era",  era)
    r10   = p.get("recent_10_era", era)

    # xFIP 最能預測未來表現（排除守備及全壘打幸運）
    s += (LEAGUE_AVG_ERA - xfip) * 6.0
    # FIP 排除守備影響
    s += (LEAGUE_AVG_ERA - fip)  * 4.0
    # ERA 實際成績
    s += (LEAGUE_AVG_ERA - era)  * 2.5
    # WHIP 跑壘者上壘率
    s += (1.30 - whip) * 12.0
    # 三振 / 四壞球效率
    s += (k9  - 7.5) * 1.2
    s -= (bb9 - 3.2) * 1.8
    s += (k_bb - 13.0) * 0.25
    # BABIP 幸運/倒楣指標（高BABIP=不幸→預期改善）
    s += (babip - 0.300) * 20.0
    # LOB% 得點圈壓制率（聯盟平均約 72%）
    s += (lob - 72.0) * 0.15
    # 貢獻值指標
    s += wpa  * 1.2
    s += re24 * 0.06

    # 近況趨勢（近3場最重）
    recent_era = r3 * 0.50 + r5 * 0.30 + r10 * 0.20
    s += (era - recent_era) * 3.5   # 正值 = 近況好於季均

    # 洋投評分加成（取代固定值，依實際指標計算）
    if p.get("foreign"):
        fs = foreign_score(p)
        s += (fs - 50.0) * 0.10  # 中位分=50 → 不增不減；越高加越多

    return max(10.0, min(90.0, s))


def _pitcher_detail(hp: dict, ap: dict) -> str:
    if not hp and not ap:
        return "先發投手資料不完整"
    lines = []
    for label, p in [("主隊", hp), ("客隊", ap)]:
        if not p:
            lines.append(f"{label} 無資料")
            continue
        foreign_tag = "🌏" if p.get("foreign") else ""
        trend = _trend_label(p.get("era", LEAGUE_AVG_ERA),
                             p.get("recent_3_era", p.get("era", LEAGUE_AVG_ERA)))
        lines.append(
            f"{label}{foreign_tag} ERA {p.get('era','-')} FIP {p.get('fip','-')} "
            f"xFIP {p.get('xfip','-')} WHIP {p.get('whip','-')} K/9 {p.get('k9','-')} "
            f"K-BB% {p.get('k_bb_pct','-')} | 近3ERA {p.get('recent_3_era','-')} {trend}"
        )
    return " | ".join(lines)


def _trend_label(season_era: float, recent_era: float) -> str:
    d = season_era - recent_era
    if d > 0.5:  return "🔥 上升中"
    if d < -0.5: return "❄️ 下滑中"
    return "➡️ 穩定"


def foreign_score(p: dict) -> float:
    """
    洋投綜合評分 0-100
    ERA 25% | WHIP 20% | K-BB% 20% | 近5場狀態 20% | BABIP+LOB 10% | 主客場(lob) 5%
    """
    if not p or not p.get("foreign"):
        return 0.0
    era   = p.get("era", 4.5)
    whip  = p.get("whip", 1.40)
    kbb   = p.get("k_bb_pct", 10.0)
    r5    = p.get("recent_5_era", era)
    babip = p.get("babip", 0.300)
    lob   = p.get("lob_pct", 72.0)

    era_s   = max(0, min(100, (5.0 - era)  / 4.0  * 100))
    whip_s  = max(0, min(100, (1.7 - whip) / 0.80 * 100))
    kbb_s   = max(0, min(100, kbb / 25.0   * 100))
    form_s  = max(0, min(100, (5.0 - r5)   / 4.0  * 100))
    babip_s = max(0, min(100, (0.340 - babip) / 0.08 * 100))
    lob_s   = max(0, min(100, (lob - 60)   / 30.0 * 100))

    return round(
        era_s   * 0.25 +
        whip_s  * 0.20 +
        kbb_s   * 0.20 +
        form_s  * 0.20 +
        babip_s * 0.10 +
        lob_s   * 0.05,
        1
    )


def _lineup_score(team: str) -> float:
    """打線強度 (0~100)。涵蓋 7 個指標 + 三段近況 OPS 趨勢。"""
    b = TEAM_STATS.get(team, {}).get("batting", {})
    if not b:
        return 50.0
    s = 50.0

    ops  = b.get("ops",      LEAGUE_AVG_OPS)
    woba = b.get("woba",     LEAGUE_AVG_WOBA)
    wrc  = b.get("wrc_plus", LEAGUE_AVG_WRC)
    rpg  = b.get("runs_per_game",  LEAGUE_AVG_RPG)
    hrpg = b.get("hr_per_game",    0.9)
    r7   = b.get("recent_7_ops",   ops)
    r14  = b.get("recent_14_ops",  ops)
    r30  = b.get("recent_30_ops",  ops)

    # 整季核心打擊指標
    s += (ops  - LEAGUE_AVG_OPS)  * 50.0
    s += (woba - LEAGUE_AVG_WOBA) * 40.0
    s += (wrc  - LEAGUE_AVG_WRC)  * 0.35
    # 得分製造能力
    s += (rpg  - LEAGUE_AVG_RPG) * 4.0
    s += (hrpg - 0.9) * 5.0
    # 近況趨勢（7天最新，30天最平滑）
    recent_ops = r7 * 0.50 + r14 * 0.30 + r30 * 0.20
    s += (recent_ops - ops) * 30.0

    return max(10.0, min(90.0, s))


def _lineup_detail(ht: str, at: str) -> str:
    bh = TEAM_STATS.get(ht, {}).get("batting", {})
    ba = TEAM_STATS.get(at, {}).get("batting", {})
    return (
        f"主隊 OPS {bh.get('ops','-')} wOBA {bh.get('woba','-')} "
        f"wRC+ {bh.get('wrc_plus','-')} 近7OPS {bh.get('recent_7_ops','-')} "
        f"| 客隊 OPS {ba.get('ops','-')} wOBA {ba.get('woba','-')} "
        f"wRC+ {ba.get('wrc_plus','-')} 近7OPS {ba.get('recent_7_ops','-')}"
    )


def _bullpen_score(team: str) -> float:
    """牛棚戰力 (0~100)。涵蓋 ERA/FIP/WHIP + 疲勞三重指標。"""
    bp = TEAM_STATS.get(team, {}).get("bullpen", {})
    if not bp:
        return 50.0
    s = 50.0

    era      = bp.get("era",      LEAGUE_AVG_ERA)
    fip      = bp.get("fip",      LEAGUE_AVG_ERA)
    whip     = bp.get("whip",     1.30)
    save_pct = bp.get("save_pct", 65.0)
    hold_pct = bp.get("hold_pct", 60.0)
    fatigue  = bp.get("fatigue_score", 40)
    consec   = bp.get("closer_consecutive_days", 0)
    l7g      = bp.get("last7_games",   12)
    l7p      = bp.get("last7_pitches", 360)

    # 品質指標
    s += (LEAGUE_AVG_ERA - era)  * 7.0
    s += (LEAGUE_AVG_ERA - fip)  * 4.0
    s += (1.30 - whip) * 12.0
    # 關鍵局效率
    s += (save_pct - 65.0) * 0.25
    s += (hold_pct - 60.0) * 0.20
    # 疲勞指數（0=新鮮，100=力竭）
    s -= max(0, fatigue - 30) * 0.28
    # 終結者連續出賽懲罰
    if consec >= 3:
        s -= 14
    elif consec == 2:
        s -= 8
    elif consec == 1:
        s -= 3
    # 近7天用球量懲罰
    if l7p > 420:
        s -= (l7p - 420) * 0.05
    if l7g > 15:
        s -= (l7g - 15) * 1.2

    return max(10.0, min(90.0, s))


def _bullpen_detail(ht: str, at: str) -> str:
    bh = TEAM_STATS.get(ht, {}).get("bullpen", {})
    ba = TEAM_STATS.get(at, {}).get("bullpen", {})
    return (
        f"主隊牛棚 ERA {bh.get('era','-')} WHIP {bh.get('whip','-')} "
        f"疲勞 {bh.get('fatigue_score','-')} 終結者連出 {bh.get('closer_consecutive_days',0)}天 "
        f"| 客隊牛棚 ERA {ba.get('era','-')} WHIP {ba.get('whip','-')} "
        f"疲勞 {ba.get('fatigue_score','-')} 終結者連出 {ba.get('closer_consecutive_days',0)}天"
    )


def _home_away_score(ht: str, at: str, venue: str) -> float:
    """主場優勢 + 球場環境，回傳 -25~+25（正值 = 主隊佔優）。"""
    h_rec = TEAM_STATS.get(ht, {}).get("record", {})
    a_rec = TEAM_STATS.get(at, {}).get("record", {})

    hw, hl = h_rec.get("home_w", 0), h_rec.get("home_l", 1)
    aw, al = a_rec.get("away_w", 0), a_rec.get("away_l", 1)
    home_rate = hw / (hw + hl) if (hw + hl) > 0 else 0.5
    away_rate = aw / (aw + al) if (aw + al) > 0 else 0.5

    # 主場勝率 vs 客場勝率的差值
    adv  = (home_rate - 0.5) * 20.0
    adv -= (away_rate - 0.5) * 15.0
    # CPBL 主場固有優勢（約+5%勝率）
    adv += 5.0

    # 球場環境：得分友好的球場對打擊較好隊有利
    vf    = VENUE_FACTORS.get(venue, {}).get("run_factor", 1.0)
    bat_h = TEAM_STATS.get(ht, {}).get("batting", {}).get("ops", LEAGUE_AVG_OPS)
    bat_a = TEAM_STATS.get(at, {}).get("batting", {}).get("ops", LEAGUE_AVG_OPS)
    adv  += (vf - 1.0) * (bat_h - bat_a) * 50.0

    return max(-25.0, min(25.0, adv))


def _ha_detail(ht: str, at: str, venue: str) -> str:
    hr = TEAM_STATS.get(ht, {}).get("record", {})
    ar = TEAM_STATS.get(at, {}).get("record", {})
    vf = VENUE_FACTORS.get(venue, {})
    return (
        f"主隊主場 {hr.get('home_w',0)}勝{hr.get('home_l',0)}敗 "
        f"| 客隊客場 {ar.get('away_w',0)}勝{ar.get('away_l',0)}敗 "
        f"| {venue} run_factor={vf.get('run_factor',1.0)} {vf.get('note','')}"
    )


def _recent_form_score(team: str) -> float:
    """近期狀態 (0~100)。近5場最重，加入得失分差與出賽密度懲罰。"""
    rec  = TEAM_STATS.get(team, {}).get("record", {})
    if not rec:
        return 50.0
    s = 50.0

    last5    = rec.get("last5",  [])
    last10   = rec.get("last10", [])
    run_diff = rec.get("run_diff", 0)
    fatigue  = TEAM_STATS.get(team, {}).get("schedule_fatigue", 3)

    # 近5場勝率（最新動態，權重最高）
    if last5:
        s += (sum(last5) / len(last5) - 0.5) * 40.0
    # 近10場勝率（中期趨勢）
    if last10:
        s += (sum(last10) / len(last10) - 0.5) * 25.0
    # 得失分差（正 = 總體表現較強）
    s += min(15.0, max(-15.0, run_diff / 10.0))
    # 出賽密度疲勞懲罰（schedule_fatigue = 近7天比賽場數）
    if fatigue >= 6:
        s -= 8.0
    elif fatigue >= 5:
        s -= 4.0

    return max(10.0, min(90.0, s))


def _form_detail(ht: str, at: str) -> str:
    rh = TEAM_STATS.get(ht, {}).get("record", {})
    ra = TEAM_STATS.get(at, {}).get("record", {})
    fh = TEAM_STATS.get(ht, {}).get("schedule_fatigue", 3)
    fa = TEAM_STATS.get(at, {}).get("schedule_fatigue", 3)

    def fmt(ls): return "".join("●" if r else "○" for r in ls)
    return (
        f"主隊近5場 {fmt(rh.get('last5',[]))} 近10場 {fmt(rh.get('last10',[]))} "
        f"得失分差 {rh.get('run_diff',0):+d} 出賽密度 {fh}/7天 "
        f"| 客隊近5場 {fmt(ra.get('last5',[]))} 近10場 {fmt(ra.get('last10',[]))} "
        f"得失分差 {ra.get('run_diff',0):+d} 出賽密度 {fa}/7天"
    )


def _h2h_score(away_team: str, home_team: str) -> float:
    """本季對戰主隊優勢 (-15~+15)。"""
    record = H2H.get(away_team, {}).get(home_team, [5, 5])
    away_w, home_w = record[0], record[1]
    total = away_w + home_w
    if total == 0:
        return 0.0
    home_rate = home_w / total
    return (home_rate - 0.5) * 30.0


def _h2h_detail(away_team: str, home_team: str) -> str:
    rec = H2H.get(away_team, {}).get(home_team, [5, 5])
    total = rec[0] + rec[1]
    h_pct = f"{rec[1]/total*100:.0f}%" if total > 0 else "N/A"
    return f"本季對戰：客隊 {rec[0]} 勝 主隊 {rec[1]} 勝（主隊勝率 {h_pct}）"


def _injury_tier(inj_str: str) -> str:
    """從傷兵描述字串估計嚴重等級 S/A/B。"""
    if "DL60" in inj_str or "IL60" in inj_str:
        return "S"
    critical_keywords = ("腿傷", "肩傷", "手肘", "手臂", "腰傷", "膝蓋", "韌帶")
    if "DL15" in inj_str or "IL15" in inj_str:
        return "S" if any(k in inj_str for k in critical_keywords) else "A"
    if "觀察中" in inj_str or "評估" in inj_str:
        return "B"
    return "A"


def _injury_score(team: str) -> float:
    """傷兵狀況 (0~100)。S 級 -15、A 級 -8、B 級 -3。"""
    injuries = TEAM_STATS.get(team, {}).get("injuries", [])
    if not injuries:
        return 50.0
    s = 50.0
    tier_penalty = {"S": 15, "A": 8, "B": 3}
    for inj in injuries:
        s -= tier_penalty[_injury_tier(inj)]
    return max(10.0, min(90.0, s))


def _injury_detail(ht: str, at: str) -> str:
    hi = TEAM_STATS.get(ht, {}).get("injuries", [])
    ai = TEAM_STATS.get(at, {}).get("injuries", [])

    def fmt_list(lst):
        if not lst:
            return "無傷兵"
        return "、".join(f"{inj}[{_injury_tier(inj)}]" for inj in lst)

    return f"主隊：{fmt_list(hi)} | 客隊：{fmt_list(ai)}"


def _weather_score(weather: dict | None, venue: str) -> float:
    """天氣對主隊的影響 (-15~+15)。正值 = 對主隊有利。"""
    if not weather:
        return 0.0
    temp     = weather.get("temp_c",  25)
    wind_kph = weather.get("wind_kph", 10)
    humidity = weather.get("humidity", 70)
    cond     = str(weather.get("condition", "")).lower()
    score    = 0.0

    # 氣溫：高溫有利打者（全壘打增加）
    if temp > 32:
        score += 4.0
    elif temp > 28:
        score += 2.0
    elif temp < 18:
        score -= 2.0

    # 強風：增加不確定性（輕微不利主隊，因客隊打者更少主場比賽適應）
    if wind_kph > 40:
        score -= 3.0
    elif wind_kph > 25:
        score -= 1.5

    # 濕度過高影響球速
    if humidity > 88:
        score -= 1.0

    # 降雨 / 惡劣天候
    if any(w in cond for w in ("rain", "storm", "shower", "雨", "暴風")):
        score -= 4.0

    # 球場特性疊加：海風 / 夜場風對特定球場的影響
    vf = VENUE_FACTORS.get(venue, {})
    rf = vf.get("run_factor", 1.0)
    # 大球場（run_factor < 1）在強風下更有利主場投手
    if wind_kph > 25 and rf < 0.98:
        score += 1.5

    return max(-15.0, min(15.0, score))


def _weather_detail(weather: dict | None) -> str:
    if not weather:
        return "天氣資料無法取得"
    return (
        f"{weather.get('condition','未知')} "
        f"氣溫 {weather.get('temp_c','-')}°C "
        f"風速 {weather.get('wind_kph','-')} km/h "
        f"濕度 {weather.get('humidity','-')}%"
    )


def _defense_score(team: str) -> float:
    """守備能力 (0~100)。守備率 + DRS + UZR + 失誤數。"""
    d = TEAM_STATS.get(team, {}).get("defense", {})
    if not d:
        return 50.0
    s = 50.0

    fpct   = d.get("fielding_pct", 0.980)
    drs    = d.get("drs",    0)
    uzr    = d.get("uzr",    0.0)
    errors = d.get("errors", 30)

    s += (fpct  - 0.980) * 800.0   # 守備率差 0.001 ≈ ±0.8分
    s += drs    * 0.8               # DRS 每救1分 ≈ +0.8分
    s += uzr    * 0.5               # UZR 輔助驗證
    s -= (errors - 30) * 0.4        # 失誤越多越差

    return max(10.0, min(90.0, s))


def _defense_detail(ht: str, at: str) -> str:
    dh = TEAM_STATS.get(ht, {}).get("defense", {})
    da = TEAM_STATS.get(at, {}).get("defense", {})
    return (
        f"主隊 守備率 {dh.get('fielding_pct','-')} DRS {dh.get('drs',0):+d} "
        f"UZR {dh.get('uzr',0.0):+.1f} 失誤 {dh.get('errors','-')} "
        f"| 客隊 守備率 {da.get('fielding_pct','-')} DRS {da.get('drs',0):+d} "
        f"UZR {da.get('uzr',0.0):+.1f} 失誤 {da.get('errors','-')}"
    )
