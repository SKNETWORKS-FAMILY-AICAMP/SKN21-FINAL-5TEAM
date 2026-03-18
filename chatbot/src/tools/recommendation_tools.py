import os
import re
import pandas as pd
from typing import List, Optional
from flashrank import Ranker, RerankRequest
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from ecommerce.backend.app.database import SessionLocal
from ecommerce.backend.app.models import User
from ecommerce.backend.app.router.products import crud as product_crud
from ecommerce.backend.app.router.products import schemas as product_schemas
from chatbot.src.tools.image_search_tools import (
    search_similar_products_multimodal,
    search_similar_products_from_text,
)

# Path to the sampled dataset
DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "processed",
    "fashion-1000-balanced",
    "sampled_styles.csv",
)
PRODUCTS_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "ecommerce",
    "scripts",
    "data",
    "products.csv",
)

# Global dataframe cache
_DF_CACHE = None
_RANKER: Ranker | None = None

_COLOR_TRANSLATIONS = {
    "검은색": "black",
    "검정": "black",
    "블랙": "black",
    "흰색": "white",
    "하얀색": "white",
    "화이트": "white",
    "파란색": "blue",
    "파랑": "blue",
    "블루": "blue",
    "네이비": "navy blue",
    "남색": "navy blue",
    "빨간색": "red",
    "빨강": "red",
    "레드": "red",
    "회색": "grey",
    "그레이": "grey",
    "회색빛": "grey",
    "핑크": "pink",
    "분홍색": "pink",
    "주황색": "orange",
    "오렌지": "orange",
    "갈색": "brown",
    "브라운": "brown",
    "초록색": "green",
    "그린": "green",
    "보라색": "purple",
    "퍼플": "purple",
    "노란색": "yellow",
    "옐로": "yellow",
}

_CATEGORY_TRANSLATIONS = {
    "백팩": ["backpack", "rucksack", "bag", "백팩", "등산 백팩"],
    "더플백": ["duffle bag", "duffel bag", "bag", "더플백"],
    "운동 가방": ["gym bag", "sports bag", "bag"],
    "여행용 백팩": ["travel backpack", "rucksack", "bag", "travel"],
    "운동화": ["sports shoes", "sneakers", "shoe", "스포츠화"],
    "스포츠화": ["sports shoes", "sneakers", "shoe", "스포츠화"],
    "구두": ["formal shoes", "dress shoes", "shoe", "정장화"],
    "캐주얼 신발": ["casual shoes", "shoe", "캐주얼화"],
    "셔츠": ["shirt", "셔츠"],
    "폴로 티셔츠": ["polo t-shirt", "polo shirt", "t-shirt", "티셔츠"],
    "티셔츠": ["t-shirt", "tee", "티셔츠"],
    "상의": ["top", "topwear", "상의"],
    "자켓": ["jacket", "자켓"],
    "조끼": ["waistcoat", "vest", "조끼"],
    "원피스": ["dress", "드레스", "원피스"],
    "청바지": ["jeans", "denim", "청바지"],
    "트레이닝 바지": ["track pants", "training pants", "트레이닝 바지"],
    "카프리 바지": ["capris", "capri pants", "카프리"],
    "쿠르티": ["kurtis", "kurti"],
    "쿠르타": ["kurtas", "kurta"],
    "비니": ["beanie", "skull cap", "cap", "비니", "캡"],
    "모자": ["cap", "hat", "모자", "캡"],
}

_TARGET_TERMS = [
    "백팩", "더플백", "운동 가방", "여행용 백팩", "운동화", "스포츠화",
    "구두", "캐주얼 신발", "셔츠", "폴로 티셔츠", "티셔츠", "상의", "자켓",
    "조끼", "원피스", "청바지", "트레이닝 바지", "카프리 바지", "쿠르티",
    "쿠르타", "비니", "모자",
]
_ACCESSORY_MISMATCH_TOKENS = {"브리프", "브래지어", "립", "하이라이터", "블러셔", "로브"}
_TARGET_MISMATCH_TERMS = {
    "백팩": ["힙색", "파우치", "모바일 파우치", "핸드백", "지갑", "넥타이"],
    "더플백": ["힙색", "파우치", "모바일 파우치", "핸드백", "백팩", "지갑"],
    "운동 가방": ["힙색", "파우치", "모바일 파우치", "핸드백", "넥타이"],
    "여행용 백팩": ["힙색", "파우치", "모바일 파우치", "핸드백", "넥타이"],
    "운동화": ["캡", "넥타이", "브리프", "브래지어", "지갑"],
    "스포츠화": ["캡", "넥타이", "브리프", "브래지어", "지갑"],
    "구두": ["캡", "넥타이", "브리프", "브래지어", "지갑"],
    "캐주얼 신발": ["캡", "넥타이", "브리프", "브래지어", "지갑"],
    "셔츠": ["목욕 가운", "베이비돌", "나이트 원피스", "캡", "넥타이"],
    "폴로 티셔츠": ["목욕 가운", "베이비돌", "나이트 원피스", "캡", "넥타이"],
    "티셔츠": ["목욕 가운", "베이비돌", "나이트 원피스", "캡", "넥타이"],
    "상의": ["목욕 가운", "베이비돌", "나이트 원피스", "캡", "넥타이"],
    "자켓": ["목욕 가운", "베이비돌", "나이트 원피스", "캡", "넥타이"],
    "조끼": ["목욕 가운", "베이비돌", "나이트 원피스", "캡", "넥타이"],
    "원피스": ["목욕 가운", "베이비돌", "나이트 원피스", "보정 속옷", "스타킹"],
    "청바지": ["스타킹", "레깅스", "라운지 팬츠", "라운지 쇼츠", "브래지어"],
    "트레이닝 바지": ["스타킹", "레깅스", "브래지어", "부츠", "캡"],
    "카프리 바지": ["스타킹", "레깅스", "브래지어", "부츠", "넥타이"],
    "쿠르티": ["살와르", "두파타", "나이트 원피스", "스타킹", "브래지어"],
    "쿠르타": ["살와르", "두파타", "나이트 원피스", "스타킹", "브래지어"],
    "비니": ["목욕 가운", "베이비돌", "브리프", "브래지어", "넥타이"],
    "모자": ["목욕 가운", "베이비돌", "브리프", "브래지어", "넥타이"],
}
_GENDER_HINTS = {
    "여성": "women",
    "여자": "women",
    "남성": "men",
    "남자": "men",
    "아동": "kids",
    "키즈": "kids",
    "남아": "boys",
    "여아": "girls",
}

_COLOR_FAMILIES = {
    "black": {"black"},
    "white": {"white"},
    "blue": {"blue", "navy"},
    "navy blue": {"navy", "blue"},
    "red": {"red"},
    "grey": {"grey", "gray"},
    "pink": {"pink"},
    "orange": {"orange"},
    "brown": {"brown", "tan"},
    "green": {"green"},
    "purple": {"purple"},
    "yellow": {"yellow"},
}

_USAGE_HINTS = {
    "여행용 백팩": {"travel", "rucksack"},
    "운동 가방": {"gym", "duffel", "duffle", "sports"},
    "캐주얼 신발": {"casual"},
    "정장 구두": {"formal"},
    "구두": {"formal"},
    "흰색 스포츠 운동화": {"sports"},
    "스포츠화": {"sports"},
    "운동화": {"sports"},
    "스포츠 자켓": {"sports", "track"},
    "트레이닝 바지": {"track", "training", "sports"},
}

_PRIMARY_CATEGORY_PHRASES = {
    "백팩": "backpack",
    "더플백": "duffle bag",
    "운동 가방": "gym bag",
    "여행용 백팩": "travel backpack",
    "운동화": "sports shoes",
    "스포츠화": "sports shoes",
    "구두": "formal shoes",
    "캐주얼 신발": "casual shoes",
    "셔츠": "shirt",
    "폴로 티셔츠": "polo t-shirt",
    "티셔츠": "t-shirt",
    "상의": "top",
    "자켓": "jacket",
    "조끼": "waistcoat",
    "원피스": "dress",
    "청바지": "jeans",
    "트레이닝 바지": "track pants",
    "카프리 바지": "capris",
    "쿠르티": "kurti",
    "쿠르타": "kurta",
    "비니": "beanie",
    "모자": "hat",
}


def _contains_korean(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text or ""))


def _extract_ascii_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9&+'-]*", text or "")


def _normalize_token(token: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", token.lower())


def _semantic_tokens(text: str) -> set[str]:
    return {
        _normalize_token(token)
        for token in re.findall(r"[A-Za-z0-9가-힣-]+", text or "")
        if _normalize_token(token)
    }


def _matches_semantic_phrase(tokens: set[str], phrase: str) -> bool:
    phrase_tokens = [
        _normalize_token(token)
        for token in re.findall(r"[A-Za-z0-9가-힣-]+", phrase or "")
        if _normalize_token(token)
    ]
    return bool(phrase_tokens) and all(token in tokens for token in phrase_tokens)


_CATEGORY_SIGNAL_RULES = {
    "백팩": {
        "strong": ["backpack", "rucksack"],
        "mismatch": ["messenger", "messanger", "waist pouch", "pouch", "laptop bag", "rain cover"],
    },
    "더플백": {
        "strong": ["duffle bag", "duffel bag", "duffle", "duffel"],
        "mismatch": ["waist pouch", "messenger", "laptop bag", "backpack"],
    },
    "운동 가방": {
        "strong": ["gym bag", "sports bag", "duffle bag", "duffel bag"],
        "mismatch": ["laptop bag", "messenger", "waist pouch"],
    },
    "여행용 백팩": {
        "strong": ["travel backpack", "backpack", "rucksack"],
        "mismatch": ["messenger", "laptop bag", "waist pouch"],
    },
    "구두": {
        "strong": ["formal shoes", "dress shoes"],
        "mismatch": ["casual shoes", "sports shoes", "sandals"],
    },
    "셔츠": {
        "strong": ["shirt"],
        "mismatch": ["tshirt", "tee", "cap", "hat"],
    },
    "폴로 티셔츠": {
        "strong": ["polo tshirt", "polo shirt"],
        "mismatch": ["dress", "cap", "hat", "kurta"],
    },
    "티셔츠": {
        "strong": ["tshirt", "tee"],
        "mismatch": ["formal shirt", "dress shirt", "cap", "hat"],
    },
    "원피스": {
        "strong": ["dress"],
        "mismatch": ["nightdress", "babydoll", "robe"],
    },
    "청바지": {
        "strong": ["jeans", "denim"],
        "mismatch": ["jeggings", "leggings", "lounge pant"],
    },
    "카프리 바지": {
        "strong": ["capris", "capri pants", "capri"],
        "mismatch": ["lounge pant", "lounge pants", "rain trousers", "leggings"],
    },
    "비니": {
        "strong": ["beanie", "skull cap", "skull caps"],
        "mismatch": ["cap", "hat"],
    },
    "모자": {
        "strong": ["cap", "hat"],
        "mismatch": ["beanie", "skull cap"],
    },
}


def _extract_query_colors(query: str) -> list[str]:
    colors: list[str] = []
    for korean, english in _COLOR_TRANSLATIONS.items():
        if korean in query and english not in colors:
            colors.append(english)
    return colors


def _find_target_terms(query: str) -> list[str]:
    found: list[str] = []
    lowered = (query or "").lower()
    for term in _TARGET_TERMS:
        if term in query:
            found.append(term)
            continue
        english_key = term.lower()
        if english_key in lowered:
            found.append(term)
    return found


def _translate_discovery_query(query: str) -> str:
    query_text = (query or "").strip()
    if not query_text:
        return ""

    pieces: list[str] = []
    pieces.extend(_extract_ascii_tokens(query_text))

    for korean, english in _COLOR_TRANSLATIONS.items():
        if korean in query_text:
            pieces.append(english)

    for term in _find_target_terms(query_text):
        pieces.extend(_CATEGORY_TRANSLATIONS.get(term, []))

    lowered = query_text.lower()
    if "여성" in query_text or "여자" in query_text or "women" in lowered:
        pieces.append("women")
    if "남성" in query_text or "남자" in query_text or "men" in lowered:
        pieces.append("men")
    if "여행" in query_text or "travel" in lowered:
        pieces.append("travel")
    if "운동" in query_text or "스포츠" in query_text or "sports" in lowered:
        pieces.append("sports")
    if "캐주얼" in query_text or "casual" in lowered:
        pieces.append("casual")
    if "정장" in query_text or "formal" in lowered:
        pieces.append("formal")
    if "줄무늬" in query_text or "스트라이프" in query_text:
        pieces.append("striped")
    if "체크" in query_text:
        pieces.append("checked")
    if "민소매" in query_text:
        pieces.append("sleeveless")
    if "프린트" in query_text or "printed" in lowered:
        pieces.append("printed")

    # Keep order but remove duplicates.
    deduped: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        normalized = piece.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(piece.strip())
    return " ".join(deduped)


def _build_focused_variant(query: str) -> str:
    query_text = (query or "").strip()
    if not query_text:
        return ""

    pieces: list[str] = []

    colors = _extract_query_colors(query_text)
    if colors:
        pieces.append(colors[0])

    target_terms = _find_target_terms(query_text)
    if target_terms:
        pieces.append(_PRIMARY_CATEGORY_PHRASES.get(target_terms[0], target_terms[0]))

    lowered = query_text.lower()
    if "여성" in query_text or "여자" in query_text or "women" in lowered:
        pieces.append("women")
    if "남성" in query_text or "남자" in query_text or "men" in lowered:
        pieces.append("men")
    if "여행" in query_text or "travel" in lowered:
        pieces.append("travel")
    if "운동" in query_text or "스포츠" in query_text or "sports" in lowered:
        pieces.append("sports")
    if "캐주얼" in query_text or "casual" in lowered:
        pieces.append("casual")
    if "정장" in query_text or "formal" in lowered:
        pieces.append("formal")
    if "줄무늬" in query_text or "스트라이프" in query_text:
        pieces.append("striped")
    if "체크" in query_text:
        pieces.append("checked")
    if "민소매" in query_text:
        pieces.append("sleeveless")
    if "프린트" in query_text or "printed" in lowered:
        pieces.append("printed")

    deduped: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        normalized = piece.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(piece.strip())
    return " ".join(deduped)


def _build_query_variants(query: str) -> list[str]:
    query_text = (query or "").strip()
    variants: list[str] = []
    if query_text:
        variants.append(query_text)

    focused = _build_focused_variant(query_text)
    if focused and focused not in variants:
        variants.append(focused)

    translated = _translate_discovery_query(query_text)
    if translated and translated not in variants:
        variants.append(translated)

    if translated and query_text:
        combined = f"{translated} {' '.join(_extract_ascii_tokens(query_text))}".strip()
        if combined and combined not in variants:
            variants.append(combined)

    return variants[:4]


def _score_discovery_adjustment(query_text: str | None, product: dict) -> float:
    query = (query_text or "").strip()
    if not query:
        return 0.0

    haystack = " ".join(
        [
            str(product.get("name") or ""),
            str(product.get("category") or ""),
            str(product.get("color") or ""),
        ]
    ).lower()
    normalized_haystack = _semantic_tokens(haystack)
    score = 0.0
    query_lower = query.lower()

    query_colors = _extract_query_colors(query)
    if query_colors:
        color_matched = False
        for query_color in query_colors:
            color_family = _COLOR_FAMILIES.get(query_color, {query_color})
            if any(color in haystack for color in color_family):
                score += 0.9
                color_matched = True
        if not color_matched:
            score -= 0.95

        known_color_tokens = {
            token
            for family in _COLOR_FAMILIES.values()
            for token in family
        }
        conflicting_colors = {
            token
            for token in known_color_tokens
            if token in haystack and all(token not in _COLOR_FAMILIES.get(color, {color}) for color in query_colors)
        }
        if conflicting_colors:
            score -= min(0.9, 0.3 * len(conflicting_colors))

    target_terms = _find_target_terms(query)
    matched_target = False
    for term in target_terms:
        synonyms = _CATEGORY_TRANSLATIONS.get(term, [])
        signal_rule = _CATEGORY_SIGNAL_RULES.get(term, {})
        strong_phrases = signal_rule.get("strong", [])
        mismatch_phrases = signal_rule.get("mismatch", [])
        if any(token.lower() in haystack for token in synonyms):
            score += 1.15
            matched_target = True
        for mismatch in _TARGET_MISMATCH_TERMS.get(term, []):
            if mismatch.lower() in haystack:
                score -= 1.0

        normalized_synonyms = {_normalize_token(token) for token in synonyms if _normalize_token(token)}
        if normalized_synonyms & normalized_haystack:
            score += 0.45
            matched_target = True

        strong_matches = sum(
            1 for phrase in strong_phrases if _matches_semantic_phrase(normalized_haystack, phrase)
        )
        if strong_matches:
            score += min(1.6, 0.85 + 0.35 * (strong_matches - 1))
            matched_target = True

        mismatch_hits = sum(
            1 for phrase in mismatch_phrases if _matches_semantic_phrase(normalized_haystack, phrase)
        )
        if mismatch_hits:
            score -= min(1.8, 0.75 * mismatch_hits)

        usage_hints = _USAGE_HINTS.get(term, set())
        if usage_hints and any(hint in haystack for hint in usage_hints):
            score += 0.45

    if "백팩" in query:
        if "messenger" in haystack or "messanger" in haystack or "laptop bag" in haystack:
            score -= 1.15
        if "rain cover" in haystack:
            score -= 1.0
    if "운동 가방" in query:
        if "gym bag" in haystack or "duffel bag" in haystack or "duffle bag" in haystack:
            score += 0.8
        if "laptop bag" in haystack or "messenger bag" in haystack:
            score -= 1.2
    if "여행용 백팩" in query:
        if "rucksack" in haystack or "travel" in haystack:
            score += 0.75
        if "backpack" in haystack or "등산 백팩" in haystack:
            score += 0.55
        if "messenger bag" in haystack or "satchel" in haystack:
            score -= 1.35
    if "캐주얼 신발" in query:
        if "casual shoes" in haystack:
            score += 0.8
        if "formal shoes" in haystack or "sports shoes" in haystack:
            score -= 0.7
    if "정장" in query or "구두" in query:
        if "formal shoes" in haystack:
            score += 0.85
        if "casual shoes" in haystack or "sports shoes" in haystack:
            score -= 0.75
    if "스포츠" in query or "운동화" in query or "스포츠화" in query:
        if "sports shoes" in haystack or "track" in haystack:
            score += 0.8
        if "formal shoes" in haystack:
            score -= 0.8
        if len(conflicting_colors) >= 1:
            score -= 0.35
    if "티셔츠" in query:
        if "t-shirt" in haystack or "tee" in haystack:
            score += 0.45
        if "shirt" in haystack and "t-shirt" not in haystack:
            score -= 0.55
        if "pack of" in haystack:
            score -= 0.5
        if "kidswear" in haystack:
            score -= 0.6
    if "폴로" in query:
        if "polo" in haystack:
            score += 1.35
        elif any(token in haystack for token in ["tunic", "kurti", "kurta"]):
            score -= 1.1
    if "비니" in query or "모자" in query:
        if "beanie" in haystack or "skull caps" in haystack:
            score += 0.8
        if "caps" in haystack and "skull caps" not in haystack:
            score -= 0.45
    if "카프리 바지" in query:
        if "capris" in haystack or "capri" in haystack:
            score += 1.1
        if any(token in haystack for token in ["lounge pant", "lounge pants", "lounge shorts", "rain trousers"]):
            score -= 1.25
    if "쿠르티" in query:
        if "kurtis" in haystack or "kurti" in haystack:
            score += 0.75
        if "kurta sets" in haystack or "dupatta" in haystack:
            score -= 0.55
    if "쿠르타" in query:
        if "kurtas" in haystack or "kurta" in haystack:
            score += 0.75
        if "kurta sets" in haystack:
            score -= 0.3

    if matched_target and any(token in haystack for token in _ACCESSORY_MISMATCH_TOKENS):
        score -= 0.6

    for token in _extract_ascii_tokens(query):
        if token.lower() in haystack:
            score += 0.5

    translated_query = _translate_discovery_query(query)
    translated_tokens = _semantic_tokens(translated_query)
    overlap = translated_tokens & normalized_haystack
    score += min(1.5, len(overlap) * 0.18)

    if "줄무늬" in query or "striped" in query_lower:
        if "striped" in haystack:
            score += 0.45
        if "checked" in haystack:
            score -= 0.25
    if "프린트" in query or "printed" in query_lower:
        if "printed" in haystack:
            score += 0.45
        if "sweatshirt" in haystack or "top" in haystack:
            score -= 0.4
    if "체크" in query or "checked" in query_lower:
        if "checked" in haystack:
            score += 0.45
        if "striped" in haystack:
            score -= 0.2
    if "민소매" in query or "sleeveless" in query_lower:
        if "sleeveless" in haystack:
            score += 0.7
        if "nightdress" in haystack:
            score -= 0.45
        if "camisole" in haystack and ("원피스" in query or "dress" in query_lower):
            score -= 0.95
    if "청바지" in query or "jeans" in query_lower:
        if "jeans" in haystack or "denim" in haystack:
            score += 0.35
        if "jeggings" in haystack:
            score -= 0.25
    if "원피스" in query or "dress" in query_lower:
        if "dress" in haystack:
            score += 0.75
        if "nightdress" in haystack or "babydoll" in haystack:
            score -= 0.6
        if "camisole" in haystack:
            score -= 0.75
    if "백팩" in query:
        if "waist pouch" in haystack or "hip" in haystack or "messanger" in haystack:
            score -= 0.8

    gender_hint = None
    for key, value in _GENDER_HINTS.items():
        if key in query:
            gender_hint = value
            break
    if gender_hint:
        if gender_hint in haystack:
            score += 0.25
        elif any(other in haystack for other in ["women", "men", "boys", "girls", "kids"]):
            score -= 0.12
    elif any(other in haystack for other in ["boys", "girls", "kids"]):
        score -= 0.5
    elif any(other in haystack for other in ["women", "men", "unisex"]):
        score += 0.12

    return score


def _get_ranker() -> Ranker | None:
    global _RANKER
    if _RANKER is not None:
        return _RANKER

    model_name = "ms-marco-MiniLM-L-12-v2"
    cache_dir = os.getenv("FLASHRANK_CACHE_DIR")
    try:
        kwargs = {"model_name": model_name}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        _RANKER = Ranker(**kwargs)
        return _RANKER
    except Exception as e:
        print(f"Reranker unavailable, fallback to CLIP order: {e}")
        _RANKER = None
        return None


def _get_dataframe() -> pd.DataFrame:
    global _DF_CACHE
    if _DF_CACHE is None:
        try:
            _DF_CACHE = pd.read_csv(DATA_PATH)
        except Exception as e:
            print(f"Failed to load dataset from {DATA_PATH}: {e}")
            _DF_CACHE = pd.DataFrame()  # Load empty df on failure
    return _DF_CACHE


@tool
def recommend_clothes(
    category: str,
    color: Optional[str] = None,
    usage: Optional[str] = None,
    season: Optional[str] = None,
    limit: int = 3,
    user_id: int = 1,
) -> dict:
    """
    사용자의 요청(카테고리, 색상, 용도 등)에 맞는 옷을 추천합니다.
    챗봇이 의류나 패션 아이템을 추천할 때 사용합니다.

    Args:
        category: 의류 종류 (필수, 예: "Topwear", "Bottomwear", "Dress", "Skirt", "Innerwear" 등. 사용자의 발화를 기반으로 영어 분류명으로 추론하세요)
        color: 색상 (선택사항, 예: "Black", "Red", "Blue" 등 영어 색상명)
        usage: 용도 (선택사항, 예: "Casual", "Formal", "Sports", "Party" 등 영어 용도명)
        season: 계절 (선택사항, 예: "Summer", "Winter", "Fall", "Spring")
        limit: 추천할 상품 최대 개수 (기본값 3)
        user_id: 사용자 ID (기본값 1, DB에서 성별 조회용)
    """
    db = SessionLocal()
    gender = None
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            gender = getattr(user, "gender", None)
    except Exception as e:
        print(f"Error fetching user gender: {e}")
    finally:
        db.close()

    df = _get_dataframe()
    if df.empty:
        return {"error": "상품 데이터를 로드할 수 없습니다."}

    # 1. Base filter
    filtered = df[df["masterCategory"] == "Apparel"].copy()

    # 성별 필터링 (DB에서 가져온 성별 사용)
    if gender:
        g_map = {
            "남성": "Men",
            "남자": "Men",
            "M": "Men",
            "여성": "Women",
            "여자": "Women",
            "F": "Women",
            "공용": "Unisex",
        }
        target_gender = g_map.get(gender, gender)
        filtered = filtered[
            filtered["gender"].str.contains(target_gender, case=False, na=False)
        ]

    # 2. Category matching
    if category:
        mask = filtered["subCategory"].str.contains(
            category, case=False, na=False
        ) | filtered["articleType"].str.contains(category, case=False, na=False)
        filtered = filtered[mask]

    # 3. Category fallback guard
    if len(filtered) == 0:
        return {
            "message": f"'{category}' 종류에 해당하는 옷을 찾지 못했습니다. 다른 종류의 옷을 추천해드릴까요?"
        }

    # 계절 필터링
    if season:
        filtered = filtered[
            filtered["season"].str.contains(season, case=False, na=False)
        ]

    # 컬러 필터링
    if color:
        filtered = filtered[
            filtered["baseColour"].str.contains(color, case=False, na=False)
        ]

    # 용도 필터링
    if usage:
        filtered = filtered[filtered["usage"].str.contains(usage, case=False, na=False)]

    # 필터링 후 아무 상품도 남아있지 않은 경우
    if len(filtered) == 0:
        return {
            "message": "제시하신 조건(색상, 계절, 용도 등)에 완벽히 일치하는 옷을 찾지 못했습니다. 조건을 조금 바꿔서 다시 검색해보시는 건 어떨까요?"
        }

    # 4. Random Sampling
    sample_size = min(len(filtered), limit)
    sampled = filtered.sample(n=sample_size)

    results = []
    for _, row in sampled.iterrows():
        results.append(
            {
                "id": int(row["id"]),
                "name": str(row["productDisplayName"]),
                "price": 30000,  # Mock price because price isn't in styles.csv metadata
                "category": f"{row['masterCategory']} > {row['subCategory']} > {row['articleType']}",
                "color": str(row["baseColour"]),
                "season": str(row["season"]),
                "usage": str(row["usage"]),
            }
        )

    return {
        "success": True,
        "message": f"조건에 맞는 옷 {len(results)}개를 추천해드릴게요!",
        "ui_action": "show_product_list",
        "ui_template": "product_list",
        "ui_data": results,
        "products": results,
    }

def _build_product_payloads(product_ids: List[int]) -> List[dict]:
    db = SessionLocal()
    try:
        payloads: List[dict] = []
        for product_id in product_ids:
            product = product_crud.get_product_by_id(db, product_id)
            if not product:
                continue
            category = getattr(product.category, "name", None)
            color = None
            for opt in getattr(product, "options", []):
                if opt.color:
                    color = opt.color
                    break
            image_url = None
            try:
                images = product_crud.get_product_images(
                    db, product_schemas.ProductType.NEW, product.id
                )
                if images:
                    primary_image = next((img for img in images if img.is_primary), images[0])
                    image_url = primary_image.image_url
            except Exception as img_err:
                print(f"Failed to load images for product {product.id}: {img_err}")
            payloads.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "price": float(product.price),
                    "category": category,
                    "color": color,
                    "season": None,
                    "image_url": image_url or f"/products/{product.id}.jpg",
                }
            )
        return payloads
    finally:
        db.close()


def _keyword_search_products(query_text: str, top_k: int) -> tuple[List[int], List[dict]]:
    db = SessionLocal()
    try:
        limit = max(1, min(top_k, 20))
        products = product_crud.get_products(
            db,
            keyword=query_text,
            is_active=True,
            skip=0,
            limit=limit,
        )
        product_ids = [p.id for p in products if getattr(p, "id", None) is not None]
        payloads = _build_product_payloads(product_ids)
        return product_ids, payloads
    finally:
        db.close()


def _keyword_fallback_products(query_text: str, top_k: int) -> tuple[List[int], List[dict]]:
    product_ids, payloads = _keyword_search_products(query_text, top_k)
    if product_ids:
        return product_ids, payloads

    db = SessionLocal()
    try:
        limit = max(1, min(top_k, 20))
        products = product_crud.get_products(
            db,
            is_active=True,
            skip=0,
            limit=limit,
        )
        fallback_ids = [p.id for p in products if getattr(p, "id", None) is not None]
        fallback_payloads = _build_product_payloads(fallback_ids)
        return fallback_ids, fallback_payloads
    finally:
        db.close()


def _rerank_products_by_query(
    query_text: str | None,
    product_ids: List[int],
    products: List[dict],
) -> tuple[List[int], List[dict]]:
    query = (query_text or "").strip()
    if not query:
        return product_ids, products

    ranker = _get_ranker()
    if ranker is None:
        return product_ids, products

    try:
        passages = []
        for p in products:
            pid = p.get("id")
            if pid is None:
                continue
            text = " ".join(
                [
                    str(p.get("name") or ""),
                    str(p.get("category") or ""),
                    str(p.get("color") or ""),
                    str(p.get("season") or ""),
                ]
            ).strip()
            passages.append({"id": str(pid), "text": text})

        if not passages:
            return product_ids, products

        rerank_results = ranker.rerank(RerankRequest(query=query, passages=passages))
        reranked_ids = [int(item["id"]) for item in rerank_results]
        by_id = {int(p["id"]): p for p in products if p.get("id") is not None}

        rank_index = {pid: index for index, pid in enumerate(reranked_ids)}
        rescored = []
        for pid, product in by_id.items():
            base_score = -float(rank_index.get(pid, len(reranked_ids) + 1))
            adjustment = _score_discovery_adjustment(query, product)
            rescored.append((base_score + adjustment, pid))

        rescored.sort(key=lambda item: item[0], reverse=True)
        reordered_ids = [pid for _, pid in rescored]
        reordered_products = [by_id[pid] for pid in reordered_ids if pid in by_id]
        return reordered_ids, reordered_products
    except Exception as e:
        print(f"Reranking fallback to CLIP order: {e}")
        return product_ids, products


def _merge_product_ids(candidates: list[list[int]], top_k: int) -> list[int]:
    scores: dict[int, float] = {}
    for candidate_ids in candidates:
        for rank, product_id in enumerate(candidate_ids, start=1):
            scores[product_id] = scores.get(product_id, 0.0) + (1.0 / rank)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [product_id for product_id, _ in ranked[: max(top_k * 3, top_k)]]


def _keyword_candidate_products(query_text: str, top_k: int) -> tuple[List[int], List[dict]]:
    translated_query = _translate_discovery_query(query_text) or query_text
    return _keyword_fallback_products(translated_query, top_k)


def _rescue_candidate_products(query_text: str, top_k: int) -> tuple[List[int], List[dict]]:
    focused_query = _build_focused_variant(query_text)
    if not focused_query:
        return [], []

    rescue_ids, rescue_products = _keyword_search_products(focused_query, max(top_k, 6))
    if not rescue_products:
        return [], []

    rescored: list[tuple[float, int, dict]] = []
    for product in rescue_products:
        pid = product.get("id")
        if pid is None:
            continue
        score = _score_discovery_adjustment(query_text, product)
        rescored.append((score, int(pid), product))

    rescored.sort(key=lambda item: item[0], reverse=True)
    kept = [
        (pid, product)
        for score, pid, product in rescored
        if score >= 1.2
    ][: min(2, top_k)]

    return [pid for pid, _ in kept], [product for _, product in kept]


@tool
def search_by_image(
    image_bytes: bytes,
    top_k: int = 5,
    query_text: Optional[str] = None,
    search_mode: str = "similar",
) -> dict:
    """
    CLIP/Qdrant를 활용해 업로드된 이미지와 유사한 상품을 추천합니다.
    """

    if not isinstance(image_bytes, (bytes, bytearray)):
        return {"error": "이미지 바이트 데이터를 전달해주세요."}

    try:
        product_ids = search_similar_products_multimodal(
            image_bytes=bytes(image_bytes),
            text=query_text,
            top_k=top_k,
            search_mode=search_mode,
        )
        print("CLIP SEARCH RESULT:", product_ids)
        products = _build_product_payloads(product_ids)
        product_ids, products = _rerank_products_by_query(query_text, product_ids, products)
        return {
            "ui_action": "show_product_list",
            "product_ids": product_ids,
            "products": products,
        }
    except Exception as e:
        print("IMAGE SEARCH ERROR:", e)
        return {"error": f"이미지 검색 실패: {str(e)}"}


@tool
def search_by_text_clip(
    query: str,
    top_k: int = 5,
    search_mode: str = "similar",
) -> dict:
    """
    CLIP 텍스트 임베딩 기반으로 상품 이미지를 검색합니다.
    추천/무드/스타일 검색에 사용합니다.
    """

    query_text = (query or "").strip()
    if not query_text:
        return {"error": "검색어를 입력해주세요."}

    try:
        variants = _build_query_variants(query_text)
        variant_top_k = max(top_k + 3, 8)
        candidate_lists: list[list[int]] = []
        for variant in variants:
            candidate_lists.append(
                search_similar_products_from_text(
                    text=variant,
                    top_k=variant_top_k,
                    search_mode=search_mode,
                )
            )
        keyword_ids, keyword_products = _keyword_candidate_products(query_text, top_k)
        if keyword_ids:
            candidate_lists.append(keyword_ids)
        rescue_ids, rescue_products = _rescue_candidate_products(query_text, top_k)
        if rescue_ids:
            candidate_lists.append(rescue_ids)
        product_ids = _merge_product_ids(candidate_lists, top_k)
        products = _build_product_payloads(product_ids)
        existing_ids = {int(product["id"]) for product in products if product.get("id") is not None}
        for product in keyword_products:
            pid = product.get("id")
            if pid is None or int(pid) in existing_ids:
                continue
            products.append(product)
            product_ids.append(int(pid))
            existing_ids.add(int(pid))
        for product in rescue_products:
            pid = product.get("id")
            if pid is None or int(pid) in existing_ids:
                continue
            products.append(product)
            product_ids.append(int(pid))
            existing_ids.add(int(pid))
        rerank_query = " ".join(variants) if len(variants) > 1 else query_text
        product_ids, products = _rerank_products_by_query(rerank_query, product_ids, products)
        product_ids = product_ids[:top_k]
        products = products[:top_k]
        return {
            "ui_action": "show_product_list",
            "product_ids": product_ids,
            "products": products,
        }
    except Exception as e:
        print("TEXT CLIP SEARCH ERROR:", e)
        fallback_query = _translate_discovery_query(query_text) or query_text
        fallback_ids, fallback_products = _keyword_fallback_products(fallback_query, top_k)
        if fallback_products:
            return {
                "ui_action": "show_product_list",
                "product_ids": fallback_ids,
                "products": fallback_products,
                "fallback": "keyword_search",
            }
        return {"error": f"텍스트 기반 이미지 검색 실패: {str(e)}"}
