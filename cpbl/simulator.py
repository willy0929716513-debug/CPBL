"""V7 Monte Carlo 模擬器 — 為每場比賽運行 N 次模擬，輸出置信區間"""
import random
import math


# 各因子在單場比賽中的隨機波動（σ，以優勢分為單位）
_SIGMA = {
    "starter":     8.5,   # 投手表現最難預測
    "lineup":      4.0,
    "bullpen":     5.5,
    "home_away":   1.5,
    "recent_form": 4.0,
    "h2h":         3.0,
    "injuries":    2.0,
    "weather":     3.5,
    "defense":     1.5,
}

_WEIGHTS = {
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


def simulate(pred: dict, n: int = 2000) -> dict:
    """
    蒙地卡羅模擬。

    pred: predictor.predict() 的輸出
    n:    模擬次數（預設 2000，可在 debug 時改 200）

    Returns:
        mean_prob   : 模擬平均主隊勝率
        std_dev     : 標準差（越低 = 勝率越確定）
        ci_90       : 90% 置信區間 [low, high]
        home_win_pct: 模擬中主隊勝的比例
        uncertain   : bool，std > 0.12 時為高度不確定
        conf_boost  : 根據方差給的信心加成/扣減 (-0.05~+0.05)
    """
    elo_base = pred.get("elo_base", pred.get("home_win_prob", 0.5))
    factors  = pred.get("factors", {})

    base_advs = {}
    for key in _WEIGHTS:
        f = factors.get(key, {})
        base_advs[key] = f.get("advantage", 0.0) if isinstance(f, dict) else 0.0

    probs = []
    for _ in range(n):
        hp = elo_base
        for key, w in _WEIGHTS.items():
            noisy_adv = base_advs[key] + random.gauss(0, _SIGMA.get(key, 3.0))
            hp += (noisy_adv / 100.0) * w * 0.5
        hp = max(0.05, min(0.95, hp))
        probs.append(hp)

    probs.sort()
    mean_p = sum(probs) / n
    var    = sum((p - mean_p) ** 2 for p in probs) / n
    std    = math.sqrt(var)

    ci_low  = probs[int(n * 0.05)]
    ci_high = probs[int(n * 0.95)]
    home_wins = sum(1 for p in probs if p > 0.5)

    # 低方差 → 加信心；高方差 → 減信心
    # std 正常範圍約 0.08~0.18
    conf_boost = round(max(-0.05, min(0.05, (0.12 - std) * 0.4)), 4)

    return {
        "n":             n,
        "mean_prob":     round(mean_p, 4),
        "std_dev":       round(std, 4),
        "ci_90":         [round(ci_low, 4), round(ci_high, 4)],
        "home_win_pct":  round(home_wins / n, 4),
        "uncertain":     std > 0.13,
        "conf_boost":    conf_boost,
    }
