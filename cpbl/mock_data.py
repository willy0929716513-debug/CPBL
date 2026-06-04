"""
NPB (日職) / KBO (韓職) 2026 賽季 Mock 資料 — 離線 Demo / Scraping 備用
"""
from datetime import date

# ──────────────────────────────────────────────
# 球隊基本資訊
# ──────────────────────────────────────────────
TEAM_INFO = {
    # ── NPB Central League ──────────────────────
    "GNT": {"name": "読売ジャイアンツ",         "short": "巨人",   "stadium": "東京ドーム",              "city": "東京",  "color": "#F97A1F", "league": "NPB"},
    "HNS": {"name": "阪神タイガース",           "short": "阪神",   "stadium": "甲子園球場",              "city": "西宮",  "color": "#FFE000", "league": "NPB"},
    "HRC": {"name": "広島東洋カープ",           "short": "広島",   "stadium": "マツダスタジアム",         "city": "広島",  "color": "#E82012", "league": "NPB"},
    "YDB": {"name": "横浜DeNAベイスターズ",     "short": "横浜",   "stadium": "横浜スタジアム",           "city": "横浜",  "color": "#004E9A", "league": "NPB"},
    "YKL": {"name": "東京ヤクルトスワローズ",   "short": "ヤクルト","stadium": "神宮球場",               "city": "東京",  "color": "#00A859", "league": "NPB"},
    "CND": {"name": "中日ドラゴンズ",           "short": "中日",   "stadium": "バンテリンドーム",         "city": "名古屋","color": "#003B87", "league": "NPB"},
    # ── NPB Pacific League ──────────────────────
    "SBH": {"name": "福岡ソフトバンクホークス", "short": "ソフトバンク","stadium": "みずほPayPayドーム",  "city": "福岡",  "color": "#FFD200", "league": "NPB"},
    "ORX": {"name": "オリックス・バファローズ", "short": "オリックス","stadium": "京セラドーム大阪",      "city": "大阪",  "color": "#004990", "league": "NPB"},
    "RKT": {"name": "東北楽天ゴールデンイーグルス","short": "楽天","stadium": "楽天モバイルパーク宮城","city": "仙台",  "color": "#860020", "league": "NPB"},
    "LTT": {"name": "千葉ロッテマリーンズ",     "short": "ロッテ", "stadium": "ZOZOマリンスタジアム",    "city": "千葉",  "color": "#000000", "league": "NPB"},
    "SEI": {"name": "埼玉西武ライオンズ",       "short": "西武",   "stadium": "ベルーナドーム",          "city": "所沢",  "color": "#00489C", "league": "NPB"},
    "HAM": {"name": "北海道日本ハムファイターズ","short": "日ハム", "stadium": "エスコンフィールド",      "city": "北広島","color": "#003B87", "league": "NPB"},
    # ── KBO ─────────────────────────────────────
    "SSL": {"name": "삼성 라이온즈",   "short": "삼성",   "stadium": "대구 라이온즈 파크",       "city": "대구",  "color": "#074CA1", "league": "KBO"},
    "LGT": {"name": "LG 트윈스",       "short": "LG",     "stadium": "잠실 야구장",             "city": "서울",  "color": "#C30452", "league": "KBO"},
    "DSB": {"name": "두산 베어스",     "short": "두산",   "stadium": "잠실 야구장",             "city": "서울",  "color": "#131230", "league": "KBO"},
    "KTW": {"name": "KT 위즈",         "short": "KT",     "stadium": "수원 KT 위즈 파크",       "city": "수원",  "color": "#231F20", "league": "KBO"},
    "SSG": {"name": "SSG 랜더스",      "short": "SSG",    "stadium": "인천 SSG 랜더스필드",     "city": "인천",  "color": "#CE0E2D", "league": "KBO"},
    "NCD": {"name": "NC 다이노스",     "short": "NC",     "stadium": "창원 NC 파크",            "city": "창원",  "color": "#071D3B", "league": "KBO"},
    "KIA": {"name": "KIA 타이거즈",    "short": "KIA",    "stadium": "광주 기아 챔피언스 필드", "city": "광주",  "color": "#EA0029", "league": "KBO"},
    "LTG": {"name": "롯데 자이언츠",   "short": "롯데",   "stadium": "사직 야구장",             "city": "부산",  "color": "#041E42", "league": "KBO"},
    "HWE": {"name": "한화 이글스",     "short": "한화",   "stadium": "대전 한화생명 이글스파크", "city": "대전",  "color": "#F37321", "league": "KBO"},
    "KWH": {"name": "키움 히어로즈",   "short": "키움",   "stadium": "고척 스카이돔",           "city": "서울",  "color": "#820024", "league": "KBO"},
}

# ──────────────────────────────────────────────
# 球場環境因子  (run_factor > 1.0 = 打者天堂)
# ──────────────────────────────────────────────
VENUE_FACTORS = {
    # NPB
    "東京ドーム":          {"run_factor": 0.97, "hr_factor": 1.05, "note": "室内穹頂，有利全壘打"},
    "甲子園球場":          {"run_factor": 0.94, "hr_factor": 0.88, "note": "外野大，投手有利"},
    "マツダスタジアム":    {"run_factor": 0.98, "hr_factor": 0.95, "note": "廣島天然草皮，均衡"},
    "横浜スタジアム":      {"run_factor": 1.08, "hr_factor": 1.15, "note": "球場小，打者天堂"},
    "神宮球場":            {"run_factor": 1.05, "hr_factor": 1.10, "note": "風場多變，全壘打多"},
    "バンテリンドーム":    {"run_factor": 0.93, "hr_factor": 0.87, "note": "室内穹頂，投手有利"},
    "みずほPayPayドーム":  {"run_factor": 0.96, "hr_factor": 0.98, "note": "室内穹頂，略偏投手"},
    "京セラドーム大阪":    {"run_factor": 0.95, "hr_factor": 0.92, "note": "室内穹頂，投手略有利"},
    "楽天モバイルパーク宮城": {"run_factor": 1.00, "hr_factor": 0.96, "note": "中性球場"},
    "ZOZOマリンスタジアム": {"run_factor": 1.04, "hr_factor": 1.02, "note": "海風影響，風向不定"},
    "ベルーナドーム":      {"run_factor": 1.02, "hr_factor": 1.00, "note": "室内穹頂，略偏打者"},
    "エスコンフィールド":  {"run_factor": 1.06, "hr_factor": 1.12, "note": "新球場，打者有利"},
    # KBO
    "대구 라이온즈 파크":   {"run_factor": 1.05, "hr_factor": 1.08, "note": "大邱打者友善球場"},
    "잠실 야구장":          {"run_factor": 1.00, "hr_factor": 0.97, "note": "蠶室，均衡球場"},
    "수원 KT 위즈 파크":    {"run_factor": 1.03, "hr_factor": 1.05, "note": "水原打者友善"},
    "인천 SSG 랜더스필드":  {"run_factor": 0.98, "hr_factor": 0.95, "note": "仁川，投手略有利"},
    "창원 NC 파크":         {"run_factor": 1.02, "hr_factor": 1.04, "note": "昌原，略偏打者"},
    "광주 기아 챔피언스 필드": {"run_factor": 1.07, "hr_factor": 1.12, "note": "光州打者天堂"},
    "사직 야구장":          {"run_factor": 0.96, "hr_factor": 0.93, "note": "釜山社稷，投手有利"},
    "대전 한화생명 이글스파크": {"run_factor": 1.01, "hr_factor": 1.03, "note": "大田，均衡"},
    "고척 스카이돔":        {"run_factor": 0.94, "hr_factor": 0.91, "note": "高尺室内球場，投手有利"},
}

# ──────────────────────────────────────────────
# 投手資料
# ERA_key: era / ip / so / bb / whip / fip
# ──────────────────────────────────────────────
PITCHERS: dict[str, dict] = {
    # ── GNT (読売巨人) ─────────────────────────
    "GNT_戸郷翔征": {"team": "GNT", "role": "SP", "era": 2.45, "ip": 80.0, "so": 88, "bb": 18, "whip": 0.98, "fip": 2.62},
    "GNT_山崎伊織":  {"team": "GNT", "role": "SP", "era": 2.88, "ip": 72.0, "so": 75, "bb": 22, "whip": 1.08, "fip": 2.95},
    "GNT_グリフィン": {"team": "GNT", "role": "SP", "era": 3.42, "ip": 65.0, "so": 62, "bb": 25, "whip": 1.18, "fip": 3.55},
    "GNT_井上温大":  {"team": "GNT", "role": "SP", "era": 3.85, "ip": 58.0, "so": 55, "bb": 20, "whip": 1.22, "fip": 3.72},
    # ── HNS (阪神) ─────────────────────────────
    "HNS_青柳晃洋":  {"team": "HNS", "role": "SP", "era": 2.68, "ip": 78.0, "so": 70, "bb": 24, "whip": 1.05, "fip": 2.88},
    "HNS_西勇輝":    {"team": "HNS", "role": "SP", "era": 3.12, "ip": 72.0, "so": 60, "bb": 20, "whip": 1.12, "fip": 3.25},
    "HNS_才木浩人":  {"team": "HNS", "role": "SP", "era": 3.55, "ip": 68.0, "so": 65, "bb": 22, "whip": 1.15, "fip": 3.45},
    "HNS_村上頌樹":  {"team": "HNS", "role": "SP", "era": 2.92, "ip": 75.0, "so": 78, "bb": 19, "whip": 1.02, "fip": 2.78},
    # ── HRC (広島) ─────────────────────────────
    "HRC_九里亜蓮":  {"team": "HRC", "role": "SP", "era": 3.20, "ip": 70.0, "so": 62, "bb": 22, "whip": 1.14, "fip": 3.35},
    "HRC_床田寛樹":  {"team": "HRC", "role": "SP", "era": 2.85, "ip": 75.0, "so": 72, "bb": 18, "whip": 1.05, "fip": 2.92},
    "HRC_大瀬良大地":{"team": "HRC", "role": "SP", "era": 3.50, "ip": 65.0, "so": 60, "bb": 24, "whip": 1.20, "fip": 3.58},
    "HRC_森下暢仁":  {"team": "HRC", "role": "SP", "era": 3.08, "ip": 72.0, "so": 68, "bb": 20, "whip": 1.10, "fip": 3.15},
    # ── YDB (横浜DeNA) ─────────────────────────
    "YDB_今永昇太":  {"team": "YDB", "role": "SP", "era": 2.25, "ip": 82.0, "so": 95, "bb": 15, "whip": 0.92, "fip": 2.38},
    "YDB_東克樹":    {"team": "YDB", "role": "SP", "era": 2.72, "ip": 75.0, "so": 80, "bb": 18, "whip": 1.00, "fip": 2.65},
    "YDB_バウアー":  {"team": "YDB", "role": "SP", "era": 3.35, "ip": 68.0, "so": 72, "bb": 28, "whip": 1.22, "fip": 3.45},
    "YDB_石田裕太郎":{"team": "YDB", "role": "SP", "era": 3.75, "ip": 60.0, "so": 55, "bb": 22, "whip": 1.28, "fip": 3.80},
    # ── YKL (ヤクルト) ─────────────────────────
    "YKL_小川泰弘":  {"team": "YKL", "role": "SP", "era": 3.42, "ip": 68.0, "so": 58, "bb": 22, "whip": 1.18, "fip": 3.52},
    "YKL_原樹理":    {"team": "YKL", "role": "SP", "era": 3.85, "ip": 62.0, "so": 52, "bb": 25, "whip": 1.30, "fip": 3.92},
    "YKL_サイスニード":{"team": "YKL", "role": "SP", "era": 3.28, "ip": 70.0, "so": 68, "bb": 20, "whip": 1.12, "fip": 3.35},
    "YKL_高橋奎二":  {"team": "YKL", "role": "SP", "era": 3.65, "ip": 64.0, "so": 60, "bb": 24, "whip": 1.22, "fip": 3.72},
    # ── CND (中日) ─────────────────────────────
    "CND_柳裕也":    {"team": "CND", "role": "SP", "era": 3.15, "ip": 72.0, "so": 65, "bb": 20, "whip": 1.10, "fip": 3.22},
    "CND_小笠原慎之介":{"team": "CND","role": "SP","era": 3.42, "ip": 68.0,"so": 68, "bb": 22,"whip": 1.15,"fip": 3.38},
    "CND_大野雄大":  {"team": "CND", "role": "SP", "era": 3.78, "ip": 62.0, "so": 58, "bb": 26, "whip": 1.28, "fip": 3.85},
    "CND_梅津晃大":  {"team": "CND", "role": "SP", "era": 3.55, "ip": 66.0, "so": 62, "bb": 22, "whip": 1.20, "fip": 3.62},
    # ── SBH (ソフトバンク) ─────────────────────
    "SBH_有原航平":  {"team": "SBH", "role": "SP", "era": 2.55, "ip": 82.0, "so": 85, "bb": 18, "whip": 0.98, "fip": 2.68},
    "SBH_和田毅":    {"team": "SBH", "role": "SP", "era": 3.05, "ip": 70.0, "so": 65, "bb": 20, "whip": 1.08, "fip": 3.12},
    "SBH_石川柊太":  {"team": "SBH", "role": "SP", "era": 3.38, "ip": 68.0, "so": 62, "bb": 22, "whip": 1.15, "fip": 3.45},
    "SBH_スチュワート":{"team": "SBH","role": "SP","era": 3.72, "ip": 62.0,"so": 60, "bb": 28,"whip": 1.30,"fip": 3.85},
    # ── ORX (オリックス) ───────────────────────
    "ORX_山本由伸":  {"team": "ORX", "role": "SP", "era": 1.85, "ip": 88.0, "so": 108, "bb": 12, "whip": 0.78, "fip": 1.92},
    "ORX_宮城大弥":  {"team": "ORX", "role": "SP", "era": 2.42, "ip": 80.0, "so": 82,  "bb": 18, "whip": 0.95, "fip": 2.55},
    "ORX_田嶋大樹":  {"team": "ORX", "role": "SP", "era": 3.18, "ip": 72.0, "so": 68,  "bb": 22, "whip": 1.12, "fip": 3.25},
    "ORX_曽谷龍平":  {"team": "ORX", "role": "SP", "era": 3.55, "ip": 65.0, "so": 62,  "bb": 20, "whip": 1.18, "fip": 3.62},
    # ── RKT (楽天) ─────────────────────────────
    "RKT_則本昂大":  {"team": "RKT", "role": "SP", "era": 3.22, "ip": 72.0, "so": 80, "bb": 25, "whip": 1.15, "fip": 3.28},
    "RKT_岸孝之":    {"team": "RKT", "role": "SP", "era": 3.48, "ip": 68.0, "so": 62, "bb": 18, "whip": 1.12, "fip": 3.42},
    "RKT_瀧中瞭太":  {"team": "RKT", "role": "SP", "era": 3.82, "ip": 62.0, "so": 55, "bb": 22, "whip": 1.28, "fip": 3.88},
    "RKT_早川隆久":  {"team": "RKT", "role": "SP", "era": 2.98, "ip": 75.0, "so": 78, "bb": 20, "whip": 1.05, "fip": 3.05},
    # ── LTT (ロッテ) ───────────────────────────
    "LTT_佐々木朗希":{"team": "LTT", "role": "SP", "era": 2.02, "ip": 85.0, "so": 110, "bb": 14, "whip": 0.85, "fip": 2.08},
    "LTT_石川歩":    {"team": "LTT", "role": "SP", "era": 3.35, "ip": 70.0, "so": 62,  "bb": 22, "whip": 1.18, "fip": 3.42},
    "LTT_種市篤暉":  {"team": "LTT", "role": "SP", "era": 3.65, "ip": 64.0, "so": 60,  "bb": 24, "whip": 1.25, "fip": 3.72},
    "LTT_美馬学":    {"team": "LTT", "role": "SP", "era": 3.92, "ip": 60.0, "so": 52,  "bb": 20, "whip": 1.30, "fip": 3.98},
    # ── SEI (西武) ─────────────────────────────
    "SEI_髙橋光成":  {"team": "SEI", "role": "SP", "era": 3.28, "ip": 72.0, "so": 68, "bb": 24, "whip": 1.18, "fip": 3.35},
    "SEI_今井達也":  {"team": "SEI", "role": "SP", "era": 3.58, "ip": 68.0, "so": 72, "bb": 28, "whip": 1.25, "fip": 3.62},
    "SEI_平良海馬":  {"team": "SEI", "role": "SP", "era": 3.42, "ip": 70.0, "so": 70, "bb": 22, "whip": 1.15, "fip": 3.48},
    "SEI_渡邉勇太朗":{"team": "SEI", "role": "SP", "era": 4.05, "ip": 58.0, "so": 52, "bb": 22, "whip": 1.35, "fip": 4.12},
    # ── HAM (日ハム) ───────────────────────────
    "HAM_上沢直之":  {"team": "HAM", "role": "SP", "era": 3.05, "ip": 75.0, "so": 70, "bb": 20, "whip": 1.08, "fip": 3.12},
    "HAM_加藤貴之":  {"team": "HAM", "role": "SP", "era": 3.42, "ip": 68.0, "so": 60, "bb": 18, "whip": 1.15, "fip": 3.38},
    "HAM_ポンセ":    {"team": "HAM", "role": "SP", "era": 3.78, "ip": 63.0, "so": 58, "bb": 28, "whip": 1.28, "fip": 3.88},
    "HAM_伊藤大海":  {"team": "HAM", "role": "SP", "era": 2.88, "ip": 78.0, "so": 82, "bb": 18, "whip": 1.02, "fip": 2.95},
    # ── SSL (삼성) ─────────────────────────────
    "SSL_에르난데스": {"team": "SSL", "role": "SP", "era": 3.22, "ip": 72.0, "so": 75, "bb": 22, "whip": 1.12, "fip": 3.35},
    "SSL_원태인":    {"team": "SSL", "role": "SP", "era": 2.98, "ip": 78.0, "so": 82, "bb": 18, "whip": 1.05, "fip": 3.08},
    "SSL_최채흥":    {"team": "SSL", "role": "SP", "era": 4.12, "ip": 62.0, "so": 58, "bb": 28, "whip": 1.42, "fip": 4.25},
    "SSL_레예스":    {"team": "SSL", "role": "SP", "era": 3.65, "ip": 68.0, "so": 65, "bb": 24, "whip": 1.25, "fip": 3.72},
    # ── LGT (LG트윈스) ─────────────────────────
    "LGT_임찬규":    {"team": "LGT", "role": "SP", "era": 3.45, "ip": 70.0, "so": 68, "bb": 22, "whip": 1.18, "fip": 3.52},
    "LGT_케이시켈리":{"team": "LGT", "role": "SP", "era": 3.12, "ip": 75.0, "so": 72, "bb": 18, "whip": 1.10, "fip": 3.22},
    "LGT_플럿코":    {"team": "LGT", "role": "SP", "era": 3.88, "ip": 65.0, "so": 62, "bb": 26, "whip": 1.32, "fip": 3.95},
    "LGT_이민호":    {"team": "LGT", "role": "SP", "era": 3.58, "ip": 68.0, "so": 65, "bb": 22, "whip": 1.22, "fip": 3.65},
    # ── DSB (두산) ─────────────────────────────
    "DSB_아리에타":  {"team": "DSB", "role": "SP", "era": 3.35, "ip": 72.0, "so": 72, "bb": 22, "whip": 1.15, "fip": 3.42},
    "DSB_곽빈":      {"team": "DSB", "role": "SP", "era": 4.05, "ip": 65.0, "so": 60, "bb": 28, "whip": 1.38, "fip": 4.15},
    "DSB_이영하":    {"team": "DSB", "role": "SP", "era": 3.72, "ip": 68.0, "so": 65, "bb": 24, "whip": 1.28, "fip": 3.78},
    "DSB_브랜든":    {"team": "DSB", "role": "SP", "era": 3.58, "ip": 70.0, "so": 68, "bb": 22, "whip": 1.20, "fip": 3.62},
    # ── KTW (KT위즈) ───────────────────────────
    "KTW_소형준":    {"team": "KTW", "role": "SP", "era": 3.48, "ip": 72.0, "so": 70, "bb": 22, "whip": 1.18, "fip": 3.55},
    "KTW_윌리엄스":  {"team": "KTW", "role": "SP", "era": 3.22, "ip": 75.0, "so": 75, "bb": 20, "whip": 1.12, "fip": 3.30},
    "KTW_배제성":    {"team": "KTW", "role": "SP", "era": 4.28, "ip": 60.0, "so": 55, "bb": 28, "whip": 1.45, "fip": 4.38},
    "KTW_엄상백":    {"team": "KTW", "role": "SP", "era": 3.78, "ip": 65.0, "so": 62, "bb": 25, "whip": 1.30, "fip": 3.85},
    # ── SSG (SSG랜더스) ────────────────────────
    "SSG_김광현":    {"team": "SSG", "role": "SP", "era": 2.88, "ip": 80.0, "so": 85, "bb": 18, "whip": 1.02, "fip": 2.95},
    "SSG_로맥":      {"team": "SSG", "role": "SP", "era": 3.55, "ip": 68.0, "so": 65, "bb": 24, "whip": 1.22, "fip": 3.62},
    "SSG_오원석":    {"team": "SSG", "role": "SP", "era": 4.02, "ip": 62.0, "so": 58, "bb": 26, "whip": 1.38, "fip": 4.12},
    "SSG_이태양":    {"team": "SSG", "role": "SP", "era": 3.78, "ip": 65.0, "so": 60, "bb": 22, "whip": 1.28, "fip": 3.85},
    # ── NCD (NC다이노스) ───────────────────────
    "NCD_루친스키":  {"team": "NCD", "role": "SP", "era": 3.18, "ip": 75.0, "so": 78, "bb": 20, "whip": 1.10, "fip": 3.25},
    "NCD_신민혁":    {"team": "NCD", "role": "SP", "era": 3.65, "ip": 68.0, "so": 65, "bb": 24, "whip": 1.25, "fip": 3.72},
    "NCD_김진욱":    {"team": "NCD", "role": "SP", "era": 4.15, "ip": 60.0, "so": 52, "bb": 28, "whip": 1.42, "fip": 4.25},
    "NCD_페디":      {"team": "NCD", "role": "SP", "era": 3.42, "ip": 72.0, "so": 72, "bb": 22, "whip": 1.15, "fip": 3.48},
    # ── KIA (KIA타이거즈) ──────────────────────
    "KIA_양현종":    {"team": "KIA", "role": "SP", "era": 3.05, "ip": 78.0, "so": 75, "bb": 18, "whip": 1.08, "fip": 3.12},
    "KIA_네일":      {"team": "KIA", "role": "SP", "era": 3.38, "ip": 72.0, "so": 72, "bb": 22, "whip": 1.15, "fip": 3.45},
    "KIA_윤영철":    {"team": "KIA", "role": "SP", "era": 3.72, "ip": 65.0, "so": 62, "bb": 24, "whip": 1.28, "fip": 3.78},
    "KIA_이의리":    {"team": "KIA", "role": "SP", "era": 3.55, "ip": 68.0, "so": 68, "bb": 20, "whip": 1.18, "fip": 3.58},
    # ── LTG (롯데) ─────────────────────────────
    "LTG_스트레일리":{"team": "LTG", "role": "SP", "era": 3.42, "ip": 72.0, "so": 72, "bb": 22, "whip": 1.15, "fip": 3.48},
    "LTG_박세웅":    {"team": "LTG", "role": "SP", "era": 3.85, "ip": 65.0, "so": 62, "bb": 26, "whip": 1.30, "fip": 3.92},
    "LTG_글레이버":  {"team": "LTG", "role": "SP", "era": 4.22, "ip": 60.0, "so": 58, "bb": 28, "whip": 1.42, "fip": 4.32},
    "LTG_안효준":    {"team": "LTG", "role": "SP", "era": 3.65, "ip": 68.0, "so": 65, "bb": 22, "whip": 1.22, "fip": 3.72},
    # ── HWE (한화) ─────────────────────────────
    "HWE_류현진":    {"team": "HWE", "role": "SP", "era": 3.12, "ip": 75.0, "so": 72, "bb": 18, "whip": 1.10, "fip": 3.18},
    "HWE_샤이너":    {"team": "HWE", "role": "SP", "era": 3.58, "ip": 68.0, "so": 65, "bb": 24, "whip": 1.22, "fip": 3.65},
    "HWE_문동주":    {"team": "HWE", "role": "SP", "era": 3.85, "ip": 65.0, "so": 62, "bb": 26, "whip": 1.32, "fip": 3.92},
    "HWE_이성훈":    {"team": "HWE", "role": "SP", "era": 4.15, "ip": 60.0, "so": 52, "bb": 28, "whip": 1.45, "fip": 4.25},
    # ── KWH (키움) ─────────────────────────────
    "KWH_안우진":    {"team": "KWH", "role": "SP", "era": 2.78, "ip": 80.0, "so": 88, "bb": 18, "whip": 1.00, "fip": 2.85},
    "KWH_헤이수스":  {"team": "KWH", "role": "SP", "era": 3.42, "ip": 70.0, "so": 68, "bb": 24, "whip": 1.18, "fip": 3.48},
    "KWH_하영민":    {"team": "KWH", "role": "SP", "era": 3.88, "ip": 65.0, "so": 62, "bb": 26, "whip": 1.32, "fip": 3.95},
    "KWH_김윤하":    {"team": "KWH", "role": "SP", "era": 4.02, "ip": 62.0, "so": 55, "bb": 24, "whip": 1.38, "fip": 4.12},
}

# ──────────────────────────────────────────────
# 球隊預設先發投手
# ──────────────────────────────────────────────
TEAM_DEFAULT_SP: dict[str, str] = {
    "GNT": "GNT_戸郷翔征",
    "HNS": "HNS_村上頌樹",
    "HRC": "HRC_床田寛樹",
    "YDB": "YDB_今永昇太",
    "YKL": "YKL_サイスニード",
    "CND": "CND_柳裕也",
    "SBH": "SBH_有原航平",
    "ORX": "ORX_山本由伸",
    "RKT": "RKT_早川隆久",
    "LTT": "LTT_佐々木朗希",
    "SEI": "SEI_髙橋光成",
    "HAM": "HAM_伊藤大海",
    "SSL": "SSL_원태인",
    "LGT": "LGT_케이시켈리",
    "DSB": "DSB_아리에타",
    "KTW": "KTW_윌리엄스",
    "SSG": "SSG_김광현",
    "NCD": "NCD_루친스키",
    "KIA": "KIA_양현종",
    "LTG": "LTG_스트레일리",
    "HWE": "HWE_류현진",
    "KWH": "KWH_안우진",
}

# ──────────────────────────────────────────────
# 打者資料  (OPS / wRC+ / wOBA / avg / hr / rbi / sb)
# ──────────────────────────────────────────────
BATTERS: dict[str, dict] = {
    # GNT
    "GNT_岡本和真":  {"team": "GNT", "ops": 0.982, "wrc_plus": 158, "woba": 0.412, "avg": 0.305, "hr": 28, "rbi": 88, "sb": 3},
    "GNT_坂本勇人":  {"team": "GNT", "ops": 0.798, "wrc_plus": 118, "woba": 0.342, "avg": 0.278, "hr": 12, "rbi": 52, "sb": 4},
    "GNT_丸佳浩":    {"team": "GNT", "ops": 0.842, "wrc_plus": 128, "woba": 0.358, "avg": 0.268, "hr": 18, "rbi": 62, "sb": 2},
    "GNT_ウォーカー":{"team": "GNT", "ops": 0.912, "wrc_plus": 142, "woba": 0.385, "avg": 0.282, "hr": 24, "rbi": 78, "sb": 1},
    # HNS
    "HNS_大山悠輔":  {"team": "HNS", "ops": 0.895, "wrc_plus": 138, "woba": 0.378, "avg": 0.285, "hr": 22, "rbi": 82, "sb": 2},
    "HNS_佐藤輝明":  {"team": "HNS", "ops": 0.872, "wrc_plus": 132, "woba": 0.365, "avg": 0.265, "hr": 25, "rbi": 72, "sb": 5},
    "HNS_近本光司":  {"team": "HNS", "ops": 0.782, "wrc_plus": 115, "woba": 0.335, "avg": 0.298, "hr": 8,  "rbi": 42, "sb": 22},
    "HNS_中野拓夢":  {"team": "HNS", "ops": 0.758, "wrc_plus": 108, "woba": 0.322, "avg": 0.292, "hr": 4,  "rbi": 38, "sb": 28},
    # HRC
    "HRC_秋山翔吾":  {"team": "HRC", "ops": 0.812, "wrc_plus": 120, "woba": 0.345, "avg": 0.295, "hr": 10, "rbi": 48, "sb": 12},
    "HRC_西川龍馬":  {"team": "HRC", "ops": 0.822, "wrc_plus": 122, "woba": 0.348, "avg": 0.288, "hr": 12, "rbi": 52, "sb": 8},
    "HRC_菊池涼介":  {"team": "HRC", "ops": 0.748, "wrc_plus": 106, "woba": 0.318, "avg": 0.278, "hr": 8,  "rbi": 42, "sb": 5},
    "HRC_坂倉将吾":  {"team": "HRC", "ops": 0.842, "wrc_plus": 128, "woba": 0.358, "avg": 0.295, "hr": 15, "rbi": 62, "sb": 1},
    # YDB
    "YDB_牧秀悟":    {"team": "YDB", "ops": 0.925, "wrc_plus": 148, "woba": 0.392, "avg": 0.295, "hr": 22, "rbi": 78, "sb": 2},
    "YDB_宮崎敏郎":  {"team": "YDB", "ops": 0.888, "wrc_plus": 135, "woba": 0.372, "avg": 0.312, "hr": 16, "rbi": 68, "sb": 1},
    "YDB_ソト":      {"team": "YDB", "ops": 0.958, "wrc_plus": 152, "woba": 0.402, "avg": 0.275, "hr": 32, "rbi": 88, "sb": 0},
    "YDB_佐野恵太":  {"team": "YDB", "ops": 0.838, "wrc_plus": 125, "woba": 0.355, "avg": 0.285, "hr": 14, "rbi": 58, "sb": 3},
    # YKL
    "YKL_村上宗隆":  {"team": "YKL", "ops": 1.018, "wrc_plus": 168, "woba": 0.428, "avg": 0.318, "hr": 38, "rbi": 102, "sb": 2},
    "YKL_山田哲人":  {"team": "YKL", "ops": 0.895, "wrc_plus": 138, "woba": 0.378, "avg": 0.282, "hr": 22, "rbi": 72, "sb": 15},
    "YKL_塩見泰隆":  {"team": "YKL", "ops": 0.845, "wrc_plus": 128, "woba": 0.358, "avg": 0.272, "hr": 18, "rbi": 58, "sb": 12},
    # CND
    "CND_岡林勇希":  {"team": "CND", "ops": 0.778, "wrc_plus": 112, "woba": 0.332, "avg": 0.298, "hr": 6,  "rbi": 42, "sb": 18},
    "CND_ビシエド":  {"team": "CND", "ops": 0.858, "wrc_plus": 130, "woba": 0.362, "avg": 0.285, "hr": 18, "rbi": 68, "sb": 0},
    "CND_木下拓哉":  {"team": "CND", "ops": 0.772, "wrc_plus": 110, "woba": 0.328, "avg": 0.272, "hr": 10, "rbi": 48, "sb": 2},
    # SBH
    "SBH_柳田悠岐":  {"team": "SBH", "ops": 0.945, "wrc_plus": 152, "woba": 0.398, "avg": 0.295, "hr": 26, "rbi": 85, "sb": 8},
    "SBH_近藤健介":  {"team": "SBH", "ops": 0.912, "wrc_plus": 142, "woba": 0.382, "avg": 0.325, "hr": 18, "rbi": 72, "sb": 5},
    "SBH_栗原陵矢":  {"team": "SBH", "ops": 0.858, "wrc_plus": 130, "woba": 0.362, "avg": 0.288, "hr": 20, "rbi": 68, "sb": 3},
    "SBH_今宮健太":  {"team": "SBH", "ops": 0.728, "wrc_plus": 100, "woba": 0.308, "avg": 0.265, "hr": 6,  "rbi": 38, "sb": 10},
    # ORX
    "ORX_吉田正尚":  {"team": "ORX", "ops": 0.978, "wrc_plus": 158, "woba": 0.412, "avg": 0.318, "hr": 24, "rbi": 88, "sb": 2},
    "ORX_頓宮裕真":  {"team": "ORX", "ops": 0.925, "wrc_plus": 148, "woba": 0.392, "avg": 0.308, "hr": 22, "rbi": 78, "sb": 1},
    "ORX_森友哉":    {"team": "ORX", "ops": 0.888, "wrc_plus": 135, "woba": 0.372, "avg": 0.298, "hr": 18, "rbi": 68, "sb": 2},
    # RKT
    "RKT_浅村栄斗":  {"team": "RKT", "ops": 0.905, "wrc_plus": 142, "woba": 0.382, "avg": 0.278, "hr": 28, "rbi": 85, "sb": 3},
    "RKT_島内宏明":  {"team": "RKT", "ops": 0.828, "wrc_plus": 122, "woba": 0.348, "avg": 0.282, "hr": 14, "rbi": 58, "sb": 8},
    "RKT_辰己涼介":  {"team": "RKT", "ops": 0.798, "wrc_plus": 115, "woba": 0.335, "avg": 0.275, "hr": 10, "rbi": 48, "sb": 20},
    # LTT
    "LTT_安田尚憲":  {"team": "LTT", "ops": 0.835, "wrc_plus": 122, "woba": 0.352, "avg": 0.278, "hr": 18, "rbi": 62, "sb": 4},
    "LTT_荻野貴司":  {"team": "LTT", "ops": 0.775, "wrc_plus": 110, "woba": 0.328, "avg": 0.285, "hr": 5,  "rbi": 38, "sb": 22},
    "LTT_マーティン":{"team": "LTT", "ops": 0.892, "wrc_plus": 138, "woba": 0.375, "avg": 0.268, "hr": 28, "rbi": 75, "sb": 2},
    # SEI
    "SEI_山川穂高":  {"team": "SEI", "ops": 0.965, "wrc_plus": 155, "woba": 0.408, "avg": 0.285, "hr": 35, "rbi": 95, "sb": 2},
    "SEI_外崎修汰":  {"team": "SEI", "ops": 0.818, "wrc_plus": 120, "woba": 0.345, "avg": 0.278, "hr": 14, "rbi": 55, "sb": 12},
    "SEI_源田壮亮":  {"team": "SEI", "ops": 0.738, "wrc_plus": 104, "woba": 0.315, "avg": 0.278, "hr": 4,  "rbi": 38, "sb": 18},
    # HAM
    "HAM_清宮幸太郎":{"team": "HAM", "ops": 0.878, "wrc_plus": 132, "woba": 0.368, "avg": 0.272, "hr": 22, "rbi": 68, "sb": 2},
    "HAM_近藤健介":  {"team": "HAM", "ops": 0.878, "wrc_plus": 132, "woba": 0.368, "avg": 0.305, "hr": 15, "rbi": 62, "sb": 4},
    "HAM_万波中正":  {"team": "HAM", "ops": 0.892, "wrc_plus": 138, "woba": 0.375, "avg": 0.268, "hr": 28, "rbi": 78, "sb": 6},
    # SSL
    "SSL_구자욱":    {"team": "SSL", "ops": 0.878, "wrc_plus": 132, "woba": 0.368, "avg": 0.295, "hr": 18, "rbi": 68, "sb": 8},
    "SSL_피렐라":    {"team": "SSL", "ops": 0.935, "wrc_plus": 148, "woba": 0.392, "avg": 0.285, "hr": 28, "rbi": 85, "sb": 2},
    "SSL_강민호":    {"team": "SSL", "ops": 0.798, "wrc_plus": 115, "woba": 0.335, "avg": 0.272, "hr": 12, "rbi": 52, "sb": 1},
    "SSL_이병헌":    {"team": "SSL", "ops": 0.812, "wrc_plus": 118, "woba": 0.342, "avg": 0.282, "hr": 10, "rbi": 48, "sb": 5},
    # LGT
    "LGT_오지환":    {"team": "LGT", "ops": 0.825, "wrc_plus": 122, "woba": 0.348, "avg": 0.285, "hr": 12, "rbi": 52, "sb": 5},
    "LGT_박해민":    {"team": "LGT", "ops": 0.778, "wrc_plus": 112, "woba": 0.332, "avg": 0.298, "hr": 5,  "rbi": 38, "sb": 25},
    "LGT_오스틴":    {"team": "LGT", "ops": 0.945, "wrc_plus": 152, "woba": 0.398, "avg": 0.288, "hr": 32, "rbi": 88, "sb": 2},
    "LGT_홍창기":    {"team": "LGT", "ops": 0.798, "wrc_plus": 115, "woba": 0.335, "avg": 0.305, "hr": 6,  "rbi": 42, "sb": 18},
    # DSB
    "DSB_양석환":    {"team": "DSB", "ops": 0.858, "wrc_plus": 130, "woba": 0.362, "avg": 0.272, "hr": 22, "rbi": 72, "sb": 2},
    "DSB_라모스":    {"team": "DSB", "ops": 0.912, "wrc_plus": 142, "woba": 0.382, "avg": 0.278, "hr": 28, "rbi": 82, "sb": 1},
    "DSB_허경민":    {"team": "DSB", "ops": 0.782, "wrc_plus": 112, "woba": 0.332, "avg": 0.285, "hr": 8,  "rbi": 45, "sb": 6},
    # KTW
    "KTW_강백호":    {"team": "KTW", "ops": 0.958, "wrc_plus": 155, "woba": 0.405, "avg": 0.295, "hr": 32, "rbi": 92, "sb": 5},
    "KTW_황재균":    {"team": "KTW", "ops": 0.838, "wrc_plus": 125, "woba": 0.355, "avg": 0.278, "hr": 18, "rbi": 65, "sb": 4},
    "KTW_멜로":      {"team": "KTW", "ops": 0.895, "wrc_plus": 138, "woba": 0.375, "avg": 0.272, "hr": 25, "rbi": 78, "sb": 1},
    # SSG
    "SSG_최정":      {"team": "SSG", "ops": 0.978, "wrc_plus": 158, "woba": 0.412, "avg": 0.285, "hr": 35, "rbi": 98, "sb": 2},
    "SSG_추신수":    {"team": "SSG", "ops": 0.895, "wrc_plus": 138, "woba": 0.375, "avg": 0.295, "hr": 18, "rbi": 72, "sb": 5},
    "SSG_노수광":    {"team": "SSG", "ops": 0.822, "wrc_plus": 120, "woba": 0.348, "avg": 0.275, "hr": 12, "rbi": 52, "sb": 8},
    # NCD
    "NCD_손아섭":    {"team": "NCD", "ops": 0.872, "wrc_plus": 132, "woba": 0.368, "avg": 0.305, "hr": 15, "rbi": 65, "sb": 6},
    "NCD_박건우":    {"team": "NCD", "ops": 0.845, "wrc_plus": 128, "woba": 0.358, "avg": 0.292, "hr": 16, "rbi": 62, "sb": 5},
    "NCD_알테어":    {"team": "NCD", "ops": 0.928, "wrc_plus": 148, "woba": 0.392, "avg": 0.278, "hr": 28, "rbi": 82, "sb": 2},
    # KIA
    "KIA_나성범":    {"team": "KIA", "ops": 0.898, "wrc_plus": 138, "woba": 0.378, "avg": 0.288, "hr": 22, "rbi": 75, "sb": 8},
    "KIA_소크라테스":{"team": "KIA", "ops": 0.942, "wrc_plus": 152, "woba": 0.398, "avg": 0.282, "hr": 30, "rbi": 88, "sb": 3},
    "KIA_최형우":    {"team": "KIA", "ops": 0.862, "wrc_plus": 130, "woba": 0.362, "avg": 0.295, "hr": 18, "rbi": 68, "sb": 2},
    # LTG
    "LTG_전준우":    {"team": "LTG", "ops": 0.858, "wrc_plus": 128, "woba": 0.360, "avg": 0.292, "hr": 16, "rbi": 65, "sb": 8},
    "LTG_한동희":    {"team": "LTG", "ops": 0.825, "wrc_plus": 122, "woba": 0.348, "avg": 0.282, "hr": 12, "rbi": 55, "sb": 5},
    "LTG_빅터레예스":{"team": "LTG", "ops": 0.912, "wrc_plus": 142, "woba": 0.382, "avg": 0.275, "hr": 26, "rbi": 78, "sb": 2},
    # HWE
    "HWE_채은성":    {"team": "HWE", "ops": 0.888, "wrc_plus": 135, "woba": 0.372, "avg": 0.298, "hr": 20, "rbi": 72, "sb": 5},
    "HWE_노시환":    {"team": "HWE", "ops": 0.942, "wrc_plus": 150, "woba": 0.398, "avg": 0.285, "hr": 30, "rbi": 88, "sb": 3},
    "HWE_페라자":    {"team": "HWE", "ops": 0.925, "wrc_plus": 148, "woba": 0.392, "avg": 0.275, "hr": 28, "rbi": 82, "sb": 2},
    # KWH
    "KWH_이정후":    {"team": "KWH", "ops": 0.958, "wrc_plus": 155, "woba": 0.405, "avg": 0.330, "hr": 18, "rbi": 75, "sb": 20},
    "KWH_김혜성":    {"team": "KWH", "ops": 0.825, "wrc_plus": 122, "woba": 0.348, "avg": 0.298, "hr": 10, "rbi": 52, "sb": 28},
    "KWH_로하스":    {"team": "KWH", "ops": 0.935, "wrc_plus": 150, "woba": 0.395, "avg": 0.278, "hr": 30, "rbi": 88, "sb": 2},
}

# ──────────────────────────────────────────────
# 牛棚資料 (主要後援投手)
# ──────────────────────────────────────────────
BULLPEN: dict[str, dict] = {
    # NPB
    "GNT_大勢":      {"team": "GNT", "role": "CL", "era": 1.85, "ip": 42.0, "so": 55, "bb": 10, "sv": 28, "whip": 0.78},
    "GNT_高橋優貴":  {"team": "GNT", "role": "SU", "era": 2.42, "ip": 48.0, "so": 52, "bb": 14, "sv": 5,  "whip": 0.98},
    "HNS_岩崎優":    {"team": "HNS", "role": "CL", "era": 1.92, "ip": 45.0, "so": 52, "bb": 12, "sv": 30, "whip": 0.82},
    "HNS_浜地真澄":  {"team": "HNS", "role": "SU", "era": 2.68, "ip": 48.0, "so": 48, "bb": 15, "sv": 4,  "whip": 1.05},
    "HRC_栗林良吏":  {"team": "HRC", "role": "CL", "era": 2.05, "ip": 44.0, "so": 50, "bb": 12, "sv": 25, "whip": 0.88},
    "HRC_矢崎拓也":  {"team": "HRC", "role": "SU", "era": 2.78, "ip": 46.0, "so": 45, "bb": 14, "sv": 3,  "whip": 1.08},
    "YDB_山崎康晃":  {"team": "YDB", "role": "CL", "era": 2.12, "ip": 44.0, "so": 50, "bb": 12, "sv": 28, "whip": 0.90},
    "YDB_入江大生":  {"team": "YDB", "role": "SU", "era": 2.55, "ip": 50.0, "so": 55, "bb": 14, "sv": 5,  "whip": 0.98},
    "YKL_マクガフ":  {"team": "YKL", "role": "CL", "era": 2.25, "ip": 42.0, "so": 52, "bb": 11, "sv": 25, "whip": 0.92},
    "YKL_清水昇":    {"team": "YKL", "role": "SU", "era": 2.88, "ip": 48.0, "so": 50, "bb": 16, "sv": 4,  "whip": 1.10},
    "CND_祖父江大輔":{"team": "CND", "role": "CL", "era": 2.35, "ip": 44.0, "so": 48, "bb": 13, "sv": 20, "whip": 0.95},
    "CND_又吉克樹":  {"team": "CND", "role": "SU", "era": 2.72, "ip": 48.0, "so": 46, "bb": 15, "sv": 5,  "whip": 1.05},
    "SBH_モイネロ":  {"team": "SBH", "role": "CL", "era": 1.75, "ip": 46.0, "so": 62, "bb": 10, "sv": 32, "whip": 0.72},
    "SBH_松本裕樹":  {"team": "SBH", "role": "SU", "era": 2.42, "ip": 50.0, "so": 55, "bb": 14, "sv": 5,  "whip": 0.95},
    "ORX_平野佳寿":  {"team": "ORX", "role": "CL", "era": 2.02, "ip": 44.0, "so": 50, "bb": 11, "sv": 28, "whip": 0.85},
    "ORX_比嘉幹貴":  {"team": "ORX", "role": "SU", "era": 2.58, "ip": 48.0, "so": 46, "bb": 14, "sv": 3,  "whip": 1.00},
    "RKT_松井裕樹":  {"team": "RKT", "role": "CL", "era": 2.15, "ip": 44.0, "so": 52, "bb": 13, "sv": 25, "whip": 0.90},
    "RKT_宋家豪":    {"team": "RKT", "role": "SU", "era": 2.88, "ip": 48.0, "so": 46, "bb": 16, "sv": 4,  "whip": 1.12},
    "LTT_益田直也":  {"team": "LTT", "role": "CL", "era": 2.32, "ip": 44.0, "so": 50, "bb": 12, "sv": 25, "whip": 0.92},
    "LTT_東妻勇輔":  {"team": "LTT", "role": "SU", "era": 2.75, "ip": 48.0, "so": 48, "bb": 16, "sv": 3,  "whip": 1.08},
    "SEI_平良海馬(RP)":{"team":"SEI","role": "CL", "era": 1.98, "ip": 46.0, "so": 58, "bb": 10, "sv": 22, "whip": 0.82},
    "SEI_宮川哲":    {"team": "SEI", "role": "SU", "era": 2.65, "ip": 48.0, "so": 50, "bb": 14, "sv": 4,  "whip": 1.02},
    "HAM_杉浦稔大":  {"team": "HAM", "role": "CL", "era": 2.28, "ip": 44.0, "so": 50, "bb": 13, "sv": 22, "whip": 0.93},
    "HAM_堀瑞輝":    {"team": "HAM", "role": "SU", "era": 2.85, "ip": 48.0, "so": 46, "bb": 16, "sv": 3,  "whip": 1.10},
    # KBO
    "SSL_오승환":    {"team": "SSL", "role": "CL", "era": 2.42, "ip": 42.0, "so": 48, "bb": 10, "sv": 25, "whip": 0.92},
    "SSL_최충연":    {"team": "SSL", "role": "SU", "era": 3.05, "ip": 45.0, "so": 42, "bb": 15, "sv": 4,  "whip": 1.18},
    "LGT_고우석":    {"team": "LGT", "role": "CL", "era": 2.15, "ip": 44.0, "so": 55, "bb": 11, "sv": 30, "whip": 0.88},
    "LGT_이정용":    {"team": "LGT", "role": "SU", "era": 2.75, "ip": 48.0, "so": 48, "bb": 14, "sv": 3,  "whip": 1.05},
    "DSB_김강률":    {"team": "DSB", "role": "CL", "era": 2.65, "ip": 42.0, "so": 46, "bb": 13, "sv": 22, "whip": 1.02},
    "DSB_이현승":    {"team": "DSB", "role": "SU", "era": 3.22, "ip": 45.0, "so": 42, "bb": 16, "sv": 3,  "whip": 1.22},
    "KTW_주권":      {"team": "KTW", "role": "CL", "era": 2.52, "ip": 44.0, "so": 50, "bb": 13, "sv": 24, "whip": 0.98},
    "KTW_박영현":    {"team": "KTW", "role": "SU", "era": 2.88, "ip": 48.0, "so": 50, "bb": 15, "sv": 4,  "whip": 1.10},
    "SSG_박종훈":    {"team": "SSG", "role": "CL", "era": 2.28, "ip": 44.0, "so": 50, "bb": 11, "sv": 26, "whip": 0.90},
    "SSG_서진용":    {"team": "SSG", "role": "SU", "era": 2.88, "ip": 48.0, "so": 46, "bb": 15, "sv": 3,  "whip": 1.10},
    "NCD_이재학":    {"team": "NCD", "role": "CL", "era": 2.72, "ip": 44.0, "so": 48, "bb": 14, "sv": 22, "whip": 1.05},
    "NCD_김진성":    {"team": "NCD", "role": "SU", "era": 3.12, "ip": 46.0, "so": 44, "bb": 16, "sv": 3,  "whip": 1.18},
    "KIA_정해영":    {"team": "KIA", "role": "CL", "era": 2.35, "ip": 44.0, "so": 52, "bb": 12, "sv": 28, "whip": 0.92},
    "KIA_한승혁":    {"team": "KIA", "role": "SU", "era": 2.98, "ip": 48.0, "so": 48, "bb": 16, "sv": 3,  "whip": 1.12},
    "LTG_구승민":    {"team": "LTG", "role": "CL", "era": 2.88, "ip": 44.0, "so": 46, "bb": 14, "sv": 20, "whip": 1.08},
    "LTG_최준용":    {"team": "LTG", "role": "SU", "era": 3.35, "ip": 46.0, "so": 42, "bb": 17, "sv": 2,  "whip": 1.25},
    "HWE_정우람":    {"team": "HWE", "role": "CL", "era": 2.62, "ip": 44.0, "so": 48, "bb": 13, "sv": 22, "whip": 1.02},
    "HWE_심수창":    {"team": "HWE", "role": "SU", "era": 3.18, "ip": 46.0, "so": 44, "bb": 16, "sv": 2,  "whip": 1.20},
    "KWH_조상우":    {"team": "KWH", "role": "CL", "era": 2.12, "ip": 44.0, "so": 55, "bb": 11, "sv": 28, "whip": 0.88},
    "KWH_이승호":    {"team": "KWH", "role": "SU", "era": 2.75, "ip": 48.0, "so": 48, "bb": 14, "sv": 3,  "whip": 1.05},
}

# ──────────────────────────────────────────────
# 球隊整體數據 (win / loss / runs_scored / runs_allowed / streak / elo)
# ──────────────────────────────────────────────
TEAM_STATS: dict[str, dict] = {
    # NPB Central
    "GNT": {"win": 38, "loss": 25, "pct": 0.603, "runs_scored": 195, "runs_allowed": 168, "streak": "W2", "elo": 1568},
    "HNS": {"win": 36, "loss": 27, "pct": 0.571, "runs_scored": 182, "runs_allowed": 172, "streak": "W1", "elo": 1548},
    "HRC": {"win": 34, "loss": 29, "pct": 0.540, "runs_scored": 175, "runs_allowed": 175, "streak": "L1", "elo": 1525},
    "YDB": {"win": 35, "loss": 28, "pct": 0.556, "runs_scored": 188, "runs_allowed": 178, "streak": "W3", "elo": 1538},
    "YKL": {"win": 28, "loss": 35, "pct": 0.444, "runs_scored": 172, "runs_allowed": 198, "streak": "L2", "elo": 1468},
    "CND": {"win": 25, "loss": 38, "pct": 0.397, "runs_scored": 158, "runs_allowed": 205, "streak": "L3", "elo": 1442},
    # NPB Pacific
    "SBH": {"win": 42, "loss": 21, "pct": 0.667, "runs_scored": 215, "runs_allowed": 162, "streak": "W4", "elo": 1605},
    "ORX": {"win": 40, "loss": 23, "pct": 0.635, "runs_scored": 205, "runs_allowed": 165, "streak": "W2", "elo": 1585},
    "RKT": {"win": 33, "loss": 30, "pct": 0.524, "runs_scored": 178, "runs_allowed": 182, "streak": "W1", "elo": 1512},
    "LTT": {"win": 32, "loss": 31, "pct": 0.508, "runs_scored": 175, "runs_allowed": 185, "streak": "L1", "elo": 1502},
    "SEI": {"win": 27, "loss": 36, "pct": 0.429, "runs_scored": 165, "runs_allowed": 202, "streak": "L2", "elo": 1458},
    "HAM": {"win": 30, "loss": 33, "pct": 0.476, "runs_scored": 172, "runs_allowed": 188, "streak": "W2", "elo": 1482},
    # KBO
    "LGT": {"win": 42, "loss": 20, "pct": 0.677, "runs_scored": 248, "runs_allowed": 185, "streak": "W5", "elo": 1615},
    "KIA": {"win": 38, "loss": 24, "pct": 0.613, "runs_scored": 235, "runs_allowed": 198, "streak": "W2", "elo": 1572},
    "SSG": {"win": 36, "loss": 26, "pct": 0.581, "runs_scored": 228, "runs_allowed": 202, "streak": "L1", "elo": 1548},
    "KTW": {"win": 34, "loss": 28, "pct": 0.548, "runs_scored": 222, "runs_allowed": 208, "streak": "W1", "elo": 1528},
    "SSL": {"win": 33, "loss": 29, "pct": 0.532, "runs_scored": 218, "runs_allowed": 210, "streak": "W2", "elo": 1518},
    "NCD": {"win": 30, "loss": 32, "pct": 0.484, "runs_scored": 212, "runs_allowed": 222, "streak": "L2", "elo": 1492},
    "DSB": {"win": 28, "loss": 34, "pct": 0.452, "runs_scored": 205, "runs_allowed": 228, "streak": "L1", "elo": 1468},
    "KWH": {"win": 26, "loss": 36, "pct": 0.419, "runs_scored": 198, "runs_allowed": 238, "streak": "L3", "elo": 1445},
    "HWE": {"win": 24, "loss": 38, "pct": 0.387, "runs_scored": 192, "runs_allowed": 248, "streak": "W1", "elo": 1422},
    "LTG": {"win": 22, "loss": 40, "pct": 0.355, "runs_scored": 185, "runs_allowed": 258, "streak": "L4", "elo": 1398},
}

# ──────────────────────────────────────────────
# 近期交手紀錄  H2H[home][away] = (主場勝, 主場敗)
# ──────────────────────────────────────────────
H2H: dict[str, dict[str, tuple[int, int]]] = {
    # NPB CL matchups
    "GNT": {"HNS": (3, 2), "HRC": (4, 1), "YDB": (2, 3), "YKL": (5, 0), "CND": (3, 2)},
    "HNS": {"GNT": (2, 3), "HRC": (3, 2), "YDB": (2, 3), "YKL": (4, 1), "CND": (3, 2)},
    "HRC": {"GNT": (1, 4), "HNS": (2, 3), "YDB": (3, 2), "YKL": (4, 1), "CND": (3, 2)},
    "YDB": {"GNT": (3, 2), "HNS": (3, 2), "HRC": (2, 3), "YKL": (4, 1), "CND": (3, 2)},
    "YKL": {"GNT": (0, 5), "HNS": (1, 4), "HRC": (1, 4), "YDB": (1, 4), "CND": (2, 3)},
    "CND": {"GNT": (2, 3), "HNS": (2, 3), "HRC": (2, 3), "YDB": (2, 3), "YKL": (3, 2)},
    # NPB PL matchups
    "SBH": {"ORX": (4, 1), "RKT": (4, 1), "LTT": (5, 0), "SEI": (4, 1), "HAM": (4, 1)},
    "ORX": {"SBH": (1, 4), "RKT": (4, 1), "LTT": (3, 2), "SEI": (4, 1), "HAM": (3, 2)},
    "RKT": {"SBH": (1, 4), "ORX": (1, 4), "LTT": (3, 2), "SEI": (3, 2), "HAM": (2, 3)},
    "LTT": {"SBH": (0, 5), "ORX": (2, 3), "RKT": (2, 3), "SEI": (3, 2), "HAM": (3, 2)},
    "SEI": {"SBH": (1, 4), "ORX": (1, 4), "RKT": (2, 3), "LTT": (2, 3), "HAM": (2, 3)},
    "HAM": {"SBH": (1, 4), "ORX": (2, 3), "RKT": (3, 2), "LTT": (2, 3), "SEI": (3, 2)},
    # KBO matchups
    "LGT": {"KIA": (4, 2), "SSG": (5, 1), "KTW": (4, 2), "SSL": (5, 1), "NCD": (5, 1), "DSB": (4, 2), "KWH": (5, 1), "HWE": (5, 1), "LTG": (5, 1)},
    "KIA": {"LGT": (2, 4), "SSG": (4, 2), "KTW": (4, 2), "SSL": (3, 3), "NCD": (4, 2), "DSB": (4, 2), "KWH": (4, 2), "HWE": (5, 1), "LTG": (5, 1)},
    "SSG": {"LGT": (1, 5), "KIA": (2, 4), "KTW": (3, 3), "SSL": (3, 3), "NCD": (4, 2), "DSB": (4, 2), "KWH": (4, 2), "HWE": (4, 2), "LTG": (4, 2)},
    "KTW": {"LGT": (2, 4), "KIA": (2, 4), "SSG": (3, 3), "SSL": (3, 3), "NCD": (3, 3), "DSB": (4, 2), "KWH": (4, 2), "HWE": (4, 2), "LTG": (4, 2)},
    "SSL": {"LGT": (1, 5), "KIA": (3, 3), "SSG": (3, 3), "KTW": (3, 3), "NCD": (3, 3), "DSB": (3, 3), "KWH": (4, 2), "HWE": (4, 2), "LTG": (4, 2)},
    "NCD": {"LGT": (1, 5), "KIA": (2, 4), "SSG": (2, 4), "KTW": (3, 3), "SSL": (3, 3), "DSB": (3, 3), "KWH": (3, 3), "HWE": (4, 2), "LTG": (4, 2)},
    "DSB": {"LGT": (2, 4), "KIA": (2, 4), "SSG": (2, 4), "KTW": (2, 4), "SSL": (3, 3), "NCD": (3, 3), "KWH": (3, 3), "HWE": (3, 3), "LTG": (4, 2)},
    "KWH": {"LGT": (1, 5), "KIA": (2, 4), "SSG": (2, 4), "KTW": (2, 4), "SSL": (2, 4), "NCD": (3, 3), "DSB": (3, 3), "HWE": (3, 3), "LTG": (4, 2)},
    "HWE": {"LGT": (1, 5), "KIA": (1, 5), "SSG": (2, 4), "KTW": (2, 4), "SSL": (2, 4), "NCD": (2, 4), "DSB": (3, 3), "KWH": (3, 3), "LTG": (3, 3)},
    "LTG": {"LGT": (1, 5), "KIA": (1, 5), "SSG": (2, 4), "KTW": (2, 4), "SSL": (2, 4), "NCD": (2, 4), "DSB": (2, 4), "KWH": (2, 4), "HWE": (3, 3)},
}


# ──────────────────────────────────────────────
# 工具函數
# ──────────────────────────────────────────────
def _streak(team: str) -> str:
    return TEAM_STATS.get(team, {}).get("streak", "?")


def _trend(team: str) -> str:
    s = _streak(team)
    if not s or len(s) < 2:
        return "→"
    kind, n = s[0], int(s[1:]) if s[1:].isdigit() else 1
    if kind == "W":
        return "↑↑" if n >= 3 else "↑"
    return "↓↓" if n >= 3 else "↓"


# ──────────────────────────────────────────────
# 今日賽程  (Demo 用假資料)
# ──────────────────────────────────────────────
_NPB_CL_GAMES = [
    ("YDB", "GNT"), ("HNS", "HRC"), ("YKL", "CND"),
    ("GNT", "YKL"), ("HRC", "YDB"), ("CND", "HNS"),
    ("YDB", "HNS"), ("GNT", "HRC"), ("YKL", "CND"),
]
_NPB_PL_GAMES = [
    ("ORX", "SBH"), ("LTT", "RKT"), ("SEI", "HAM"),
    ("SBH", "LTT"), ("RKT", "SEI"), ("HAM", "ORX"),
    ("SBH", "HAM"), ("ORX", "RKT"), ("LTT", "SEI"),
]
_KBO_GAMES = [
    ("KIA", "LGT"), ("KTW", "SSL"), ("NCD", "SSG"), ("HWE", "DSB"), ("LTG", "KWH"),
    ("LGT", "SSL"), ("SSG", "KTW"), ("KIA", "NCD"), ("DSB", "KWH"), ("KTW", "HWE"),
    ("LGT", "KIA"), ("SSL", "SSG"), ("NCD", "KTW"), ("KWH", "DSB"), ("HWE", "LTG"),
]


def get_today_games(game_date: str = None) -> list[dict]:
    """
    回傳今日 NPB + KBO 賽程列表 (Demo 用，依日期輪轉)
    每筆: {away, home, time, venue, league}
    """
    if game_date is None:
        game_date = str(date.today())
    try:
        d = date.fromisoformat(str(game_date))
        idx = d.toordinal() % max(len(_NPB_CL_GAMES), len(_KBO_GAMES))
    except ValueError:
        idx = 0

    cl_pair = _NPB_CL_GAMES[idx % len(_NPB_CL_GAMES)]
    pl_pair = _NPB_PL_GAMES[idx % len(_NPB_PL_GAMES)]
    kbo_pairs = [
        _KBO_GAMES[i % len(_KBO_GAMES)]
        for i in range(idx, idx + 5)
    ]

    games: list[dict] = []

    # NPB CL game
    away, home = cl_pair
    venue = TEAM_INFO.get(home, {}).get("stadium", "?")
    games.append({
        "away": away, "home": home,
        "time": "18:00", "venue": venue, "league": "NPB",
        "away_sp": TEAM_DEFAULT_SP.get(away),
        "home_sp": TEAM_DEFAULT_SP.get(home),
    })

    # NPB PL game
    away, home = pl_pair
    venue = TEAM_INFO.get(home, {}).get("stadium", "?")
    games.append({
        "away": away, "home": home,
        "time": "18:00", "venue": venue, "league": "NPB",
        "away_sp": TEAM_DEFAULT_SP.get(away),
        "home_sp": TEAM_DEFAULT_SP.get(home),
    })

    # KBO games
    for away, home in kbo_pairs:
        venue = TEAM_INFO.get(home, {}).get("stadium", "?")
        games.append({
            "away": away, "home": home,
            "time": "17:00", "venue": venue, "league": "KBO",
            "away_sp": TEAM_DEFAULT_SP.get(away),
            "home_sp": TEAM_DEFAULT_SP.get(home),
        })

    return games


# ──────────────────────────────────────────────
# 順位表
# ──────────────────────────────────────────────
def get_standings() -> dict[str, list[dict]]:
    """回傳 {league_division: [standings_rows]}"""
    def _row(code: str) -> dict:
        s = TEAM_STATS.get(code, {})
        info = TEAM_INFO.get(code, {})
        return {
            "code":   code,
            "name":   info.get("short", code),
            "win":    s.get("win", 0),
            "loss":   s.get("loss", 0),
            "pct":    s.get("pct", 0.0),
            "streak": s.get("streak", "?"),
            "elo":    s.get("elo", 1500),
        }

    npb_cl = sorted(["GNT", "HNS", "HRC", "YDB", "YKL", "CND"],
                    key=lambda c: TEAM_STATS[c]["pct"], reverse=True)
    npb_pl = sorted(["SBH", "ORX", "RKT", "LTT", "SEI", "HAM"],
                    key=lambda c: TEAM_STATS[c]["pct"], reverse=True)
    kbo    = sorted(["SSL", "LGT", "DSB", "KTW", "SSG", "NCD", "KIA", "LTG", "HWE", "KWH"],
                    key=lambda c: TEAM_STATS[c]["pct"], reverse=True)

    return {
        "NPB Central": [_row(c) for c in npb_cl],
        "NPB Pacific": [_row(c) for c in npb_pl],
        "KBO":         [_row(c) for c in kbo],
    }


# ──────────────────────────────────────────────
# 頂尖投手排名
# ──────────────────────────────────────────────
def get_top_pitchers(n: int = 10) -> list[dict]:
    """回傳 ERA 最低的前 n 名先發投手"""
    sp = [
        {"name": name, **data}
        for name, data in PITCHERS.items()
        if data.get("role") == "SP"
    ]
    sp.sort(key=lambda x: x["era"])
    return sp[:n]
