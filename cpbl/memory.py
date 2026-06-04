"""V7 RL 記憶模組 — 自適應權重，根據歷史結果更新"""
import json, os, math

_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "memory.json")

DEFAULT: dict = {
    "version":        2,
    "pitcher_weight": 1.0,   # 先發投手因子乘數 (0.5~2.0)
    "market_weight":  1.0,   # 盤口因子乘數
    "lineup_weight":  1.0,   # 打線因子乘數
    "bullpen_weight": 1.0,   # 牛棚因子乘數
    "form_weight":    1.0,   # 近況因子乘數
    "bias":           0.0,   # 全局偏移，修正系統性高/低估 (-0.08~+0.08)
    "total_games":    0,
    "correct":        0,
    "roi_units":      0.0,   # 累積損益 (Kelly 單位)
    "streak_correct": 0,
    "streak_wrong":   0,
    "calibration": {         # 信心分桶校準 {bucket: [正確, 總場數]}
        "50": [0, 0], "55": [0, 0], "60": [0, 0],
        "65": [0, 0], "70": [0, 0], "75": [0, 0], "80": [0, 0],
    },
    "factor_accuracy": {     # 各因子方向預測準確率 [正確, 總場數]
        "pitcher": [0, 0],
        "lineup":  [0, 0],
        "bullpen": [0, 0],
        "market":  [0, 0],
        "form":    [0, 0],
    },
}


def load() -> dict:
    path = os.path.abspath(_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            mem = json.load(f)
        for k, v in DEFAULT.items():
            mem.setdefault(k, v)
        # 確保 calibration / factor_accuracy 子鍵完整
        for k, v in DEFAULT["calibration"].items():
            mem["calibration"].setdefault(k, v)
        for k, v in DEFAULT["factor_accuracy"].items():
            mem["factor_accuracy"].setdefault(k, v)
        return mem
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT)


def save(mem: dict):
    path = os.path.abspath(_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)


def update(mem: dict, actual_home_win: bool, predicted_home_win: bool,
           conf: float, factors: dict, edge: float = 0.0) -> dict:
    """
    一場比賽結束後更新記憶。

    actual_home_win:    實際主隊是否勝
    predicted_home_win: 模型預測主隊勝
    conf:               模型置信度 (0.0~1.0)
    factors:            predictor 輸出的 factors dict
    edge:               下注邊際（用於 ROI 估算）
    """
    LR = 0.05   # learning rate

    correct = predicted_home_win == actual_home_win
    mem["total_games"] = mem.get("total_games", 0) + 1
    if correct:
        mem["correct"] = mem.get("correct", 0) + 1
        mem["streak_correct"] = mem.get("streak_correct", 0) + 1
        mem["streak_wrong"] = 0
        mem["roi_units"] = round(mem.get("roi_units", 0) + edge, 4)
    else:
        mem["streak_wrong"] = mem.get("streak_wrong", 0) + 1
        mem["streak_correct"] = 0
        mem["roi_units"] = round(mem.get("roi_units", 0) - 1.0, 4)

    # ── 置信度校準 ──────────────────────────────
    bucket = str(int(min(80, max(50, conf * 100 // 5 * 5))))
    cal = mem.get("calibration", {})
    b = cal.get(bucket, [0, 0])
    b[1] += 1
    if correct:
        b[0] += 1
    cal[bucket] = b
    mem["calibration"] = cal

    # ── 各因子方向準確率 ────────────────────────
    fa = mem.get("factor_accuracy", {})

    def _factor_adv(key: str) -> float:
        f = factors.get(key, {})
        return f.get("advantage", 0.0) if isinstance(f, dict) else 0.0

    adv_map = {
        "pitcher": _factor_adv("starter"),
        "lineup":  _factor_adv("lineup"),
        "bullpen": _factor_adv("bullpen"),
        "market":  _factor_adv("odds"),
        "form":    _factor_adv("recent_form"),
    }
    for fa_key, adv in adv_map.items():
        if abs(adv) >= 3 and fa_key in fa:
            entry = fa[fa_key]
            entry[1] += 1
            if (adv > 0) == actual_home_win:
                entry[0] += 1
            fa[fa_key] = entry
    mem["factor_accuracy"] = fa

    # ── 自適應權重更新 ───────────────────────────
    # 若模型預測錯誤，找哪個因子方向是對的 → 增加其權重
    actual_dir = 1 if actual_home_win else -1

    def _adjust(weight_key: str, adv: float, boost: float = LR):
        if adv * actual_dir > 5:
            mem[weight_key] = round(min(2.0, mem.get(weight_key, 1.0) + boost), 4)
        elif adv * actual_dir < -5 and not correct:
            # 方向也錯了 → 微降
            mem[weight_key] = round(max(0.5, mem.get(weight_key, 1.0) - boost * 0.3), 4)

    if not correct:
        _adjust("pitcher_weight", adv_map["pitcher"])
        _adjust("market_weight",  adv_map["market"])
        _adjust("lineup_weight",  adv_map["lineup"])
        _adjust("bullpen_weight", adv_map["bullpen"])
        _adjust("form_weight",    adv_map["form"])

    # ── 全局偏誤校正（需足夠樣本才調整）──────────
    total = mem["total_games"]
    if total >= 20:
        acc = mem["correct"] / total
        if acc < 0.48:
            # 系統性低估，調低 bias（讓模型更保守）
            mem["bias"] = round(max(-0.08, mem.get("bias", 0.0) - LR * 0.3), 4)
        elif acc > 0.62:
            # 準確率異常高，可能過擬合，輕微回調
            mem["bias"] = round(min(0.08, mem.get("bias", 0.0) + LR * 0.1), 4)

    return mem


def accuracy(mem: dict) -> float:
    total = mem.get("total_games", 0)
    return mem["correct"] / total if total > 0 else 0.0


def calibration_str(mem: dict) -> str:
    cal = mem.get("calibration", {})
    parts = []
    for bucket in sorted(cal.keys(), key=int):
        right, total = cal[bucket]
        if total >= 3:
            parts.append(f"{bucket}%→{right/total*100:.0f}%({total})")
    return "  ".join(parts) if parts else "無資料"


def weight_str(mem: dict) -> str:
    return (
        f"投手×{mem.get('pitcher_weight',1):.2f} "
        f"打線×{mem.get('lineup_weight',1):.2f} "
        f"牛棚×{mem.get('bullpen_weight',1):.2f} "
        f"市場×{mem.get('market_weight',1):.2f} "
        f"近況×{mem.get('form_weight',1):.2f} "
        f"偏移{mem.get('bias',0):+.3f}"
    )
