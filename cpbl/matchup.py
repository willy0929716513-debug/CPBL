"""V8 Opponent Matchup Matrix — 投打對決類型匹配分析"""
from __future__ import annotations
from .mock_data import PITCHERS, BATTERS

_LEAGUE_OPS = 0.730  # NPB/KBO blended average


def _pitcher_hand(name: str) -> str:
    return PITCHERS.get(name, {}).get("throws", "R")


def _pitcher_type(name: str) -> str:
    """
    依 K/9 與 BB/9 分類投手型態：
    power / finesse / groundball / flyball / balanced
    """
    p   = PITCHERS.get(name, {})
    k9  = p.get("k9",     7.5)
    bb9 = p.get("bb9",    3.2)
    kbb = p.get("k_bb_pct", k9 - bb9 * 0.8)

    if k9 >= 9.5 and bb9 <= 3.0:
        return "power"
    if k9 <= 6.5 and bb9 <= 2.8:
        return "finesse"
    if kbb < 8.0:
        return "wildness"   # 控球差，對打者有利
    # ERA context for ground/fly split
    era = p.get("era", 4.0)
    if era < 3.5 and k9 < 8.5:
        return "groundball"
    if k9 >= 8.0 and era > 4.2:
        return "flyball"
    return "balanced"


def _team_profile(team: str) -> dict:
    """聚合球隊打者 vs 左投/右投 OPS 及打擊型態。"""
    roster = [b for b in BATTERS.values() if b.get("team") == team]
    if not roster:
        return {
            "vs_lhp": _LEAGUE_OPS, "vs_rhp": _LEAGUE_OPS,
            "iso": 0.150, "barrel_pct": 8.0, "k_pct": 20.0,
        }
    n = len(roster)
    return {
        "vs_lhp":     sum(b.get("vs_lhp_ops", b.get("ops", _LEAGUE_OPS)) for b in roster) / n,
        "vs_rhp":     sum(b.get("vs_rhp_ops", b.get("ops", _LEAGUE_OPS)) for b in roster) / n,
        "iso":        sum(b.get("iso", 0.150) for b in roster) / n,
        "barrel_pct": sum(b.get("barrel_pct", 8.0) for b in roster) / n,
        "k_pct":      sum(b.get("k_pct", 20.0) for b in roster) / n,
        "bb_pct":     sum(b.get("bb_pct", 8.0) for b in roster) / n,
    }


def matchup_advantage(batting_team: str, pitcher_name: str) -> float:
    """
    打線 vs 投手匹配優勢 (-10 ~ +10)。
    正值 = 打線佔優；負值 = 投手佔優。
    """
    if not batting_team or not pitcher_name:
        return 0.0

    hand    = _pitcher_hand(pitcher_name)
    ptype   = _pitcher_type(pitcher_name)
    profile = _team_profile(batting_team)
    adv     = 0.0

    # ── 1. 慣用手對決 ────────────────────────────────────────────
    key    = "vs_lhp" if hand == "L" else "vs_rhp"
    ops    = profile[key]
    adv   += (ops - _LEAGUE_OPS) * 25.0   # 0.040 OPS ≈ +1.0分

    # ── 2. 投手型態 vs 打線偏好 ──────────────────────────────────
    iso         = profile["iso"]
    barrel      = profile["barrel_pct"]
    k_pct       = profile["k_pct"]
    power_index = iso / 0.300 * 0.5 + barrel / 20.0 * 0.5  # 0~1

    if ptype == "power":
        # 高三振投手壓制強打線；接觸型打者反而較能抵抗
        adv -= power_index * 4.0
        adv += (1 - power_index) * 1.5
    elif ptype == "finesse":
        # 控球投手被長打者敲爆；接觸型雙方平衡
        adv += power_index * 5.0
    elif ptype == "groundball":
        # 滾地球投手壓制長打；對速度型打線影響小
        adv -= power_index * 3.0
    elif ptype == "flyball":
        # 飛球型最怕全壘打打線
        adv += power_index * 6.0
    elif ptype == "wildness":
        # 控球差投手：給打者選球機會（有選球的隊伍得分）
        bb_bonus = (profile.get("bb_pct", 8.0) - 8.0) * 0.5
        adv += 2.0 + bb_bonus

    return max(-10.0, min(10.0, round(adv, 2)))


def matchup_detail(batting_team: str, pitcher_name: str) -> str:
    if not pitcher_name:
        return "投手未定 / 無法分析"
    hand  = _pitcher_hand(pitcher_name)
    ptype = _pitcher_type(pitcher_name)
    adv   = matchup_advantage(batting_team, pitcher_name)
    tag   = "打線佔優" if adv > 1 else ("投手佔優" if adv < -1 else "均勢")
    return f"{pitcher_name}({hand}/{ptype}) vs {batting_team}: {tag} {adv:+.1f}"


def game_matchup(away: str, home: str,
                 away_pitcher: str, home_pitcher: str) -> dict:
    """
    計算雙邊對決，回傳可供 predictor 使用的 advantage 值。
    正值 = 主隊打線佔優（相對客隊先發）；負值反之。
    """
    # 主隊打線 vs 客隊先發
    home_bat_adv = matchup_advantage(home, away_pitcher)
    # 客隊打線 vs 主隊先發
    away_bat_adv = matchup_advantage(away, home_pitcher)

    # 淨優勢：主隊打線多佔 - 客隊打線多佔
    net = home_bat_adv - away_bat_adv

    return {
        "label":          "投打匹配",
        "home_bat_adv":   round(home_bat_adv, 2),
        "away_bat_adv":   round(away_bat_adv, 2),
        "net_advantage":  round(net, 2),
        "home_pitcher_type": _pitcher_type(home_pitcher) if home_pitcher else "unknown",
        "away_pitcher_type": _pitcher_type(away_pitcher) if away_pitcher else "unknown",
        "detail": (
            f"主隊打線 vs 客隊先發: {matchup_detail(home, away_pitcher)} | "
            f"客隊打線 vs 主隊先發: {matchup_detail(away, home_pitcher)}"
        ),
    }
