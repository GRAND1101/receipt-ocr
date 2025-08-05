import re
import json
from difflib import get_close_matches

# ✅ 교정 사전 로드
try:
    with open("store_learning.json", "r", encoding="utf-8") as f:
        learning_dict = json.load(f)
except FileNotFoundError:
    learning_dict = {}

# ✅ 브랜드 매핑
brand_map = {
    "starbucks": "스타벅스",
    "starducks": "스타벅스",
    "paris": "파리바게뜨",
    "ediya": "이디야",
    "nonghyup": "농협",
    "emart": "이마트24",
    "emrt": "이마트24"
}

# ✅ 브랜드 후보 리스트
brand_candidates = [
    "스타벅스", "이마트24", "파리바게뜨", "이디야", "투썸플레이스", "빽다방", "할리스",
    "던킨", "버거킹", "맥도날드", "롯데리아", "KFC", "CU", "GS25", "세븐일레븐",
    "코스트코", "홈플러스", "롯데마트", "농협", "다이소", "올리브영", "ABC마트"
]

# ✅ 카테고리 매핑
category_map = {
    "스타벅스": "카페",
    "이디야": "카페",
    "투썸": "카페",
    "커피": "카페",
    "농협": "마트",
    "이마트": "마트",
    "CU": "편의점",
    "GS25": "편의점",
    "세븐일레븐": "편의점",
    "코스트코": "마트"
}

# ==============================
# 🔹 OCR 텍스트 전처리
# ==============================
def normalize_ocr_text(lines):
    merged = " ".join(lines)
    merged = re.sub(r'[^가-힣A-Za-z0-9]', '', merged)
    return merged

# ==============================
# 🔹 브랜드명 정규화 (학습 + 자동 보정)
# ==============================
def normalize_store_name(name):
    # ✅ 너무 긴 문자열 처리
    if len(name) > 25:
        name = name[:25]

    # ✅ 교정 사전 우선
    if name in learning_dict:
        return learning_dict[name]

    name_clean = name.replace(" ", "").lower()

    # ✅ brand_map 매핑
    for key, val in brand_map.items():
        if key in name_clean:
            return val

    # ✅ 키워드 기반
    if "마트" in name or "emart" in name:
        return "이마트24"
    if "star" in name or "스벅" in name:
        return "스타벅스"
    if "gs25" in name:
        return "GS25"
    if "cu" in name:
        return "CU"

    # ✅ Fuzzy Matching
    match = get_close_matches(name_clean, [b.lower() for b in brand_candidates], n=1, cutoff=0.3)
    if match:
        return brand_candidates[[b.lower() for b in brand_candidates].index(match[0])]

    return name  # 기본 반환

# ==============================
# 🔹 총금액 추출
# ==============================
def extract_total(lines):
    text = " ".join(lines)
    nums = re.findall(r'\d{1,3}(?:,\d{3})+|\d{4,}', text)
    if nums:
        return max(int(n.replace(",", "")) for n in nums if int(n.replace(",", "")) < 2000000)
    return None

# ==============================
# 🔹 날짜 추출
# ==============================
def extract_date(lines):
    text = " ".join(lines)
    match = re.search(r'(\d{4}[-./년]\d{1,2}[-./월]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)', text)
    if match:
        return match.group(1).replace(".", "-").replace("/", "-").replace("년", "-").replace("월", "-").replace("일", "")
    return None

# ==============================
# 🔹 메인 파서
# ==============================
def parse_receipt_text(lines, roi_brand=None):
    parsed = {}
    store_name_raw = None

    # ✅ 1. OCR 라인에서 "가맹점" 또는 "매장명" 찾기
    for line in lines:
        if "가맹점" in line:
            store_name_raw = line.split("가맹점")[-1].strip()
            break
        elif "매장명" in line:
            store_name_raw = line.split("매장명")[-1].strip()
            break

    # ✅ 2. ROI 브랜드 사용
    if not store_name_raw and roi_brand and len(roi_brand.strip()) >= 1:
        store_name_raw = roi_brand

    # ✅ 3. OCR 병합 텍스트 기반 (fallback)
    if not store_name_raw:
        merged_text = normalize_ocr_text(lines)
        store_name_raw = merged_text

    # ✅ 4. 브랜드명 정규화
    store_name = normalize_store_name(store_name_raw)

    parsed["가맹점"] = store_name if store_name else "미확인"
    parsed["총금액"] = extract_total(lines)
    parsed["날짜"] = extract_date(lines)
    parsed["카테고리"] = category_map.get(store_name, "기타")

    return parsed, lines, learning_dict
