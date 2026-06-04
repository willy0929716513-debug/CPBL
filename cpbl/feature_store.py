"""V8 Feature Store — 長期特徵記憶，跨場次持久化（疲勞/休息/主場因子）"""
import json, os, datetime

_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "feature_history.json")

_TEAM_DEFAULTS = {
    "bullpen_ip_3d":    0.0,   # 牛棚近3天投球局數（疲勞核心指標）
    "bullpen_ip_1d":    0.0,   # 今日牛棚投球局數
    "rest_days":        1,     # 距上場天數
    "travel_fatigue":   0,     # 0=主場/近距離, 1=一般客場, 2=長途客場
    "consecutive_away": 0,     # 連續客場場次
    "home_run_factor":  1.00,  # 本球隊在主球場的 HR factor（從 VENUE_FACTORS 繼承）
    "vs_lhp_ops_30d":   0.760, # 近30天 vs 左投 OPS（滾動更新）
    "vs_rhp_ops_30d":   0.760, # 近30天 vs 右投 OPS
    "run_support_5g":   4.8,   # 近5場平均得分
    "wins_l10":         5,     # 近10場勝場數
    "last_game_date":   "",    # 上場日期 (YYYY-MM-DD)
}


def load() -> dict:
    try:
        with open(os.path.abspath(_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"teams": {}, "updated_at": ""}


def save(store: dict):
    path = os.path.abspath(_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    store["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def get_team(store: dict, team: str) -> dict:
    teams = store.setdefault("teams", {})
    if team not in teams:
        teams[team] = dict(_TEAM_DEFAULTS)
    else:
        for k, v in _TEAM_DEFAULTS.items():
            teams[team].setdefault(k, v)
    return teams[team]


def update_after_game(store: dict, team: str, date_str: str,
                      bullpen_ip: float = 0.0,
                      won: bool | None = None,
                      is_away: bool = False):
    """一場比賽結束後更新 Feature Store。"""
    tf = get_team(store, team)

    # 計算休息天數
    last = tf.get("last_game_date", "")
    if last:
        try:
            d0 = datetime.date.fromisoformat(last)
            d1 = datetime.date.fromisoformat(date_str)
            tf["rest_days"] = max(0, (d1 - d0).days)
        except ValueError:
            tf["rest_days"] = 1
    tf["last_game_date"] = date_str

    # 牛棚疲勞（指數平滑衰減，半衰期約2天）
    prev_3d = tf.get("bullpen_ip_3d", 0.0)
    tf["bullpen_ip_3d"] = round(prev_3d * 0.55 + bullpen_ip, 2)
    tf["bullpen_ip_1d"] = round(bullpen_ip, 2)

    # 客場連續累計
    if is_away:
        tf["consecutive_away"] = tf.get("consecutive_away", 0) + 1
        tf["travel_fatigue"]   = min(2, 1 + tf["consecutive_away"] // 3)
    else:
        tf["consecutive_away"] = 0
        tf["travel_fatigue"]   = 0

    # 近10場勝場滾動
    w10 = tf.get("wins_l10", 5)
    if won is not None:
        tf["wins_l10"] = max(0, min(10, w10 + (1 if won else 0) - 0))  # 簡化版
    store["teams"][team] = tf


def fatigue_penalty(store: dict, team: str) -> float:
    """
    綜合疲勞懲罰分數 (-10 ~ +3)。
    負值 = 對該隊不利。供 predictor 疊加使用。
    """
    tf = get_team(store, team)
    penalty = 0.0

    # 牛棚3天投球局數疲勞
    ip_3d = tf.get("bullpen_ip_3d", 0.0)
    if ip_3d > 12:
        penalty -= (ip_3d - 12) * 0.45
    elif ip_3d > 8:
        penalty -= (ip_3d - 8) * 0.25

    # 休息天數（超過1天有恢復加成）
    rest = tf.get("rest_days", 1)
    if rest >= 3:
        penalty += 2.5
    elif rest == 2:
        penalty += 1.5
    elif rest == 0:
        penalty -= 4.0   # back-to-back

    # 客場連續疲勞
    penalty -= tf.get("travel_fatigue", 0) * 1.5
    penalty -= min(3.0, tf.get("consecutive_away", 0) * 0.5)

    return max(-10.0, min(3.0, round(penalty, 2)))


def vs_pitcher_hand_bonus(store: dict, team: str, pitcher_throws: str) -> float:
    """
    根據 Feature Store 中近30天對左/右投 OPS 給打線補正 (-3 ~ +3)。
    """
    tf  = get_team(store, team)
    key = "vs_lhp_ops_30d" if pitcher_throws == "L" else "vs_rhp_ops_30d"
    ops = tf.get(key, 0.760)
    return max(-3.0, min(3.0, (ops - 0.760) * 30.0))
