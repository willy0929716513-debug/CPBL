"""NPB/KBO Monte Carlo 模擬器 — Poisson 得分模型 + 期望得分不確定性"""
import random
import math

_RUN_STD_DEFAULT = 3.0   # 得分差標準差（NormalCDF 用）


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _poisson(lam: float) -> int:
    """Knuth Poisson random variate."""
    L = math.exp(-min(lam, 30))
    k, p = 0, 1.0
    while p > L:
        p *= random.random()
        k += 1
    return k - 1


def simulate(pred: dict, n: int = 5000) -> dict:
    """
    Poisson Monte Carlo 模擬。

    若 pred 包含 home_exp_runs / away_exp_runs → 使用 Poisson 直接模擬。
    否則退回原有因子加雜訊方式。

    Returns:
        mean_prob   : MC 主隊平均勝率（含22-76%封頂）
        std_dev     : 跨模擬標準差
        ci_90       : 90% 信賴區間
        home_win_pct: MC中主隊勝比例
        norm_cdf_prob: NormalCDF(期望得分差 / _RUN_STD)
        uncertain   : std > 0.13
        conf_boost  : 根據方差給的信心加成
    """
    home_lam = pred.get("home_exp_runs")
    away_lam = pred.get("away_exp_runs")

    if home_lam is not None and away_lam is not None:
        return _simulate_poisson(pred, home_lam, away_lam, n)
    return _simulate_factor_based(pred, n)


def _simulate_poisson(pred: dict, home_lam: float, away_lam: float, n: int) -> dict:
    home_lam = max(0.5, min(14.0, home_lam))
    away_lam = max(0.5, min(14.0, away_lam))

    home_wins = 0
    probs = []
    for _ in range(n):
        # 投手 ERA 不確定性：±10% 高斯噪音
        h = _poisson(max(0.3, home_lam * random.gauss(1.0, 0.10)))
        a = _poisson(max(0.3, away_lam * random.gauss(1.0, 0.10)))
        if h > a:
            home_wins += 1
            probs.append(1.0)
        elif h < a:
            probs.append(0.0)
        else:
            home_wins += 0.5  # 延長賽 50/50
            probs.append(0.5)

    mc_raw = home_wins / n
    # 封頂 22-76%（防小樣本過度自信）
    mc_prob = max(0.22, min(0.76, mc_raw))

    probs.sort()
    var = sum((p - mc_raw) ** 2 for p in probs) / n
    std = math.sqrt(var)

    # NormalCDF 部分
    exp_diff = pred.get("exp_run_diff", home_lam - away_lam)
    norm_p   = _norm_cdf(exp_diff / _RUN_STD_DEFAULT)
    norm_p   = max(0.22, min(0.76, norm_p))

    conf_boost = round(max(-0.05, min(0.05, (0.12 - std) * 0.4)), 4)

    return {
        "n":             n,
        "mean_prob":     round(mc_prob, 4),
        "std_dev":       round(std, 4),
        "ci_90":         [round(probs[int(n * 0.05)], 4),
                          round(probs[int(n * 0.95)], 4)],
        "home_win_pct":  round(home_wins / n, 4),
        "norm_cdf_prob": round(norm_p, 4),
        "uncertain":     std > 0.13,
        "conf_boost":    conf_boost,
        "home_exp_runs": round(home_lam, 2),
        "away_exp_runs": round(away_lam, 2),
    }


# ── 退回：原有因子加雜訊方式（無期望得分時使用）────────────────────────

_SIGMA = {
    "starter": 8.5, "lineup": 4.0, "bullpen": 5.5,
    "home_away": 1.5, "recent_form": 4.0, "h2h": 3.0,
    "injuries": 2.0, "weather": 3.5, "defense": 1.5,
}
_WEIGHTS = {
    "starter": 0.35, "lineup": 0.20, "bullpen": 0.15,
    "home_away": 0.08, "recent_form": 0.08, "h2h": 0.05,
    "injuries": 0.04, "weather": 0.03, "defense": 0.02,
}


def _simulate_factor_based(pred: dict, n: int) -> dict:
    elo_base = pred.get("elo_base", pred.get("home_win_prob", 0.5))
    factors  = pred.get("factors", {})
    base_advs = {
        k: (factors.get(k) or {}).get("advantage", 0.0)
        for k in _WEIGHTS
    }
    probs = []
    for _ in range(n):
        hp = elo_base
        for key, w in _WEIGHTS.items():
            hp += (base_advs[key] + random.gauss(0, _SIGMA.get(key, 3.0))) / 100.0 * w * 0.5
        probs.append(max(0.05, min(0.95, hp)))

    probs.sort()
    mean_p = sum(probs) / n
    mc_prob = max(0.22, min(0.76, mean_p))
    var  = sum((p - mean_p) ** 2 for p in probs) / n
    std  = math.sqrt(var)
    conf_boost = round(max(-0.05, min(0.05, (0.12 - std) * 0.4)), 4)

    exp_diff = pred.get("exp_run_diff", 0.0)
    norm_p   = _norm_cdf(exp_diff / _RUN_STD_DEFAULT)
    norm_p   = max(0.22, min(0.76, norm_p))

    return {
        "n":             n,
        "mean_prob":     round(mc_prob, 4),
        "std_dev":       round(std, 4),
        "ci_90":         [round(probs[int(n * 0.05)], 4), round(probs[int(n * 0.95)], 4)],
        "home_win_pct":  round(sum(1 for p in probs if p > 0.5) / n, 4),
        "norm_cdf_prob": round(norm_p, 4),
        "uncertain":     std > 0.13,
        "conf_boost":    conf_boost,
    }
