"""ELO 評分系統 — 追蹤球隊實力並輸出勝率預測"""
import math
from .mock_data import TEAM_STATS

K_FACTOR = 32
HOME_ADVANTAGE = 50   # ELO 主場加成
PITCHER_SCALE = 80    # 先發投手 ERA 換算 ELO 差值的最大調整量
LEAGUE_AVG_ERA = 3.80


class ELOSystem:
    def __init__(self):
        self.ratings: dict[str, float] = {
            code: float(s["elo"]) for code, s in TEAM_STATS.items()
        }

    # ── 查詢 ─────────────────────────────────────
    def get(self, team: str) -> float:
        return self.ratings.get(team, 1500.0)

    def win_probability(
        self,
        home_team: str,
        away_team: str,
        home_pitcher_era: float | None = None,
        away_pitcher_era: float | None = None,
    ) -> float:
        """
        回傳主隊勝率 (0.0 ~ 1.0)
        可選：加入先發投手 ERA 調整
        """
        home_elo = self.get(home_team) + HOME_ADVANTAGE
        away_elo = self.get(away_team)

        # 先發投手調整
        if home_pitcher_era is not None:
            home_elo += _pitcher_elo_adj(home_pitcher_era)
        if away_pitcher_era is not None:
            away_elo += _pitcher_elo_adj(away_pitcher_era)

        return _elo_prob(home_elo, away_elo)

    # ── 更新 ─────────────────────────────────────
    def update(self, winner: str, loser: str):
        """比賽結束後更新雙方 ELO"""
        exp_w = _elo_prob(self.get(winner), self.get(loser))
        exp_l = 1.0 - exp_w
        self.ratings[winner] = self.get(winner) + K_FACTOR * (1.0 - exp_w)
        self.ratings[loser]  = self.get(loser)  + K_FACTOR * (0.0 - exp_l)


def _elo_prob(elo_a: float, elo_b: float) -> float:
    return 1.0 / (1.0 + math.pow(10, (elo_b - elo_a) / 400.0))


def _pitcher_elo_adj(era: float) -> float:
    """ERA 比聯盟平均好/差 → 換算成 ELO 加減"""
    delta = LEAGUE_AVG_ERA - era   # 正 = 比平均好
    return max(-PITCHER_SCALE, min(PITCHER_SCALE, delta * 25))
