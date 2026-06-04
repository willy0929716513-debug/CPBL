"""
CPBL 2026 賽季 Mock 資料 — 離線 Demo / Scraping 備用
"""
from datetime import date

# ──────────────────────────────────────────────
# 球隊基本資訊
# ──────────────────────────────────────────────
TEAM_INFO = {
    "AEL": {"name": "中信兄弟",      "short": "兄弟", "stadium": "洲際棒球場",  "city": "台中", "color": "#002B5B"},
    "CT":  {"name": "統一7-ELEVEn獅","short": "統一", "stadium": "台南棒球場",  "city": "台南", "color": "#C8102E"},
    "FG":  {"name": "富邦悍將",      "short": "富邦", "stadium": "新莊棒球場",  "city": "新北", "color": "#003087"},
    "WL":  {"name": "樂天桃猿",      "short": "樂天", "stadium": "桃園棒球場",  "city": "桃園", "color": "#E4002B"},
    "TSG": {"name": "台鋼雄鷹",      "short": "台鋼", "stadium": "澄清湖棒球場","city": "高雄", "color": "#1B4B8A"},
    "WC":  {"name": "味全龍",        "short": "龍",   "stadium": "天母棒球場",  "city": "台北", "color": "#E31937"},
}

# ──────────────────────────────────────────────
# 球場環境因子  (run_factor > 1.0 = 打者天堂)
# ──────────────────────────────────────────────
VENUE_FACTORS = {
    "洲際棒球場":  {"run_factor": 0.92, "hr_factor": 0.88, "note": "投手有利，外野大"},
    "台南棒球場":  {"run_factor": 1.08, "hr_factor": 1.12, "note": "打者有利，海風助攻"},
    "新莊棒球場":  {"run_factor": 1.00, "hr_factor": 0.98, "note": "中性球場"},
    "桃園棒球場":  {"run_factor": 1.05, "hr_factor": 1.15, "note": "夜場風勢大，全壘打多"},
    "澄清湖棒球場":{"run_factor": 0.95, "hr_factor": 0.90, "note": "投手有利，球場大"},
    "天母棒球場":  {"run_factor": 1.02, "hr_factor": 1.05, "note": "風場多變"},
    "台北大巨蛋":  {"run_factor": 0.94, "hr_factor": 0.91, "note": "室內球場，環控氣候"},
}

# ──────────────────────────────────────────────
# 先發投手完整數據
# ──────────────────────────────────────────────
PITCHERS = {
    # ── 中信兄弟 ──────────────────────────────
    "陳柏清": {
        "team": "AEL", "foreign": False,
        "era": 3.12, "whip": 1.21, "fip": 3.28, "xfip": 3.35,
        "k9": 8.4, "bb9": 2.8, "h9": 7.9, "hr9": 0.8,
        "babip": 0.295, "lob_pct": 74.2, "k_bb_pct": 15.8,
        "recent_3_era": 2.10, "recent_5_era": 2.45, "recent_10_era": 2.98,
        "gs": 14, "innings": 86.2, "wpa": 1.8, "re24": 12.4,
    },
    "吳哲源": {
        "team": "AEL", "foreign": False,
        "era": 3.42, "whip": 1.28, "fip": 3.55, "xfip": 3.60,
        "k9": 7.8, "bb9": 3.0, "h9": 8.5, "hr9": 0.9,
        "babip": 0.298, "lob_pct": 72.8, "k_bb_pct": 14.0,
        "recent_3_era": 3.10, "recent_5_era": 3.28, "recent_10_era": 3.38,
        "gs": 13, "innings": 76.0, "wpa": 0.8, "re24": 5.5,
    },
    "張進德": {
        "team": "AEL", "foreign": False,
        "era": 4.05, "whip": 1.40, "fip": 4.18, "xfip": 4.12,
        "k9": 7.0, "bb9": 3.5, "h9": 9.3, "hr9": 1.0,
        "babip": 0.315, "lob_pct": 70.2, "k_bb_pct": 10.8,
        "recent_3_era": 3.80, "recent_5_era": 3.95, "recent_10_era": 4.00,
        "gs": 12, "innings": 68.2, "wpa": -0.1, "re24": -0.5,
    },
    "德保拉": {"team":"AEL","foreign":True,"era":2.18,"whip":0.98,"fip":2.32,"xfip":2.45,"k9":9.2,"bb9":2.0,"h9":6.8,"hr9":0.5,"babip":0.272,"lob_pct":80.2,"k_bb_pct":21.5,"recent_3_era":1.95,"recent_5_era":2.08,"recent_10_era":2.20,"gs":15,"innings":95.1,"wpa":3.8,"re24":26.4},
    "克迪":   {"team":"AEL","foreign":True,"era":3.24,"whip":1.22,"fip":3.38,"xfip":3.45,"k9":8.1,"bb9":2.8,"h9":8.3,"hr9":0.8,"babip":0.295,"lob_pct":74.0,"k_bb_pct":15.2,"recent_3_era":2.85,"recent_5_era":3.10,"recent_10_era":3.20,"gs":14,"innings":83.2,"wpa":1.4,"re24":9.6},
    "羅戈":   {"team":"AEL","foreign":True,"era":3.88,"whip":1.38,"fip":4.02,"xfip":3.95,"k9":7.2,"bb9":3.4,"h9":9.2,"hr9":1.0,"babip":0.312,"lob_pct":70.5,"k_bb_pct":11.5,"recent_3_era":4.20,"recent_5_era":4.05,"recent_10_era":3.92,"gs":13,"innings":76.0,"wpa":0.2,"re24":1.8},
    "黃博多": {"team":"AEL","foreign":True,"era":4.12,"whip":1.42,"fip":4.28,"xfip":4.18,"k9":6.8,"bb9":3.6,"h9":9.5,"hr9":1.1,"babip":0.318,"lob_pct":69.2,"k_bb_pct":9.8,"recent_3_era":3.90,"recent_5_era":4.00,"recent_10_era":4.10,"gs":12,"innings":69.1,"wpa":-0.3,"re24":-2.5},
    "菲力士": {"team":"AEL","foreign":True,"era":3.52,"whip":1.28,"fip":3.65,"xfip":3.72,"k9":8.5,"bb9":3.0,"h9":8.5,"hr9":0.9,"babip":0.300,"lob_pct":72.8,"k_bb_pct":16.2,"recent_3_era":3.20,"recent_5_era":3.38,"recent_10_era":3.48,"gs":13,"innings":79.2,"wpa":0.8,"re24":5.5},
    "胡智為": {
        "team": "AEL", "foreign": False,
        "era": 4.89, "whip": 1.48, "fip": 4.72, "xfip": 4.58,
        "k9": 6.2, "bb9": 3.5, "h9": 9.8, "hr9": 1.2,
        "babip": 0.315, "lob_pct": 68.1, "k_bb_pct": 8.5,
        "recent_3_era": 6.20, "recent_5_era": 5.40, "recent_10_era": 5.12,
        "gs": 13, "innings": 74.1, "wpa": -1.2, "re24": -8.5,
    },
    # ── 統一7-ELEVEn獅 ─────────────────────────
    "陳冠宇": {
        "team": "CT", "foreign": False,
        "era": 3.67, "whip": 1.32, "fip": 3.81, "xfip": 3.75,
        "k9": 7.8, "bb9": 3.1, "h9": 8.6, "hr9": 0.9,
        "babip": 0.308, "lob_pct": 72.0, "k_bb_pct": 13.2,
        "recent_3_era": 2.80, "recent_5_era": 3.10, "recent_10_era": 3.55,
        "gs": 14, "innings": 83.2, "wpa": 0.9, "re24": 5.2,
    },
    "布雷克": {"team":"CT","foreign":True,"era":2.78,"whip":1.08,"fip":2.92,"xfip":3.05,"k9":9.0,"bb9":2.2,"h9":7.4,"hr9":0.6,"babip":0.280,"lob_pct":77.5,"k_bb_pct":19.8,"recent_3_era":2.50,"recent_5_era":2.65,"recent_10_era":2.75,"gs":15,"innings":91.2,"wpa":2.8,"re24":19.5},
    "飛力獅": {"team":"CT","foreign":True,"era":3.42,"whip":1.25,"fip":3.55,"xfip":3.62,"k9":8.2,"bb9":3.0,"h9":8.6,"hr9":0.9,"babip":0.298,"lob_pct":73.2,"k_bb_pct":14.8,"recent_3_era":3.10,"recent_5_era":3.28,"recent_10_era":3.38,"gs":14,"innings":84.0,"wpa":1.0,"re24":7.2},
    "梅賽斯": {"team":"CT","foreign":True,"era":3.65,"whip":1.32,"fip":3.78,"xfip":3.82,"k9":7.8,"bb9":3.2,"h9":8.9,"hr9":1.0,"babip":0.308,"lob_pct":71.8,"k_bb_pct":12.8,"recent_3_era":3.40,"recent_5_era":3.55,"recent_10_era":3.62,"gs":13,"innings":78.1,"wpa":0.5,"re24":3.8},
    "雷伊":   {"team":"CT","foreign":True,"era":4.05,"whip":1.40,"fip":4.18,"xfip":4.12,"k9":7.0,"bb9":3.5,"h9":9.3,"hr9":1.1,"babip":0.315,"lob_pct":70.0,"k_bb_pct":10.5,"recent_3_era":3.80,"recent_5_era":3.95,"recent_10_era":4.02,"gs":12,"innings":71.0,"wpa":-0.1,"re24":-0.8},
    "林其緯": {
        "team": "CT", "foreign": False,
        "era": 4.21, "whip": 1.38, "fip": 4.35, "xfip": 4.28,
        "k9": 7.1, "bb9": 3.8, "h9": 9.1, "hr9": 1.0,
        "babip": 0.320, "lob_pct": 70.5, "k_bb_pct": 10.6,
        "recent_3_era": 3.80, "recent_5_era": 3.95, "recent_10_era": 4.10,
        "gs": 12, "innings": 70.2, "wpa": -0.4, "re24": -2.1,
    },
    "潘威倫": {
        "team": "CT", "foreign": False,
        "era": 3.78, "whip": 1.33, "fip": 3.90, "xfip": 3.85,
        "k9": 7.2, "bb9": 2.8, "h9": 9.0, "hr9": 0.9,
        "babip": 0.308, "lob_pct": 72.5, "k_bb_pct": 13.5,
        "recent_3_era": 3.50, "recent_5_era": 3.65, "recent_10_era": 3.72,
        "gs": 14, "innings": 85.2, "wpa": 0.4, "re24": 2.8,
    },
    "廖俊儒": {
        "team": "CT", "foreign": False,
        "era": 4.38, "whip": 1.43, "fip": 4.52, "xfip": 4.45,
        "k9": 6.8, "bb9": 3.8, "h9": 9.4, "hr9": 1.1,
        "babip": 0.322, "lob_pct": 69.5, "k_bb_pct": 9.5,
        "recent_3_era": 4.20, "recent_5_era": 4.30, "recent_10_era": 4.35,
        "gs": 11, "innings": 62.0, "wpa": -0.5, "re24": -3.5,
    },
    # ── 富邦悍將 ──────────────────────────────
    "李東洛": {
        "team": "FG", "foreign": False,
        "era": 1.83, "whip": 0.96, "fip": 2.05, "xfip": 2.18,
        "k9": 8.8, "bb9": 2.1, "h9": 6.9, "hr9": 0.4,
        "babip": 0.270, "lob_pct": 81.5, "k_bb_pct": 21.2,
        "recent_3_era": 1.50, "recent_5_era": 1.72, "recent_10_era": 1.80,
        "gs": 13, "innings": 83.2, "wpa": 3.5, "re24": 24.8,
    },
    "鄭錫謙": {
        "team": "FG", "foreign": False,
        "era": 3.34, "whip": 1.24, "fip": 3.45, "xfip": 3.50,
        "k9": 8.1, "bb9": 2.9, "h9": 8.2, "hr9": 0.8,
        "babip": 0.298, "lob_pct": 73.8, "k_bb_pct": 14.5,
        "recent_3_era": 2.10, "recent_5_era": 2.65, "recent_10_era": 3.10,
        "gs": 14, "innings": 86.0, "wpa": 1.5, "re24": 10.2,
    },
    "富藍戈": {"team":"FG","foreign":True,"era":2.95,"whip":1.14,"fip":3.08,"xfip":3.18,"k9":8.7,"bb9":2.5,"h9":7.7,"hr9":0.7,"babip":0.288,"lob_pct":76.2,"k_bb_pct":17.8,"recent_3_era":2.68,"recent_5_era":2.82,"recent_10_era":2.92,"gs":15,"innings":88.2,"wpa":2.2,"re24":15.5},
    "威爾森": {"team":"FG","foreign":True,"era":3.42,"whip":1.26,"fip":3.55,"xfip":3.62,"k9":8.0,"bb9":2.9,"h9":8.5,"hr9":0.8,"babip":0.298,"lob_pct":73.5,"k_bb_pct":14.5,"recent_3_era":3.15,"recent_5_era":3.30,"recent_10_era":3.38,"gs":14,"innings":83.0,"wpa":1.0,"re24":7.0},
    "力亞士": {"team":"FG","foreign":True,"era":3.78,"whip":1.35,"fip":3.92,"xfip":3.88,"k9":7.5,"bb9":3.3,"h9":9.0,"hr9":1.0,"babip":0.310,"lob_pct":71.5,"k_bb_pct":12.2,"recent_3_era":3.50,"recent_5_era":3.65,"recent_10_era":3.75,"gs":13,"innings":77.1,"wpa":0.4,"re24":3.0},
    "安倍悠大":{"team":"FG","foreign":True,"era":3.52,"whip":1.28,"fip":3.65,"xfip":3.70,"k9":8.2,"bb9":3.0,"h9":8.6,"hr9":0.9,"babip":0.300,"lob_pct":72.8,"k_bb_pct":15.0,"recent_3_era":3.28,"recent_5_era":3.40,"recent_10_era":3.48,"gs":13,"innings":80.0,"wpa":0.9,"re24":6.2},
    "曾仁和": {
        "team": "FG", "foreign": False,
        "era": 5.12, "whip": 1.55, "fip": 5.08, "xfip": 4.92,
        "k9": 5.8, "bb9": 4.2, "h9": 10.2, "hr9": 1.3,
        "babip": 0.330, "lob_pct": 65.2, "k_bb_pct": 6.0,
        "recent_3_era": 7.50, "recent_5_era": 6.30, "recent_10_era": 5.80,
        "gs": 11, "innings": 63.0, "wpa": -2.1, "re24": -14.8,
    },
    "劉基鴻": {
        "team": "FG", "foreign": False,
        "era": 4.10, "whip": 1.39, "fip": 4.22, "xfip": 4.15,
        "k9": 7.1, "bb9": 3.4, "h9": 9.1, "hr9": 1.0,
        "babip": 0.318, "lob_pct": 70.8, "k_bb_pct": 11.2,
        "recent_3_era": 3.90, "recent_5_era": 4.00, "recent_10_era": 4.08,
        "gs": 12, "innings": 68.1, "wpa": -0.2, "re24": -1.5,
    },
    # ── 樂天桃猿 ──────────────────────────────
    "林晨樺": {
        "team": "WL", "foreign": False,
        "era": 2.67, "whip": 1.09, "fip": 2.78, "xfip": 2.88,
        "k9": 9.2, "bb9": 2.3, "h9": 7.0, "hr9": 0.5,
        "babip": 0.278, "lob_pct": 79.1, "k_bb_pct": 20.1,
        "recent_3_era": 1.50, "recent_5_era": 1.80, "recent_10_era": 2.40,
        "gs": 15, "innings": 94.2, "wpa": 4.1, "re24": 28.5,
    },
    "威能帝": {"team":"WL","foreign":True,"era":2.88,"whip":1.12,"fip":3.01,"xfip":3.10,"k9":8.8,"bb9":2.4,"h9":7.6,"hr9":0.7,"babip":0.285,"lob_pct":76.8,"k_bb_pct":18.2,"recent_3_era":2.60,"recent_5_era":2.75,"recent_10_era":2.85,"gs":15,"innings":90.2,"wpa":2.4,"re24":16.8},
    "魔爾曼": {"team":"WL","foreign":True,"era":3.55,"whip":1.28,"fip":3.68,"xfip":3.75,"k9":8.0,"bb9":3.1,"h9":8.8,"hr9":0.9,"babip":0.305,"lob_pct":72.5,"k_bb_pct":13.5,"recent_3_era":3.25,"recent_5_era":3.42,"recent_10_era":3.52,"gs":14,"innings":82.1,"wpa":0.7,"re24":4.9},
    "麥斯威尼":{"team":"WL","foreign":True,"era":3.82,"whip":1.35,"fip":3.95,"xfip":3.98,"k9":7.5,"bb9":3.3,"h9":9.0,"hr9":1.0,"babip":0.308,"lob_pct":71.2,"k_bb_pct":11.8,"recent_3_era":3.55,"recent_5_era":3.70,"recent_10_era":3.78,"gs":13,"innings":77.2,"wpa":0.3,"re24":2.1},
    "艾菩樂": {"team":"WL","foreign":True,"era":4.18,"whip":1.44,"fip":4.32,"xfip":4.25,"k9":6.9,"bb9":3.7,"h9":9.6,"hr9":1.2,"babip":0.322,"lob_pct":68.8,"k_bb_pct":9.5,"recent_3_era":3.95,"recent_5_era":4.08,"recent_10_era":4.15,"gs":12,"innings":70.0,"wpa":-0.4,"re24":-3.2},
    "榊原元稀":{"team":"WL","foreign":True,"era":3.32,"whip":1.20,"fip":3.45,"xfip":3.52,"k9":8.4,"bb9":2.8,"h9":8.2,"hr9":0.8,"babip":0.292,"lob_pct":74.5,"k_bb_pct":16.5,"recent_3_era":3.05,"recent_5_era":3.20,"recent_10_era":3.28,"gs":14,"innings":85.0,"wpa":1.2,"re24":8.2},
    "楊志龍": {
        "team": "WL", "foreign": False,
        "era": 4.56, "whip": 1.42, "fip": 4.61, "xfip": 4.52,
        "k9": 6.8, "bb9": 3.6, "h9": 9.5, "hr9": 1.1,
        "babip": 0.318, "lob_pct": 69.4, "k_bb_pct": 9.9,
        "recent_3_era": 3.90, "recent_5_era": 4.20, "recent_10_era": 4.45,
        "gs": 12, "innings": 69.0, "wpa": -0.8, "re24": -5.2,
    },
    "羅嘉仁": {
        "team": "WL", "foreign": False,
        "era": 3.62, "whip": 1.30, "fip": 3.75, "xfip": 3.80,
        "k9": 7.8, "bb9": 3.2, "h9": 8.9, "hr9": 0.9,
        "babip": 0.308, "lob_pct": 72.0, "k_bb_pct": 13.2,
        "recent_3_era": 3.40, "recent_5_era": 3.52, "recent_10_era": 3.58,
        "gs": 13, "innings": 79.0, "wpa": 0.6, "re24": 4.2,
    },
    "吳承諺": {
        "team": "WL", "foreign": False,
        "era": 4.22, "whip": 1.42, "fip": 4.35, "xfip": 4.28,
        "k9": 6.9, "bb9": 3.8, "h9": 9.4, "hr9": 1.1,
        "babip": 0.325, "lob_pct": 69.2, "k_bb_pct": 9.5,
        "recent_3_era": 4.00, "recent_5_era": 4.12, "recent_10_era": 4.18,
        "gs": 11, "innings": 62.2, "wpa": -0.3, "re24": -2.0,
    },
    # ── 台鋼雄鷹 ──────────────────────────────
    "黃子鵬": {
        "team": "TSG", "foreign": False,
        "era": 2.96, "whip": 1.15, "fip": 3.10, "xfip": 3.18,
        "k9": 8.2, "bb9": 2.6, "h9": 7.8, "hr9": 0.7,
        "babip": 0.288, "lob_pct": 76.0, "k_bb_pct": 17.2,
        "recent_3_era": 2.70, "recent_5_era": 2.85, "recent_10_era": 2.92,
        "gs": 9, "innings": 54.2, "wpa": 1.2, "re24": 8.5,
    },
    "江少慶": {
        "team": "TSG", "foreign": False,
        "era": 3.78, "whip": 1.35, "fip": 3.89, "xfip": 3.82,
        "k9": 7.5, "bb9": 3.3, "h9": 8.9, "hr9": 1.0,
        "babip": 0.310, "lob_pct": 71.5, "k_bb_pct": 12.4,
        "recent_3_era": 4.80, "recent_5_era": 4.50, "recent_10_era": 4.10,
        "gs": 13, "innings": 78.1, "wpa": 0.2, "re24": 1.5,
    },
    "後勁":   {"team":"TSG","foreign":True,"era":2.65,"whip":1.05,"fip":2.78,"xfip":2.92,"k9":9.3,"bb9":2.1,"h9":7.0,"hr9":0.6,"babip":0.275,"lob_pct":78.5,"k_bb_pct":20.8,"recent_3_era":2.38,"recent_5_era":2.52,"recent_10_era":2.62,"gs":15,"innings":93.0,"wpa":3.2,"re24":22.0},
    "石萬金": {"team":"TSG","foreign":True,"era":3.52,"whip":1.28,"fip":3.65,"xfip":3.72,"k9":8.1,"bb9":3.0,"h9":8.5,"hr9":0.9,"babip":0.300,"lob_pct":73.0,"k_bb_pct":14.8,"recent_3_era":3.25,"recent_5_era":3.40,"recent_10_era":3.48,"gs":14,"innings":82.2,"wpa":0.9,"re24":6.5},
    "布坎南": {"team":"TSG","foreign":True,"era":3.82,"whip":1.36,"fip":3.95,"xfip":3.98,"k9":7.4,"bb9":3.4,"h9":9.1,"hr9":1.0,"babip":0.312,"lob_pct":71.0,"k_bb_pct":11.5,"recent_3_era":3.55,"recent_5_era":3.70,"recent_10_era":3.78,"gs":13,"innings":77.0,"wpa":0.3,"re24":2.5},
    "櫻井周斗":{"team":"TSG","foreign":True,"era":3.40,"whip":1.24,"fip":3.52,"xfip":3.58,"k9":8.3,"bb9":2.9,"h9":8.4,"hr9":0.8,"babip":0.295,"lob_pct":73.8,"k_bb_pct":15.5,"recent_3_era":3.15,"recent_5_era":3.28,"recent_10_era":3.36,"gs":14,"innings":84.0,"wpa":1.1,"re24":7.5},
    "廖任磊": {
        "team": "TSG", "foreign": False,
        "era": 4.34, "whip": 1.41, "fip": 4.48, "xfip": 4.40,
        "k9": 7.0, "bb9": 3.7, "h9": 9.2, "hr9": 1.1,
        "babip": 0.322, "lob_pct": 70.0, "k_bb_pct": 9.8,
        "recent_3_era": 5.10, "recent_5_era": 4.80, "recent_10_era": 4.50,
        "gs": 12, "innings": 68.2, "wpa": -0.6, "re24": -4.3,
    },
    "黃龍義": {
        "team": "TSG", "foreign": False,
        "era": 4.18, "whip": 1.40, "fip": 4.30, "xfip": 4.22,
        "k9": 7.0, "bb9": 3.6, "h9": 9.3, "hr9": 1.1,
        "babip": 0.320, "lob_pct": 70.0, "k_bb_pct": 10.5,
        "recent_3_era": 3.95, "recent_5_era": 4.08, "recent_10_era": 4.15,
        "gs": 12, "innings": 70.1, "wpa": -0.3, "re24": -2.2,
    },
    # ── 味全龍 ──────────────────────────────────
    "甘特":   {"team":"WC","foreign":True,"era":1.49,"whip":0.95,"fip":1.82,"xfip":2.10,"k9":9.4,"bb9":1.8,"h9":6.5,"hr9":0.5,"babip":0.268,"lob_pct":82.0,"k_bb_pct":22.1,"recent_3_era":1.20,"recent_5_era":1.38,"recent_10_era":1.50,"gs":14,"innings":90.2,"wpa":4.1,"re24":28.5},
    "鋼龍":   {"team":"WC","foreign":True,"era":2.85,"whip":1.10,"fip":2.98,"xfip":3.08,"k9":8.9,"bb9":2.3,"h9":7.5,"hr9":0.7,"babip":0.282,"lob_pct":77.0,"k_bb_pct":19.2,"recent_3_era":2.58,"recent_5_era":2.72,"recent_10_era":2.82,"gs":14,"innings":89.0,"wpa":2.5,"re24":17.5},
    "艾璞樂": {"team":"WC","foreign":True,"era":3.62,"whip":1.30,"fip":3.75,"xfip":3.80,"k9":7.8,"bb9":3.2,"h9":8.9,"hr9":0.9,"babip":0.308,"lob_pct":72.0,"k_bb_pct":13.2,"recent_3_era":3.35,"recent_5_era":3.50,"recent_10_era":3.58,"gs":13,"innings":78.2,"wpa":0.6,"re24":4.2},
    "梅賽斯WC":{"team":"WC","foreign":True,"era":3.32,"whip":1.22,"fip":3.45,"xfip":3.52,"k9":8.5,"bb9":2.8,"h9":8.3,"hr9":0.8,"babip":0.295,"lob_pct":74.0,"k_bb_pct":16.8,"recent_3_era":3.05,"recent_5_era":3.20,"recent_10_era":3.28,"gs":14,"innings":83.2,"wpa":1.1,"re24":7.8},
    "馬丁尼茲":{"team":"WC","foreign":True,"era":4.02,"whip":1.40,"fip":4.15,"xfip":4.10,"k9":7.2,"bb9":3.5,"h9":9.2,"hr9":1.1,"babip":0.312,"lob_pct":70.2,"k_bb_pct":10.8,"recent_3_era":3.78,"recent_5_era":3.92,"recent_10_era":3.98,"gs":12,"innings":72.0,"wpa":-0.1,"re24":-0.5},
    "陳子豪": {
        "team": "WC", "foreign": False,
        "era": 3.55, "whip": 1.28, "fip": 3.68, "xfip": 3.74,
        "k9": 7.8, "bb9": 2.9, "h9": 8.4, "hr9": 0.9,
        "babip": 0.302, "lob_pct": 73.5, "k_bb_pct": 14.0,
        "recent_3_era": 3.20, "recent_5_era": 3.40, "recent_10_era": 3.60,
        "gs": 13, "innings": 81.0, "wpa": 1.2, "re24": 8.8,
    },
    "劉冠宇": {
        "team": "WC", "foreign": False,
        "era": 3.88, "whip": 1.36, "fip": 4.00, "xfip": 3.95,
        "k9": 7.4, "bb9": 3.3, "h9": 9.0, "hr9": 1.0,
        "babip": 0.312, "lob_pct": 71.5, "k_bb_pct": 12.0,
        "recent_3_era": 3.65, "recent_5_era": 3.78, "recent_10_era": 3.85,
        "gs": 13, "innings": 77.0, "wpa": 0.3, "re24": 2.0,
    },
}

# 各隊預設先發（無明確排班時使用 ace 數據供參考）
TEAM_DEFAULT_SP = {
    "AEL": "德保拉",  # ERA 2.18
    "CT":  "布雷克",  # ERA 2.78
    "FG":  "富藍戈",  # ERA 2.95
    "WL":  "威能帝",  # ERA 2.88
    "TSG": "後勁",    # ERA 2.65
    "WC":  "甘特",    # ERA 1.49
}

# ──────────────────────────────────────────────
# 野手完整數據
# 欄位說明：
#   pos      守備位置
#   bats     打席方向 R/L/S
#   avg/obp/slg/ops  主要打擊率
#   woba     加權上壘率
#   wrc_plus 跑者得分+ (聯盟均值=100)
#   babip    可守備範圍安打率
#   hr/rbi/sb  全壘打/打點/盜壘
#   bb_pct/k_pct  四壞/三振%
#   hard_hit_pct  強擊率%
#   games/pa/ab  出賽/打席/打數
#   recent_7/14_ops  近7/14天OPS
#   vs_lhp/rhp_ops  對左/右投OPS
#   home/away_ops   主客場OPS
# ──────────────────────────────────────────────
BATTERS = {
    # ══════════════ 中信兄弟 AEL ══════════════
    "江坤宇": {
        "team": "AEL", "pos": "2B", "bats": "R",
        "avg": 0.285, "obp": 0.352, "slg": 0.445, "ops": 0.797,
        "woba": 0.338, "wrc_plus": 108, "babip": 0.315, "iso": 0.160,
        "hr": 12, "rbi": 48, "sb": 10,
        "bb_pct": 9.0, "k_pct": 17.8, "hard_hit_pct": 39.2, "barrel_pct": 8.5,
        "games": 64, "pa": 270, "ab": 242,
        "recent_7_ops": 0.825, "recent_14_ops": 0.810,
        "vs_lhp_ops": 0.820, "vs_rhp_ops": 0.785,
        "home_ops": 0.810, "away_ops": 0.782,
    },
    "朱育賢": {
        "team": "AEL", "pos": "CF", "bats": "L",
        "avg": 0.302, "obp": 0.368, "slg": 0.470, "ops": 0.838,
        "woba": 0.355, "wrc_plus": 118, "babip": 0.335, "iso": 0.168,
        "hr": 10, "rbi": 42, "sb": 18,
        "bb_pct": 9.8, "k_pct": 15.2, "hard_hit_pct": 41.0, "barrel_pct": 9.2,
        "games": 63, "pa": 265, "ab": 232,
        "recent_7_ops": 0.860, "recent_14_ops": 0.845,
        "vs_lhp_ops": 0.875, "vs_rhp_ops": 0.820,
        "home_ops": 0.852, "away_ops": 0.822,
    },
    "王威晨": {
        "team": "AEL", "pos": "3B", "bats": "R",
        "avg": 0.278, "obp": 0.345, "slg": 0.432, "ops": 0.777,
        "woba": 0.330, "wrc_plus": 104, "babip": 0.308, "iso": 0.154,
        "hr": 10, "rbi": 44, "sb": 5,
        "bb_pct": 8.5, "k_pct": 19.5, "hard_hit_pct": 37.5, "barrel_pct": 7.8,
        "games": 62, "pa": 258, "ab": 233,
        "recent_7_ops": 0.792, "recent_14_ops": 0.782,
        "vs_lhp_ops": 0.802, "vs_rhp_ops": 0.762,
        "home_ops": 0.785, "away_ops": 0.768,
    },
    "高國慶": {
        "team": "AEL", "pos": "1B", "bats": "L",
        "avg": 0.292, "obp": 0.358, "slg": 0.488, "ops": 0.846,
        "woba": 0.358, "wrc_plus": 120, "babip": 0.318, "iso": 0.196,
        "hr": 16, "rbi": 55, "sb": 2,
        "bb_pct": 9.5, "k_pct": 20.8, "hard_hit_pct": 43.5, "barrel_pct": 11.5,
        "games": 60, "pa": 252, "ab": 224,
        "recent_7_ops": 0.862, "recent_14_ops": 0.850,
        "vs_lhp_ops": 0.905, "vs_rhp_ops": 0.828,
        "home_ops": 0.858, "away_ops": 0.832,
    },
    "吳秉承": {
        "team": "AEL", "pos": "RF", "bats": "R",
        "avg": 0.272, "obp": 0.335, "slg": 0.415, "ops": 0.750,
        "woba": 0.322, "wrc_plus": 98, "babip": 0.302, "iso": 0.143,
        "hr": 8, "rbi": 36, "sb": 7,
        "bb_pct": 7.8, "k_pct": 20.2, "hard_hit_pct": 35.8, "barrel_pct": 7.0,
        "games": 62, "pa": 248, "ab": 225,
        "recent_7_ops": 0.762, "recent_14_ops": 0.755,
        "vs_lhp_ops": 0.778, "vs_rhp_ops": 0.735,
        "home_ops": 0.758, "away_ops": 0.742,
    },
    "陳重廷": {
        "team": "AEL", "pos": "C", "bats": "R",
        "avg": 0.258, "obp": 0.318, "slg": 0.382, "ops": 0.700,
        "woba": 0.308, "wrc_plus": 88, "babip": 0.292, "iso": 0.124,
        "hr": 6, "rbi": 30, "sb": 1,
        "bb_pct": 7.2, "k_pct": 22.5, "hard_hit_pct": 32.8, "barrel_pct": 5.5,
        "games": 58, "pa": 228, "ab": 209,
        "recent_7_ops": 0.712, "recent_14_ops": 0.706,
        "vs_lhp_ops": 0.725, "vs_rhp_ops": 0.688,
        "home_ops": 0.708, "away_ops": 0.692,
    },
    "林凱威": {
        "team": "AEL", "pos": "SS", "bats": "R",
        "avg": 0.265, "obp": 0.322, "slg": 0.398, "ops": 0.720,
        "woba": 0.312, "wrc_plus": 92, "babip": 0.298, "iso": 0.133,
        "hr": 5, "rbi": 28, "sb": 14,
        "bb_pct": 7.0, "k_pct": 21.2, "hard_hit_pct": 33.5, "barrel_pct": 5.8,
        "games": 63, "pa": 255, "ab": 232,
        "recent_7_ops": 0.735, "recent_14_ops": 0.726,
        "vs_lhp_ops": 0.748, "vs_rhp_ops": 0.708,
        "home_ops": 0.728, "away_ops": 0.712,
    },
    "郭天信": {
        "team": "AEL", "pos": "LF", "bats": "L",
        "avg": 0.275, "obp": 0.340, "slg": 0.425, "ops": 0.765,
        "woba": 0.328, "wrc_plus": 102, "babip": 0.308, "iso": 0.150,
        "hr": 10, "rbi": 40, "sb": 4,
        "bb_pct": 8.8, "k_pct": 19.8, "hard_hit_pct": 36.2, "barrel_pct": 7.5,
        "games": 61, "pa": 250, "ab": 225,
        "recent_7_ops": 0.778, "recent_14_ops": 0.770,
        "vs_lhp_ops": 0.815, "vs_rhp_ops": 0.745,
        "home_ops": 0.772, "away_ops": 0.758,
    },
    # ══════════════ 統一7-ELEVEn獅 CT ══════════════
    "林哲瑄": {
        "team": "CT", "pos": "CF", "bats": "L",
        "avg": 0.308, "obp": 0.372, "slg": 0.488, "ops": 0.860,
        "woba": 0.362, "wrc_plus": 122, "babip": 0.338, "iso": 0.180,
        "hr": 11, "rbi": 46, "sb": 15,
        "bb_pct": 9.5, "k_pct": 16.5, "hard_hit_pct": 42.5, "barrel_pct": 10.2,
        "games": 63, "pa": 268, "ab": 237,
        "recent_7_ops": 0.875, "recent_14_ops": 0.862,
        "vs_lhp_ops": 0.902, "vs_rhp_ops": 0.842,
        "home_ops": 0.872, "away_ops": 0.848,
    },
    "高國麟": {
        "team": "CT", "pos": "DH", "bats": "R",
        "avg": 0.285, "obp": 0.352, "slg": 0.448, "ops": 0.800,
        "woba": 0.340, "wrc_plus": 110, "babip": 0.315, "iso": 0.163,
        "hr": 13, "rbi": 50, "sb": 3,
        "bb_pct": 9.2, "k_pct": 20.5, "hard_hit_pct": 40.2, "barrel_pct": 9.8,
        "games": 62, "pa": 262, "ab": 234,
        "recent_7_ops": 0.812, "recent_14_ops": 0.805,
        "vs_lhp_ops": 0.835, "vs_rhp_ops": 0.782,
        "home_ops": 0.818, "away_ops": 0.782,
    },
    "蘇智傑": {
        "team": "CT", "pos": "RF", "bats": "R",
        "avg": 0.292, "obp": 0.358, "slg": 0.462, "ops": 0.820,
        "woba": 0.348, "wrc_plus": 114, "babip": 0.322, "iso": 0.170,
        "hr": 10, "rbi": 44, "sb": 8,
        "bb_pct": 9.0, "k_pct": 18.5, "hard_hit_pct": 40.8, "barrel_pct": 9.5,
        "games": 62, "pa": 258, "ab": 230,
        "recent_7_ops": 0.832, "recent_14_ops": 0.824,
        "vs_lhp_ops": 0.855, "vs_rhp_ops": 0.805,
        "home_ops": 0.835, "away_ops": 0.805,
    },
    "王正棠": {
        "team": "CT", "pos": "2B", "bats": "R",
        "avg": 0.275, "obp": 0.340, "slg": 0.418, "ops": 0.758,
        "woba": 0.325, "wrc_plus": 100, "babip": 0.305, "iso": 0.143,
        "hr": 7, "rbi": 34, "sb": 9,
        "bb_pct": 8.5, "k_pct": 20.2, "hard_hit_pct": 36.5, "barrel_pct": 7.2,
        "games": 62, "pa": 252, "ab": 227,
        "recent_7_ops": 0.768, "recent_14_ops": 0.762,
        "vs_lhp_ops": 0.782, "vs_rhp_ops": 0.745,
        "home_ops": 0.768, "away_ops": 0.748,
    },
    "陳鏞基": {
        "team": "CT", "pos": "1B", "bats": "L",
        "avg": 0.280, "obp": 0.348, "slg": 0.455, "ops": 0.803,
        "woba": 0.342, "wrc_plus": 112, "babip": 0.308, "iso": 0.175,
        "hr": 12, "rbi": 48, "sb": 2,
        "bb_pct": 9.5, "k_pct": 21.5, "hard_hit_pct": 41.5, "barrel_pct": 10.5,
        "games": 60, "pa": 248, "ab": 220,
        "recent_7_ops": 0.815, "recent_14_ops": 0.808,
        "vs_lhp_ops": 0.845, "vs_rhp_ops": 0.782,
        "home_ops": 0.818, "away_ops": 0.788,
    },
    "林志祥": {
        "team": "CT", "pos": "SS", "bats": "R",
        "avg": 0.262, "obp": 0.322, "slg": 0.392, "ops": 0.714,
        "woba": 0.310, "wrc_plus": 90, "babip": 0.295, "iso": 0.130,
        "hr": 4, "rbi": 26, "sb": 11,
        "bb_pct": 7.2, "k_pct": 22.0, "hard_hit_pct": 32.5, "barrel_pct": 5.2,
        "games": 63, "pa": 250, "ab": 228,
        "recent_7_ops": 0.722, "recent_14_ops": 0.718,
        "vs_lhp_ops": 0.738, "vs_rhp_ops": 0.702,
        "home_ops": 0.720, "away_ops": 0.708,
    },
    "郭阜林": {
        "team": "CT", "pos": "3B", "bats": "R",
        "avg": 0.268, "obp": 0.332, "slg": 0.410, "ops": 0.742,
        "woba": 0.318, "wrc_plus": 95, "babip": 0.300, "iso": 0.142,
        "hr": 7, "rbi": 32, "sb": 3,
        "bb_pct": 8.0, "k_pct": 21.5, "hard_hit_pct": 35.2, "barrel_pct": 6.8,
        "games": 60, "pa": 242, "ab": 218,
        "recent_7_ops": 0.752, "recent_14_ops": 0.746,
        "vs_lhp_ops": 0.768, "vs_rhp_ops": 0.728,
        "home_ops": 0.748, "away_ops": 0.736,
    },
    "高明杰": {
        "team": "CT", "pos": "C", "bats": "R",
        "avg": 0.252, "obp": 0.312, "slg": 0.378, "ops": 0.690,
        "woba": 0.302, "wrc_plus": 84, "babip": 0.285, "iso": 0.126,
        "hr": 5, "rbi": 25, "sb": 0,
        "bb_pct": 7.0, "k_pct": 24.5, "hard_hit_pct": 30.5, "barrel_pct": 4.8,
        "games": 55, "pa": 215, "ab": 198,
        "recent_7_ops": 0.700, "recent_14_ops": 0.694,
        "vs_lhp_ops": 0.718, "vs_rhp_ops": 0.672,
        "home_ops": 0.698, "away_ops": 0.682,
    },
    # ══════════════ 富邦悍將 FG ══════════════
    "李凱威": {
        "team": "FG", "pos": "LF", "bats": "L",
        "avg": 0.292, "obp": 0.360, "slg": 0.468, "ops": 0.828,
        "woba": 0.352, "wrc_plus": 116, "babip": 0.322, "iso": 0.176,
        "hr": 11, "rbi": 47, "sb": 9,
        "bb_pct": 9.5, "k_pct": 18.2, "hard_hit_pct": 41.8, "barrel_pct": 10.0,
        "games": 63, "pa": 268, "ab": 238,
        "recent_7_ops": 0.845, "recent_14_ops": 0.835,
        "vs_lhp_ops": 0.872, "vs_rhp_ops": 0.808,
        "home_ops": 0.842, "away_ops": 0.815,
    },
    "王柏融": {
        "team": "FG", "pos": "DH", "bats": "L",
        "avg": 0.312, "obp": 0.382, "slg": 0.505, "ops": 0.887,
        "woba": 0.372, "wrc_plus": 130, "babip": 0.342, "iso": 0.193,
        "hr": 16, "rbi": 58, "sb": 5,
        "bb_pct": 10.2, "k_pct": 17.5, "hard_hit_pct": 45.2, "barrel_pct": 12.8,
        "games": 60, "pa": 255, "ab": 224,
        "recent_7_ops": 0.902, "recent_14_ops": 0.890,
        "vs_lhp_ops": 0.945, "vs_rhp_ops": 0.862,
        "home_ops": 0.895, "away_ops": 0.878,
    },
    "謝仕洋": {
        "team": "FG", "pos": "3B", "bats": "R",
        "avg": 0.275, "obp": 0.342, "slg": 0.438, "ops": 0.780,
        "woba": 0.332, "wrc_plus": 105, "babip": 0.308, "iso": 0.163,
        "hr": 9, "rbi": 40, "sb": 4,
        "bb_pct": 8.8, "k_pct": 20.8, "hard_hit_pct": 38.2, "barrel_pct": 8.2,
        "games": 62, "pa": 258, "ab": 232,
        "recent_7_ops": 0.792, "recent_14_ops": 0.785,
        "vs_lhp_ops": 0.808, "vs_rhp_ops": 0.762,
        "home_ops": 0.788, "away_ops": 0.772,
    },
    "吳念庭": {
        "team": "FG", "pos": "2B", "bats": "L",
        "avg": 0.285, "obp": 0.352, "slg": 0.442, "ops": 0.794,
        "woba": 0.338, "wrc_plus": 108, "babip": 0.315, "iso": 0.157,
        "hr": 7, "rbi": 36, "sb": 11,
        "bb_pct": 9.2, "k_pct": 19.5, "hard_hit_pct": 37.8, "barrel_pct": 7.8,
        "games": 63, "pa": 262, "ab": 235,
        "recent_7_ops": 0.808, "recent_14_ops": 0.800,
        "vs_lhp_ops": 0.832, "vs_rhp_ops": 0.775,
        "home_ops": 0.800, "away_ops": 0.788,
    },
    "林智平": {
        "team": "FG", "pos": "CF", "bats": "R",
        "avg": 0.268, "obp": 0.330, "slg": 0.408, "ops": 0.738,
        "woba": 0.318, "wrc_plus": 96, "babip": 0.298, "iso": 0.140,
        "hr": 6, "rbi": 30, "sb": 13,
        "bb_pct": 7.8, "k_pct": 20.8, "hard_hit_pct": 34.8, "barrel_pct": 6.5,
        "games": 63, "pa": 252, "ab": 228,
        "recent_7_ops": 0.750, "recent_14_ops": 0.744,
        "vs_lhp_ops": 0.765, "vs_rhp_ops": 0.722,
        "home_ops": 0.745, "away_ops": 0.732,
    },
    "呂彥青": {
        "team": "FG", "pos": "C", "bats": "R",
        "avg": 0.255, "obp": 0.315, "slg": 0.380, "ops": 0.695,
        "woba": 0.305, "wrc_plus": 86, "babip": 0.288, "iso": 0.125,
        "hr": 5, "rbi": 26, "sb": 0,
        "bb_pct": 7.2, "k_pct": 23.8, "hard_hit_pct": 31.5, "barrel_pct": 5.0,
        "games": 57, "pa": 222, "ab": 204,
        "recent_7_ops": 0.705, "recent_14_ops": 0.700,
        "vs_lhp_ops": 0.722, "vs_rhp_ops": 0.678,
        "home_ops": 0.702, "away_ops": 0.688,
    },
    "黃鈞聲": {
        "team": "FG", "pos": "SS", "bats": "R",
        "avg": 0.262, "obp": 0.322, "slg": 0.395, "ops": 0.717,
        "woba": 0.312, "wrc_plus": 92, "babip": 0.295, "iso": 0.133,
        "hr": 4, "rbi": 25, "sb": 8,
        "bb_pct": 7.5, "k_pct": 22.2, "hard_hit_pct": 33.2, "barrel_pct": 5.5,
        "games": 62, "pa": 248, "ab": 226,
        "recent_7_ops": 0.728, "recent_14_ops": 0.722,
        "vs_lhp_ops": 0.742, "vs_rhp_ops": 0.705,
        "home_ops": 0.722, "away_ops": 0.712,
    },
    "張政禹": {
        "team": "FG", "pos": "RF", "bats": "R",
        "avg": 0.270, "obp": 0.335, "slg": 0.422, "ops": 0.757,
        "woba": 0.325, "wrc_plus": 100, "babip": 0.302, "iso": 0.152,
        "hr": 8, "rbi": 35, "sb": 5,
        "bb_pct": 8.2, "k_pct": 20.5, "hard_hit_pct": 36.0, "barrel_pct": 7.2,
        "games": 61, "pa": 248, "ab": 222,
        "recent_7_ops": 0.768, "recent_14_ops": 0.762,
        "vs_lhp_ops": 0.785, "vs_rhp_ops": 0.740,
        "home_ops": 0.762, "away_ops": 0.752,
    },
    # ══════════════ 樂天桃猿 WL ══════════════
    "余謙": {
        "team": "WL", "pos": "SS", "bats": "R",
        "avg": 0.295, "obp": 0.368, "slg": 0.478, "ops": 0.846,
        "woba": 0.358, "wrc_plus": 120, "babip": 0.325, "iso": 0.183,
        "hr": 12, "rbi": 50, "sb": 14,
        "bb_pct": 10.2, "k_pct": 17.5, "hard_hit_pct": 42.5, "barrel_pct": 10.8,
        "games": 64, "pa": 272, "ab": 238,
        "recent_7_ops": 0.862, "recent_14_ops": 0.852,
        "vs_lhp_ops": 0.888, "vs_rhp_ops": 0.828,
        "home_ops": 0.858, "away_ops": 0.835,
    },
    "陳晨威": {
        "team": "WL", "pos": "CF", "bats": "S",
        "avg": 0.298, "obp": 0.368, "slg": 0.480, "ops": 0.848,
        "woba": 0.360, "wrc_plus": 122, "babip": 0.330, "iso": 0.182,
        "hr": 12, "rbi": 48, "sb": 20,
        "bb_pct": 10.0, "k_pct": 17.2, "hard_hit_pct": 43.2, "barrel_pct": 10.5,
        "games": 64, "pa": 275, "ab": 242,
        "recent_7_ops": 0.865, "recent_14_ops": 0.855,
        "vs_lhp_ops": 0.895, "vs_rhp_ops": 0.832,
        "home_ops": 0.862, "away_ops": 0.835,
    },
    "林立": {
        "team": "WL", "pos": "2B", "bats": "R",
        "avg": 0.315, "obp": 0.385, "slg": 0.515, "ops": 0.900,
        "woba": 0.380, "wrc_plus": 135, "babip": 0.348, "iso": 0.200,
        "hr": 15, "rbi": 58, "sb": 10,
        "bb_pct": 10.5, "k_pct": 16.5, "hard_hit_pct": 46.5, "barrel_pct": 13.5,
        "games": 64, "pa": 278, "ab": 244,
        "recent_7_ops": 0.918, "recent_14_ops": 0.908,
        "vs_lhp_ops": 0.952, "vs_rhp_ops": 0.878,
        "home_ops": 0.912, "away_ops": 0.888,
    },
    "林承飛": {
        "team": "WL", "pos": "LF", "bats": "L",
        "avg": 0.280, "obp": 0.348, "slg": 0.448, "ops": 0.796,
        "woba": 0.338, "wrc_plus": 108, "babip": 0.312, "iso": 0.168,
        "hr": 10, "rbi": 42, "sb": 7,
        "bb_pct": 9.5, "k_pct": 19.5, "hard_hit_pct": 38.8, "barrel_pct": 9.0,
        "games": 62, "pa": 258, "ab": 230,
        "recent_7_ops": 0.810, "recent_14_ops": 0.802,
        "vs_lhp_ops": 0.838, "vs_rhp_ops": 0.775,
        "home_ops": 0.808, "away_ops": 0.785,
    },
    "鄭浩均": {
        "team": "WL", "pos": "1B", "bats": "L",
        "avg": 0.275, "obp": 0.345, "slg": 0.442, "ops": 0.787,
        "woba": 0.335, "wrc_plus": 106, "babip": 0.308, "iso": 0.167,
        "hr": 11, "rbi": 45, "sb": 3,
        "bb_pct": 9.5, "k_pct": 21.5, "hard_hit_pct": 39.5, "barrel_pct": 9.5,
        "games": 61, "pa": 252, "ab": 224,
        "recent_7_ops": 0.800, "recent_14_ops": 0.793,
        "vs_lhp_ops": 0.825, "vs_rhp_ops": 0.768,
        "home_ops": 0.795, "away_ops": 0.780,
    },
    "陳子強": {
        "team": "WL", "pos": "3B", "bats": "R",
        "avg": 0.265, "obp": 0.328, "slg": 0.412, "ops": 0.740,
        "woba": 0.318, "wrc_plus": 96, "babip": 0.298, "iso": 0.147,
        "hr": 7, "rbi": 32, "sb": 5,
        "bb_pct": 8.2, "k_pct": 21.5, "hard_hit_pct": 35.5, "barrel_pct": 7.0,
        "games": 60, "pa": 242, "ab": 218,
        "recent_7_ops": 0.752, "recent_14_ops": 0.746,
        "vs_lhp_ops": 0.768, "vs_rhp_ops": 0.722,
        "home_ops": 0.748, "away_ops": 0.732,
    },
    "游霆崴": {
        "team": "WL", "pos": "C", "bats": "R",
        "avg": 0.255, "obp": 0.315, "slg": 0.382, "ops": 0.697,
        "woba": 0.305, "wrc_plus": 87, "babip": 0.288, "iso": 0.127,
        "hr": 5, "rbi": 26, "sb": 1,
        "bb_pct": 7.5, "k_pct": 24.0, "hard_hit_pct": 31.8, "barrel_pct": 5.2,
        "games": 56, "pa": 218, "ab": 200,
        "recent_7_ops": 0.708, "recent_14_ops": 0.702,
        "vs_lhp_ops": 0.725, "vs_rhp_ops": 0.682,
        "home_ops": 0.705, "away_ops": 0.690,
    },
    "許基宏": {
        "team": "WL", "pos": "RF", "bats": "R",
        "avg": 0.270, "obp": 0.335, "slg": 0.425, "ops": 0.760,
        "woba": 0.325, "wrc_plus": 100, "babip": 0.302, "iso": 0.155,
        "hr": 8, "rbi": 36, "sb": 6,
        "bb_pct": 8.5, "k_pct": 21.0, "hard_hit_pct": 36.8, "barrel_pct": 7.5,
        "games": 61, "pa": 248, "ab": 222,
        "recent_7_ops": 0.772, "recent_14_ops": 0.765,
        "vs_lhp_ops": 0.788, "vs_rhp_ops": 0.742,
        "home_ops": 0.768, "away_ops": 0.752,
    },
    # ══════════════ 台鋼雄鷹 TSG ══════════════
    "林子偉": {
        "team": "TSG", "pos": "SS", "bats": "R",
        "avg": 0.295, "obp": 0.365, "slg": 0.472, "ops": 0.837,
        "woba": 0.355, "wrc_plus": 118, "babip": 0.325, "iso": 0.177,
        "hr": 12, "rbi": 48, "sb": 12,
        "bb_pct": 10.0, "k_pct": 18.5, "hard_hit_pct": 41.5, "barrel_pct": 10.2,
        "games": 62, "pa": 265, "ab": 234,
        "recent_7_ops": 0.852, "recent_14_ops": 0.844,
        "vs_lhp_ops": 0.878, "vs_rhp_ops": 0.818,
        "home_ops": 0.848, "away_ops": 0.826,
    },
    "廖健富": {
        "team": "TSG", "pos": "1B", "bats": "L",
        "avg": 0.282, "obp": 0.348, "slg": 0.450, "ops": 0.798,
        "woba": 0.340, "wrc_plus": 110, "babip": 0.312, "iso": 0.168,
        "hr": 13, "rbi": 50, "sb": 2,
        "bb_pct": 9.5, "k_pct": 21.2, "hard_hit_pct": 41.0, "barrel_pct": 10.2,
        "games": 61, "pa": 252, "ab": 224,
        "recent_7_ops": 0.812, "recent_14_ops": 0.805,
        "vs_lhp_ops": 0.838, "vs_rhp_ops": 0.778,
        "home_ops": 0.808, "away_ops": 0.788,
    },
    "邱智呈": {
        "team": "TSG", "pos": "3B", "bats": "R",
        "avg": 0.272, "obp": 0.338, "slg": 0.428, "ops": 0.766,
        "woba": 0.328, "wrc_plus": 103, "babip": 0.305, "iso": 0.156,
        "hr": 9, "rbi": 38, "sb": 4,
        "bb_pct": 8.8, "k_pct": 20.8, "hard_hit_pct": 37.8, "barrel_pct": 8.0,
        "games": 61, "pa": 250, "ab": 224,
        "recent_7_ops": 0.778, "recent_14_ops": 0.772,
        "vs_lhp_ops": 0.795, "vs_rhp_ops": 0.748,
        "home_ops": 0.775, "away_ops": 0.758,
    },
    "謝榮豪": {
        "team": "TSG", "pos": "LF", "bats": "L",
        "avg": 0.265, "obp": 0.328, "slg": 0.408, "ops": 0.736,
        "woba": 0.318, "wrc_plus": 95, "babip": 0.298, "iso": 0.143,
        "hr": 7, "rbi": 32, "sb": 6,
        "bb_pct": 8.2, "k_pct": 21.5, "hard_hit_pct": 34.8, "barrel_pct": 6.8,
        "games": 60, "pa": 242, "ab": 218,
        "recent_7_ops": 0.748, "recent_14_ops": 0.742,
        "vs_lhp_ops": 0.775, "vs_rhp_ops": 0.715,
        "home_ops": 0.745, "away_ops": 0.728,
    },
    "吳東融": {
        "team": "TSG", "pos": "CF", "bats": "R",
        "avg": 0.270, "obp": 0.335, "slg": 0.420, "ops": 0.755,
        "woba": 0.322, "wrc_plus": 98, "babip": 0.302, "iso": 0.150,
        "hr": 7, "rbi": 30, "sb": 10,
        "bb_pct": 8.5, "k_pct": 21.0, "hard_hit_pct": 35.5, "barrel_pct": 7.2,
        "games": 62, "pa": 250, "ab": 224,
        "recent_7_ops": 0.768, "recent_14_ops": 0.762,
        "vs_lhp_ops": 0.782, "vs_rhp_ops": 0.738,
        "home_ops": 0.762, "away_ops": 0.748,
    },
    "胡金龍": {
        "team": "TSG", "pos": "2B", "bats": "R",
        "avg": 0.268, "obp": 0.330, "slg": 0.405, "ops": 0.735,
        "woba": 0.315, "wrc_plus": 93, "babip": 0.298, "iso": 0.137,
        "hr": 5, "rbi": 28, "sb": 8,
        "bb_pct": 7.8, "k_pct": 22.5, "hard_hit_pct": 33.8, "barrel_pct": 6.0,
        "games": 62, "pa": 248, "ab": 225,
        "recent_7_ops": 0.748, "recent_14_ops": 0.740,
        "vs_lhp_ops": 0.762, "vs_rhp_ops": 0.718,
        "home_ops": 0.742, "away_ops": 0.728,
    },
    "林孟學": {
        "team": "TSG", "pos": "RF", "bats": "R",
        "avg": 0.262, "obp": 0.325, "slg": 0.398, "ops": 0.723,
        "woba": 0.312, "wrc_plus": 91, "babip": 0.295, "iso": 0.136,
        "hr": 5, "rbi": 26, "sb": 3,
        "bb_pct": 7.8, "k_pct": 23.0, "hard_hit_pct": 32.8, "barrel_pct": 5.5,
        "games": 58, "pa": 232, "ab": 210,
        "recent_7_ops": 0.735, "recent_14_ops": 0.728,
        "vs_lhp_ops": 0.748, "vs_rhp_ops": 0.708,
        "home_ops": 0.730, "away_ops": 0.716,
    },
    "高志綱": {
        "team": "TSG", "pos": "C", "bats": "R",
        "avg": 0.250, "obp": 0.308, "slg": 0.370, "ops": 0.678,
        "woba": 0.298, "wrc_plus": 82, "babip": 0.282, "iso": 0.120,
        "hr": 4, "rbi": 22, "sb": 0,
        "bb_pct": 6.8, "k_pct": 25.0, "hard_hit_pct": 29.8, "barrel_pct": 4.5,
        "games": 52, "pa": 202, "ab": 188,
        "recent_7_ops": 0.688, "recent_14_ops": 0.682,
        "vs_lhp_ops": 0.705, "vs_rhp_ops": 0.662,
        "home_ops": 0.685, "away_ops": 0.672,
    },
    # ══════════════ 味全龍 WC ══════════════
    "陳俊秀": {
        "team": "WC", "pos": "1B", "bats": "L",
        "avg": 0.298, "obp": 0.368, "slg": 0.480, "ops": 0.848,
        "woba": 0.360, "wrc_plus": 122, "babip": 0.328, "iso": 0.182,
        "hr": 14, "rbi": 53, "sb": 4,
        "bb_pct": 10.0, "k_pct": 19.5, "hard_hit_pct": 43.0, "barrel_pct": 11.2,
        "games": 62, "pa": 262, "ab": 232,
        "recent_7_ops": 0.862, "recent_14_ops": 0.855,
        "vs_lhp_ops": 0.898, "vs_rhp_ops": 0.828,
        "home_ops": 0.862, "away_ops": 0.835,
    },
    "高宇杰": {
        "team": "WC", "pos": "3B", "bats": "R",
        "avg": 0.285, "obp": 0.352, "slg": 0.460, "ops": 0.812,
        "woba": 0.345, "wrc_plus": 115, "babip": 0.315, "iso": 0.175,
        "hr": 12, "rbi": 47, "sb": 5,
        "bb_pct": 9.2, "k_pct": 19.8, "hard_hit_pct": 41.8, "barrel_pct": 10.5,
        "games": 62, "pa": 258, "ab": 230,
        "recent_7_ops": 0.825, "recent_14_ops": 0.818,
        "vs_lhp_ops": 0.848, "vs_rhp_ops": 0.792,
        "home_ops": 0.820, "away_ops": 0.805,
    },
    "彭名傑": {
        "team": "WC", "pos": "2B", "bats": "R",
        "avg": 0.278, "obp": 0.345, "slg": 0.438, "ops": 0.783,
        "woba": 0.332, "wrc_plus": 106, "babip": 0.308, "iso": 0.160,
        "hr": 9, "rbi": 40, "sb": 9,
        "bb_pct": 9.0, "k_pct": 20.5, "hard_hit_pct": 38.5, "barrel_pct": 8.5,
        "games": 62, "pa": 255, "ab": 228,
        "recent_7_ops": 0.795, "recent_14_ops": 0.788,
        "vs_lhp_ops": 0.812, "vs_rhp_ops": 0.764,
        "home_ops": 0.792, "away_ops": 0.775,
    },
    "周柏諺": {
        "team": "WC", "pos": "CF", "bats": "L",
        "avg": 0.292, "obp": 0.360, "slg": 0.470, "ops": 0.830,
        "woba": 0.350, "wrc_plus": 117, "babip": 0.322, "iso": 0.178,
        "hr": 11, "rbi": 44, "sb": 16,
        "bb_pct": 9.5, "k_pct": 18.2, "hard_hit_pct": 41.5, "barrel_pct": 10.0,
        "games": 63, "pa": 265, "ab": 235,
        "recent_7_ops": 0.845, "recent_14_ops": 0.837,
        "vs_lhp_ops": 0.878, "vs_rhp_ops": 0.808,
        "home_ops": 0.842, "away_ops": 0.818,
    },
    "詹智堯": {
        "team": "WC", "pos": "RF", "bats": "R",
        "avg": 0.270, "obp": 0.335, "slg": 0.422, "ops": 0.757,
        "woba": 0.325, "wrc_plus": 100, "babip": 0.302, "iso": 0.152,
        "hr": 8, "rbi": 35, "sb": 7,
        "bb_pct": 8.5, "k_pct": 21.2, "hard_hit_pct": 36.5, "barrel_pct": 7.5,
        "games": 61, "pa": 248, "ab": 222,
        "recent_7_ops": 0.770, "recent_14_ops": 0.763,
        "vs_lhp_ops": 0.788, "vs_rhp_ops": 0.738,
        "home_ops": 0.765, "away_ops": 0.750,
    },
    "鄭鈞仁": {
        "team": "WC", "pos": "SS", "bats": "R",
        "avg": 0.262, "obp": 0.325, "slg": 0.398, "ops": 0.723,
        "woba": 0.312, "wrc_plus": 91, "babip": 0.295, "iso": 0.136,
        "hr": 5, "rbi": 28, "sb": 10,
        "bb_pct": 7.8, "k_pct": 22.5, "hard_hit_pct": 33.0, "barrel_pct": 5.8,
        "games": 62, "pa": 248, "ab": 225,
        "recent_7_ops": 0.735, "recent_14_ops": 0.728,
        "vs_lhp_ops": 0.748, "vs_rhp_ops": 0.708,
        "home_ops": 0.730, "away_ops": 0.716,
    },
    "吳偲佑": {
        "team": "WC", "pos": "LF", "bats": "L",
        "avg": 0.265, "obp": 0.330, "slg": 0.410, "ops": 0.740,
        "woba": 0.318, "wrc_plus": 95, "babip": 0.298, "iso": 0.145,
        "hr": 7, "rbi": 30, "sb": 5,
        "bb_pct": 8.5, "k_pct": 22.0, "hard_hit_pct": 34.5, "barrel_pct": 6.8,
        "games": 60, "pa": 242, "ab": 218,
        "recent_7_ops": 0.752, "recent_14_ops": 0.745,
        "vs_lhp_ops": 0.778, "vs_rhp_ops": 0.718,
        "home_ops": 0.748, "away_ops": 0.732,
    },
    "李哲帆": {
        "team": "WC", "pos": "C", "bats": "R",
        "avg": 0.248, "obp": 0.308, "slg": 0.370, "ops": 0.678,
        "woba": 0.298, "wrc_plus": 82, "babip": 0.280, "iso": 0.122,
        "hr": 4, "rbi": 22, "sb": 1,
        "bb_pct": 7.0, "k_pct": 25.5, "hard_hit_pct": 29.5, "barrel_pct": 4.5,
        "games": 52, "pa": 205, "ab": 190,
        "recent_7_ops": 0.688, "recent_14_ops": 0.682,
        "vs_lhp_ops": 0.705, "vs_rhp_ops": 0.660,
        "home_ops": 0.685, "away_ops": 0.672,
    },
}

# ──────────────────────────────────────────────
# 牛棚關鍵成員
# 欄位說明：
#   role    CL=終結者 SU=設置 MR=中繼
#   era/whip/k9/bb9  投球指標
#   sv/hld/bs  救援/中繼/吹救
#   ip       局數
#   consec_days  連續出賽天數（疲勞指標）
#   recent_3_era 近3場防禦率
# ──────────────────────────────────────────────
BULLPEN = {
    # ── 中信兄弟 ──
    "江辰晏": {
        "team": "AEL", "role": "CL",
        "era": 1.85, "whip": 0.92, "k9": 11.2, "bb9": 2.5,
        "sv": 15, "hld": 0, "bs": 2, "ip": 43.2,
        "consec_days": 0, "recent_3_era": 1.50,
    },
    "李杰明": {
        "team": "AEL", "role": "SU",
        "era": 2.95, "whip": 1.18, "k9": 9.5, "bb9": 3.2,
        "sv": 2, "hld": 12, "bs": 1, "ip": 39.1,
        "consec_days": 1, "recent_3_era": 2.70,
    },
    "朱立人": {
        "team": "AEL", "role": "MR",
        "era": 3.45, "whip": 1.32, "k9": 8.2, "bb9": 3.8,
        "sv": 0, "hld": 8, "bs": 1, "ip": 36.2,
        "consec_days": 0, "recent_3_era": 3.20,
    },
    # ── 統一獅 ──
    "林鼎棫": {
        "team": "CT", "role": "CL",
        "era": 2.25, "whip": 1.05, "k9": 10.5, "bb9": 2.8,
        "sv": 14, "hld": 0, "bs": 3, "ip": 40.0,
        "consec_days": 2, "recent_3_era": 2.70,
    },
    "陳禹勳": {
        "team": "CT", "role": "SU",
        "era": 3.12, "whip": 1.22, "k9": 8.8, "bb9": 3.5,
        "sv": 1, "hld": 10, "bs": 2, "ip": 37.2,
        "consec_days": 0, "recent_3_era": 2.95,
    },
    "許凱威": {
        "team": "CT", "role": "MR",
        "era": 3.78, "whip": 1.38, "k9": 7.8, "bb9": 4.0,
        "sv": 0, "hld": 7, "bs": 1, "ip": 33.2,
        "consec_days": 1, "recent_3_era": 3.50,
    },
    # ── 富邦悍將 ──
    "張詠丞": {
        "team": "FG", "role": "CL",
        "era": 2.05, "whip": 0.98, "k9": 11.5, "bb9": 2.2,
        "sv": 16, "hld": 0, "bs": 2, "ip": 44.0,
        "consec_days": 1, "recent_3_era": 1.80,
    },
    "林子昱": {
        "team": "FG", "role": "SU",
        "era": 2.85, "whip": 1.15, "k9": 9.8, "bb9": 3.0,
        "sv": 2, "hld": 11, "bs": 1, "ip": 41.2,
        "consec_days": 0, "recent_3_era": 2.60,
    },
    "王躍霖": {
        "team": "FG", "role": "MR",
        "era": 3.55, "whip": 1.30, "k9": 8.5, "bb9": 3.5,
        "sv": 0, "hld": 9, "bs": 2, "ip": 35.2,
        "consec_days": 2, "recent_3_era": 3.80,
    },
    # ── 樂天桃猿 ──
    "宋文華": {
        "team": "WL", "role": "CL",
        "era": 1.65, "whip": 0.88, "k9": 11.8, "bb9": 2.0,
        "sv": 18, "hld": 0, "bs": 1, "ip": 43.2,
        "consec_days": 0, "recent_3_era": 1.50,
    },
    "朱哲民": {
        "team": "WL", "role": "SU",
        "era": 2.45, "whip": 1.08, "k9": 10.2, "bb9": 2.8,
        "sv": 3, "hld": 14, "bs": 1, "ip": 44.0,
        "consec_days": 1, "recent_3_era": 2.20,
    },
    "劉致榮": {
        "team": "WL", "role": "MR",
        "era": 3.25, "whip": 1.22, "k9": 8.8, "bb9": 3.2,
        "sv": 1, "hld": 10, "bs": 1, "ip": 38.2,
        "consec_days": 0, "recent_3_era": 3.00,
    },
    # ── 台鋼雄鷹 ──
    "黃俊中": {
        "team": "TSG", "role": "CL",
        "era": 2.35, "whip": 1.08, "k9": 10.8, "bb9": 2.8,
        "sv": 13, "hld": 0, "bs": 3, "ip": 38.1,
        "consec_days": 1, "recent_3_era": 2.80,
    },
    "顏佑倫": {
        "team": "TSG", "role": "SU",
        "era": 3.05, "whip": 1.20, "k9": 9.2, "bb9": 3.3,
        "sv": 1, "hld": 9, "bs": 2, "ip": 35.2,
        "consec_days": 2, "recent_3_era": 3.50,
    },
    "龔宬宇": {
        "team": "TSG", "role": "MR",
        "era": 3.65, "whip": 1.35, "k9": 8.0, "bb9": 3.8,
        "sv": 0, "hld": 8, "bs": 1, "ip": 32.0,
        "consec_days": 0, "recent_3_era": 3.40,
    },
    # ── 味全龍 ──
    "鄭凱文": {
        "team": "WC", "role": "CL",
        "era": 1.95, "whip": 0.95, "k9": 11.2, "bb9": 2.2,
        "sv": 14, "hld": 0, "bs": 2, "ip": 41.2,
        "consec_days": 0, "recent_3_era": 1.70,
    },
    "呂偲緯": {
        "team": "WC", "role": "SU",
        "era": 2.75, "whip": 1.12, "k9": 10.0, "bb9": 2.8,
        "sv": 2, "hld": 12, "bs": 1, "ip": 39.1,
        "consec_days": 1, "recent_3_era": 2.50,
    },
    "謝子菘": {
        "team": "WC", "role": "MR",
        "era": 3.45, "whip": 1.28, "k9": 8.5, "bb9": 3.5,
        "sv": 0, "hld": 8, "bs": 2, "ip": 34.2,
        "consec_days": 0, "recent_3_era": 3.20,
    },
}

# ──────────────────────────────────────────────
# 球隊整體數據
# ──────────────────────────────────────────────
TEAM_STATS = {
    "AEL": {
        "batting": {
            "avg": 0.282, "obp": 0.348, "slg": 0.448, "ops": 0.796,
            "woba": 0.342, "wrc_plus": 108,
            "runs_per_game": 5.2, "hr_per_game": 1.1,
            "recent_7_ops": 0.820, "recent_14_ops": 0.808, "recent_30_ops": 0.802,
        },
        "bullpen": {
            "era": 3.21, "whip": 1.18, "fip": 3.35,
            "save_pct": 72.0, "hold_pct": 68.5,
            "last7_games": 12, "last7_pitches": 380,
            "closer_consecutive_days": 1,
            "fatigue_score": 42,  # 0=fresh, 100=exhausted
        },
        "defense": {
            "fielding_pct": 0.982, "errors": 28, "drs": 8, "uzr": 5.2,
        },
        "record": {
            "w": 32, "l": 18, "pct": 0.640,
            "home_w": 18, "home_l": 8,
            "away_w": 14, "away_l": 10,
            "last5": [1,1,0,1,1], "last10": [1,1,0,1,1,0,1,0,1,1],
            "run_diff": 52,
        },
        "elo": 1578,
        "injuries": [],
        "schedule_fatigue": 2,  # games in last 7 days
    },
    "CT": {
        "batting": {
            "avg": 0.265, "obp": 0.328, "slg": 0.418, "ops": 0.746,
            "woba": 0.318, "wrc_plus": 95,
            "runs_per_game": 4.6, "hr_per_game": 0.9,
            "recent_7_ops": 0.730, "recent_14_ops": 0.738, "recent_30_ops": 0.745,
        },
        "bullpen": {
            "era": 3.89, "whip": 1.35, "fip": 3.98,
            "save_pct": 62.5, "hold_pct": 60.0,
            "last7_games": 15, "last7_pitches": 445,
            "closer_consecutive_days": 2,
            "fatigue_score": 65,
        },
        "defense": {
            "fielding_pct": 0.978, "errors": 35, "drs": -2, "uzr": -1.8,
        },
        "record": {
            "w": 22, "l": 28, "pct": 0.440,
            "home_w": 12, "home_l": 14,
            "away_w": 10, "away_l": 14,
            "last5": [0,1,0,0,1], "last10": [1,0,1,0,0,1,0,0,1,0],
            "run_diff": -18,
        },
        "elo": 1452,
        "injuries": ["陳傑憲（腿傷，DL15）"],
        "schedule_fatigue": 5,
    },
    "FG": {
        "batting": {
            "avg": 0.271, "obp": 0.338, "slg": 0.428, "ops": 0.766,
            "woba": 0.328, "wrc_plus": 101,
            "runs_per_game": 4.9, "hr_per_game": 1.0,
            "recent_7_ops": 0.790, "recent_14_ops": 0.775, "recent_30_ops": 0.768,
        },
        "bullpen": {
            "era": 3.45, "whip": 1.24, "fip": 3.58,
            "save_pct": 68.0, "hold_pct": 65.2,
            "last7_games": 10, "last7_pitches": 312,
            "closer_consecutive_days": 0,
            "fatigue_score": 28,
        },
        "defense": {
            "fielding_pct": 0.980, "errors": 32, "drs": 3, "uzr": 2.1,
        },
        "record": {
            "w": 26, "l": 24, "pct": 0.520,
            "home_w": 14, "home_l": 12,
            "away_w": 12, "away_l": 12,
            "last5": [1,0,1,1,0], "last10": [1,1,0,1,0,1,0,1,1,0],
            "run_diff": 8,
        },
        "elo": 1508,
        "injuries": [],
        "schedule_fatigue": 3,
    },
    "WL": {
        "batting": {
            "avg": 0.291, "obp": 0.360, "slg": 0.468, "ops": 0.828,
            "woba": 0.358, "wrc_plus": 115,
            "runs_per_game": 5.6, "hr_per_game": 1.3,
            "recent_7_ops": 0.855, "recent_14_ops": 0.842, "recent_30_ops": 0.830,
        },
        "bullpen": {
            "era": 2.98, "whip": 1.12, "fip": 3.12,
            "save_pct": 78.5, "hold_pct": 72.0,
            "last7_games": 8, "last7_pitches": 245,
            "closer_consecutive_days": 0,
            "fatigue_score": 18,
        },
        "defense": {
            "fielding_pct": 0.984, "errors": 24, "drs": 12, "uzr": 8.5,
        },
        "record": {
            "w": 36, "l": 14, "pct": 0.720,
            "home_w": 20, "home_l": 6,
            "away_w": 16, "away_l": 8,
            "last5": [1,1,1,0,1], "last10": [1,1,0,1,1,1,0,1,1,1],
            "run_diff": 85,
        },
        "elo": 1628,
        "injuries": [],
        "schedule_fatigue": 2,
    },
    "TSG": {
        "batting": {
            "avg": 0.268, "obp": 0.330, "slg": 0.420, "ops": 0.750,
            "woba": 0.322, "wrc_plus": 97,
            "runs_per_game": 4.7, "hr_per_game": 0.9,
            "recent_7_ops": 0.762, "recent_14_ops": 0.755, "recent_30_ops": 0.752,
        },
        "bullpen": {
            "era": 3.62, "whip": 1.28, "fip": 3.75,
            "save_pct": 65.0, "hold_pct": 62.5,
            "last7_games": 13, "last7_pitches": 398,
            "closer_consecutive_days": 1,
            "fatigue_score": 52,
        },
        "defense": {
            "fielding_pct": 0.979, "errors": 33, "drs": 1, "uzr": 0.5,
        },
        "record": {
            "w": 24, "l": 26, "pct": 0.480,
            "home_w": 13, "home_l": 13,
            "away_w": 11, "away_l": 13,
            "last5": [0,1,0,1,1], "last10": [0,0,1,0,1,0,1,1,0,1],
            "run_diff": -12,
        },
        "elo": 1484,
        "injuries": ["吉力吉撈（腰傷，觀察中）"],
        "schedule_fatigue": 4,
    },
}

# ──────────────────────────────────────────────
# 味全龍 球隊數據（2026 復歸六隊）
# ──────────────────────────────────────────────
TEAM_STATS["WC"] = {
    "batting": {
        "avg": 0.275, "obp": 0.340, "slg": 0.435, "ops": 0.775,
        "woba": 0.335, "wrc_plus": 103,
        "runs_per_game": 5.0, "hr_per_game": 1.0,
        "recent_7_ops": 0.790, "recent_14_ops": 0.780, "recent_30_ops": 0.775,
    },
    "bullpen": {
        "era": 3.20, "whip": 1.20, "fip": 3.35,
        "save_pct": 70.0, "hold_pct": 65.0,
        "last7_games": 10, "last7_pitches": 310,
        "closer_consecutive_days": 0,
        "fatigue_score": 30,
    },
    "defense": {
        "fielding_pct": 0.981, "errors": 28, "drs": 5, "uzr": 3.0,
    },
    "record": {
        "w": 30, "l": 20, "pct": 0.600,
        "home_w": 16, "home_l": 10,
        "away_w": 14, "away_l": 10,
        "last5": [1,1,0,1,1], "last10": [1,0,1,1,0,1,1,0,1,1],
        "run_diff": 28,
    },
    "elo": 1545,
    "injuries": [],
    "schedule_fatigue": 2,
}

# ──────────────────────────────────────────────
# 本季對戰紀錄 {away: {home: [away_wins, home_wins]}}
# ──────────────────────────────────────────────
H2H = {
    "AEL": {"CT": [6,4], "FG": [5,5], "WL": [3,7], "TSG": [7,3], "WC": [4,6]},
    "CT":  {"AEL": [4,6], "FG": [4,6], "WL": [2,8], "TSG": [5,5], "WC": [5,5]},
    "FG":  {"AEL": [5,5], "CT": [6,4], "WL": [3,7], "TSG": [6,4], "WC": [4,6]},
    "WL":  {"AEL": [7,3], "CT": [8,2], "FG": [7,3], "TSG": [7,3], "WC": [6,4]},
    "TSG": {"AEL": [3,7], "CT": [5,5], "FG": [4,6], "WL": [3,7], "WC": [5,5]},
    "WC":  {"AEL": [6,4], "CT": [5,5], "FG": [6,4], "WL": [4,6], "TSG": [5,5]},
}

# ──────────────────────────────────────────────
# 今日賽程 (Demo — 三場六隊全出)
# ──────────────────────────────────────────────
def get_today_games(game_date: date = None) -> list:
    if game_date is None:
        game_date = date.today()
    ds = str(game_date)
    return [
        {
            "game_id": f"{ds}-FG-TSG",
            "date": ds, "time": "18:35",
            "away": "FG",  "away_name": "富邦悍將",
            "home": "TSG", "home_name": "台鋼雄鷹",
            "venue": "澄清湖棒球場",
            "away_pitcher": "富藍戈",
            "home_pitcher": "後勁",
            "status": "預定",
            "away_score": None, "home_score": None,
        },
        {
            "game_id": f"{ds}-FG-WL",
            "date": ds, "time": "18:35",
            "away": "FG",  "away_name": "富邦悍將",
            "home": "WL",  "home_name": "樂天桃猿",
            "venue": "桃園棒球場",
            "away_pitcher": "富藍戈",
            "home_pitcher": "威能帝",
            "status": "預定",
            "away_score": None, "home_score": None,
        },
        {
            "game_id": f"{ds}-WC-CT",
            "date": ds, "time": "18:35",
            "away": "WC",  "away_name": "味全龍",
            "home": "CT",  "home_name": "統一7-ELEVEn獅",
            "venue": "台南棒球場",
            "away_pitcher": "甘特",
            "home_pitcher": "布雷克",
            "status": "預定",
            "away_score": None, "home_score": None,
        },
    ]

def get_standings() -> list:
    rows = []
    for code, s in TEAM_STATS.items():
        r = s["record"]
        rows.append({
            "code": code,
            "name": TEAM_INFO[code]["name"],
            "short": TEAM_INFO[code]["short"],
            "w": r["w"], "l": r["l"], "pct": r["pct"],
            "run_diff": r["run_diff"],
            "last5": r["last5"],
            "elo": s["elo"],
            "streak": _streak(r["last10"]),
        })
    rows.sort(key=lambda x: -x["pct"])
    for i, row in enumerate(rows):
        row["rank"] = i + 1
    return rows

def _streak(results: list) -> str:
    if not results:
        return "-"
    current = results[-1]
    count = 0
    for r in reversed(results):
        if r == current:
            count += 1
        else:
            break
    return f"{'勝' if current == 1 else '敗'}{count}"

def get_top_pitchers(n: int = 10) -> list:
    pitchers = []
    for name, p in PITCHERS.items():
        if p.get("gs", 0) >= 5:
            pitchers.append({
                "name": name,
                "team": p["team"],
                "team_name": TEAM_INFO[p["team"]]["short"],
                "foreign": p["foreign"],
                "era": p["era"],
                "fip": p["fip"],
                "xfip": p["xfip"],
                "whip": p["whip"],
                "k9": p["k9"],
                "bb9": p["bb9"],
                "gs": p["gs"],
                "recent_5_era": p["recent_5_era"],
                "trend": _trend(p["era"], p["recent_5_era"]),
            })
    pitchers.sort(key=lambda x: x["era"])
    return pitchers[:n]

def _trend(season_era: float, recent_era: float) -> str:
    delta = season_era - recent_era
    if delta > 0.5:
        return "hot"
    if delta < -0.5:
        return "cold"
    return "neutral"
