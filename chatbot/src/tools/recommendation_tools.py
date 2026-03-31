import importlib
import json
import os
import re
import pandas as pd
from typing import Any, List, Optional
from flashrank import Ranker, RerankRequest
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from chatbot.src.tools.image_search_tools import (
    SearchHit,
    search_similar_product_hits_multimodal,
    search_similar_product_hits_from_text,
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
_DISCOVERY_RERANK_LLM: ChatOpenAI | None = None
_ECOMMERCE_BACKEND_CACHE: tuple[Any, Any, Any, Any] | None = None
_ECOMMERCE_BACKEND_ERROR: Exception | None = None


def _load_ecommerce_backend_primitives() -> tuple[Any, Any, Any, Any]:
    global _ECOMMERCE_BACKEND_CACHE, _ECOMMERCE_BACKEND_ERROR
    if _ECOMMERCE_BACKEND_CACHE is not None:
        return _ECOMMERCE_BACKEND_CACHE
    if _ECOMMERCE_BACKEND_ERROR is not None:
        raise _ECOMMERCE_BACKEND_ERROR
    try:
        database_module = importlib.import_module("ecommerce.backend.app.database")
        models_module = importlib.import_module("ecommerce.backend.app.models")
        crud_module = importlib.import_module("ecommerce.backend.app.router.products.crud")
        schemas_module = importlib.import_module("ecommerce.backend.app.router.products.schemas")
        _ECOMMERCE_BACKEND_CACHE = (
            getattr(database_module, "SessionLocal"),
            getattr(models_module, "User"),
            crud_module,
            schemas_module,
        )
        return _ECOMMERCE_BACKEND_CACHE
    except Exception as exc:
        _ECOMMERCE_BACKEND_ERROR = exc
        raise


def _ecommerce_backend_available() -> bool:
    try:
        _load_ecommerce_backend_primitives()
    except Exception:
        return False
    return True


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _coerce_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("amount", "price", "value", "sale_price", "discounted_price"):
            parsed = _coerce_price(value.get(key))
            if parsed is not None:
                return parsed
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace(",", "")
    normalized = re.sub(r"[^0-9.\-]", "", normalized)
    if not normalized:
        return None
    try:
        return float(normalized)
    except Exception:
        return None


def _normalize_category(payload: dict[str, Any]) -> str | None:
    primary = _first_non_empty(
        payload.get("category"),
        payload.get("subcategory"),
        payload.get("sub_category"),
        payload.get("article_type"),
        payload.get("articleType"),
    )
    if primary:
        return primary
    parts = [
        _first_non_empty(payload.get("main_category")),
        _first_non_empty(payload.get("sub_category")),
        _first_non_empty(payload.get("article_type")),
    ]
    cleaned = [part for part in parts if part]
    if not cleaned:
        return None
    deduped: list[str] = []
    for part in cleaned:
        if part not in deduped:
            deduped.append(part)
    return " > ".join(deduped)


def _payload_to_product(hit: SearchHit) -> dict[str, Any]:
    payload = dict(hit.payload or {})
    product_id = payload.get("product_id", payload.get("id", hit.product_id))
    title = _first_non_empty(
        payload.get("product_display_name"),
        payload.get("product_name"),
        payload.get("name"),
        payload.get("title"),
        payload.get("variant_name"),
        payload.get("option_name"),
    )
    category = _normalize_category(payload)
    return {
        "id": int(product_id) if str(product_id).strip().isdigit() else product_id,
        "name": title or f"상품 {product_id}",
        "price": _coerce_price(
            payload.get("price")
            or payload.get("sale_price")
            or payload.get("discounted_price")
            or payload.get("list_price")
        ),
        "category": category,
        "color": _first_non_empty(
            payload.get("color"),
            payload.get("base_colour"),
            payload.get("baseColor"),
        ),
        "season": _first_non_empty(payload.get("season")),
        "image_url": _first_non_empty(
            payload.get("image_url"),
            payload.get("resolved_image_url"),
            payload.get("image"),
            payload.get("primary_image"),
        ),
        "brand": _first_non_empty(
            payload.get("brand"),
            payload.get("brand_name"),
            payload.get("manufacturer"),
        ),
        "description": _first_non_empty(
            payload.get("description"),
            payload.get("summary"),
            payload.get("details"),
            payload.get("benefits"),
        ),
    }


def _build_products_from_hits(hits: list[SearchHit]) -> tuple[list[int], list[dict[str, Any]]]:
    product_ids: list[int] = []
    products: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for hit in hits:
        try:
            product_id = int(hit.product_id)
        except Exception:
            continue
        if product_id in seen_ids:
            continue
        seen_ids.add(product_id)
        product_ids.append(product_id)
        products.append(_payload_to_product(hit))
    return product_ids, products

_COLOR_TRANSLATIONS = {
    "검은색": "black",
    "검은": "black",
    "검정": "black",
    "블랙": "black",
    "흰색": "white",
    "흰": "white",
    "하얀색": "white",
    "하얀": "white",
    "화이트": "white",
    "파란색": "blue",
    "파란": "blue",
    "파랑": "blue",
    "블루": "blue",
    "하늘색": "aqua",
    "스카이블루": "aqua",
    "네이비": "navy blue",
    "남색": "navy blue",
    "빨간색": "red",
    "빨간": "red",
    "빨강": "red",
    "레드": "red",
    "회색": "grey",
    "그레이": "grey",
    "회색빛": "grey",
    "핑크": "pink",
    "분홍색": "pink",
    "주황색": "orange",
    "주황": "orange",
    "오렌지": "orange",
    "갈색": "brown",
    "브라운": "brown",
    "카키색": "khaki",
    "카키": "khaki",
    "초록색": "green",
    "초록": "green",
    "그린": "green",
    "보라색": "purple",
    "보라": "purple",
    "퍼플": "purple",
    "노란색": "yellow",
    "노란": "yellow",
    "옐로": "yellow",
    "진회색": "dark grey",
    "차콜": "charcoal",
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
_ACCESSORY_MISMATCH_TOKENS = {
    "briefs",
    "bra",
    "lipstick",
    "lip care",
    "highlighter",
    "blush",
    "bath robe",
    "robe",
    "stockings",
    "muffler",
    "scarf",
    "tie",
    "cufflinks",
    "mobile pouch",
    "shapewear",
    "hair colour",
}
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
    "blue": {"blue", "aqua"},
    "aqua": {"aqua", "blue"},
    "navy blue": {"navy", "blue"},
    "red": {"red"},
    "grey": {"grey", "gray"},
    "dark grey": {"dark", "grey", "gray", "charcoal"},
    "pink": {"pink"},
    "orange": {"orange"},
    "brown": {"brown", "tan"},
    "khaki": {"khaki", "olive"},
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

_PATTERN_TRANSLATIONS = {
    "줄무늬": "striped",
    "스트라이프": "striped",
    "체크": "checked",
    "프린트": "printed",
    "민소매": "sleeveless",
    "무지": "solid",
}

_MATERIAL_TRANSLATIONS = {
    "가죽": "leatherette",
    "레더": "leatherette",
    "캔버스": "canvas",
}

_QUERY_NORMALIZATION_REPLACEMENTS = [
    ("더플 스타일 가방", "더플백"),
    ("더플 스타일", "더플백"),
    ("더플 가방", "더플백"),
    ("더플 스타일의 가방", "더플백"),
    ("정장화", "구두"),
    ("드레스화", "구두"),
    ("캐주얼화", "캐주얼 신발"),
    ("캐주얼 슈즈", "캐주얼 신발"),
    ("폴로티셔츠", "폴로 티셔츠"),
    ("폴로티", "폴로 티셔츠"),
    ("배낭", "백팩"),
    ("배낭가방", "백팩"),
    ("드레스", "원피스"),
    ("흰 티셔츠", "흰색 티셔츠"),
    ("흰 티", "흰색 티셔츠"),
    ("검정 티", "검은색 티셔츠"),
    ("검은 티", "검은색 티셔츠"),
]

_USAGE_TRANSLATIONS = {
    "여행": ["travel"],
    "등산": ["hiking", "rucksack"],
    "하이킹": ["hiking", "rucksack"],
    "운동": ["sports"],
    "스포츠": ["sports"],
    "트레이닝": ["training", "trng"],
    "캐주얼": ["casual"],
    "정장": ["formal"],
    "포멀": ["formal"],
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
        "mismatch": ["laptop bag", "messenger", "waist pouch", "backpack"],
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
        "mismatch": ["formal shirt", "dress shirt", "cap", "hat", "muffler", "scarf", "tie"],
    },
    "자켓": {
        "strong": ["jacket"],
        "mismatch": ["waistcoat", "vest", "bath robe"],
    },
    "조끼": {
        "strong": ["waistcoat", "vest"],
        "mismatch": ["jacket", "blazer", "bath robe"],
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
    "쿠르티": {
        "strong": ["kurti", "kurtis"],
        "mismatch": ["kurta sets", "dupatta", "salwar"],
    },
    "쿠르타": {
        "strong": ["kurta", "kurtas"],
        "mismatch": ["kurta sets", "dupatta", "salwar"],
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


def _normalize_discovery_query(query: str) -> str:
    normalized = (query or "").strip()
    for source, target in _QUERY_NORMALIZATION_REPLACEMENTS:
        if source in normalized:
            normalized = normalized.replace(source, target)
    return normalized


def _find_target_terms(query: str) -> list[str]:
    query = _normalize_discovery_query(query)
    found: list[str] = []
    lowered = (query or "").lower()
    for term in sorted(_TARGET_TERMS, key=len, reverse=True):
        matched = False
        if term in query:
            matched = True
        else:
            english_key = term.lower()
            if english_key in lowered:
                matched = True
        if not matched:
            continue
        if any(term in existing for existing in found):
            continue
        found.append(term)
    return found


def _dedupe_terms(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value.strip())
    return deduped


def _extract_query_slots(query: str) -> dict[str, object]:
    query_text = _normalize_discovery_query(query)
    lowered = query_text.lower()

    colors = _extract_query_colors(query_text)
    target_terms = _find_target_terms(query_text)

    gender = ""
    for key, value in _GENDER_HINTS.items():
        if key in query_text or key in lowered:
            gender = value
            break

    usage_tokens: list[str] = []
    for trigger, translations in _USAGE_TRANSLATIONS.items():
        if trigger in query_text or trigger in lowered:
            usage_tokens.extend(translations)

    patterns: list[str] = []
    for trigger, translation in _PATTERN_TRANSLATIONS.items():
        if trigger in query_text or trigger in lowered:
            patterns.append(translation)

    materials: list[str] = []
    for trigger, translation in _MATERIAL_TRANSLATIONS.items():
        if trigger in query_text or trigger in lowered:
            materials.append(translation)

    category_synonyms: list[str] = []
    for term in target_terms:
        category_synonyms.extend(_CATEGORY_TRANSLATIONS.get(term, []))

    return {
        "colors": _dedupe_terms(colors),
        "target_terms": target_terms,
        "gender": gender,
        "usage_tokens": _dedupe_terms(usage_tokens),
        "patterns": _dedupe_terms(patterns),
        "materials": _dedupe_terms(materials),
        "ascii_tokens": _extract_ascii_tokens(query_text),
        "category_synonyms": _dedupe_terms(category_synonyms),
        "primary_category_phrase": _PRIMARY_CATEGORY_PHRASES.get(target_terms[0], target_terms[0]) if target_terms else "",
    }


def _build_slot_variant(query: str) -> str:
    slots = _extract_query_slots(query)
    pieces: list[str] = []

    colors = list(slots["colors"])
    if colors:
        pieces.extend(colors[:2])

    primary_category_phrase = str(slots["primary_category_phrase"] or "")
    if primary_category_phrase:
        pieces.append(primary_category_phrase)

    gender = str(slots["gender"] or "")
    if gender:
        pieces.append(gender)

    pieces.extend(list(slots["usage_tokens"]))
    pieces.extend(list(slots["patterns"]))
    pieces.extend(list(slots["materials"]))

    return " ".join(_dedupe_terms(pieces))


def _translate_discovery_query(query: str) -> str:
    query_text = (query or "").strip()
    if not query_text:
        return ""

    slots = _extract_query_slots(query_text)
    pieces: list[str] = []
    pieces.extend(list(slots["ascii_tokens"]))
    pieces.extend(list(slots["colors"]))
    pieces.extend(list(slots["category_synonyms"]))
    gender = str(slots["gender"] or "")
    if gender:
        pieces.append(gender)
    pieces.extend(list(slots["usage_tokens"]))
    pieces.extend(list(slots["patterns"]))
    pieces.extend(list(slots["materials"]))
    return " ".join(_dedupe_terms(pieces))


def _build_focused_variant(query: str) -> str:
    query_text = (query or "").strip()
    if not query_text:
        return ""

    slots = _extract_query_slots(query_text)
    pieces: list[str] = []

    colors = list(slots["colors"])
    if colors:
        pieces.extend(colors[:1])

    primary_category_phrase = str(slots["primary_category_phrase"] or "")
    if primary_category_phrase:
        pieces.append(primary_category_phrase)

    gender = str(slots["gender"] or "")
    if gender:
        pieces.append(gender)

    usage_tokens = list(slots["usage_tokens"])
    if usage_tokens:
        pieces.extend(usage_tokens[:2])
    patterns = list(slots["patterns"])
    if patterns:
        pieces.extend(patterns[:1])
    materials = list(slots["materials"])
    if materials:
        pieces.extend(materials[:1])

    return " ".join(_dedupe_terms(pieces))


def _build_query_variants(query: str) -> list[str]:
    query_text = (query or "").strip()
    normalized_query = _normalize_discovery_query(query_text)
    variants: list[str] = []
    if normalized_query:
        variants.append(normalized_query)
    if query_text and query_text != normalized_query:
        variants.append(query_text)

    focused = _build_focused_variant(normalized_query)
    if focused and focused not in variants:
        variants.append(focused)

    slot_variant = _build_slot_variant(normalized_query)
    if slot_variant and slot_variant not in variants:
        variants.append(slot_variant)

    translated = _translate_discovery_query(normalized_query)
    if translated and translated not in variants:
        variants.append(translated)

    for phrase in _build_exact_phrase_variants(normalized_query)[:3]:
        if phrase and phrase not in variants:
            variants.append(phrase)

    if translated and query_text:
        combined = f"{translated} {' '.join(_extract_ascii_tokens(query_text))}".strip()
        if combined and combined not in variants:
            variants.append(combined)

    return variants[:8]


def _expand_primary_color_variants(colors: list[str]) -> list[str]:
    variants: list[str] = []
    for color in colors[:1]:
        variants.append(color)
        if color == "navy blue":
            variants.append("dark blue")
        elif color == "grey":
            variants.append("gray")
        elif color == "dark grey":
            variants.extend(["charcoal", "dark gray"])
        elif color == "aqua":
            variants.extend(["sky blue", "light blue"])
    return _dedupe_terms(variants)


def _build_exact_phrase_variants(query: str) -> list[str]:
    slots = _extract_query_slots(query)
    target_terms = list(slots["target_terms"])
    if not target_terms:
        return []

    colors = _expand_primary_color_variants(list(slots["colors"]))
    usage_tokens = list(slots["usage_tokens"])
    pattern_tokens = list(slots["patterns"])
    material_tokens = list(slots["materials"])
    gender = str(slots["gender"] or "")
    target = target_terms[0]

    phrases: list[str] = []

    def add(*parts: str) -> None:
        phrase = " ".join(part for part in parts if part).strip()
        if phrase and phrase not in phrases:
            phrases.append(phrase)

    color_variants = colors or [""]

    if target == "티셔츠":
        noun_variants = ["t-shirt", "tshirts", "t shirt", "tee"]
        for color in color_variants:
            if "printed" in pattern_tokens:
                for noun in noun_variants[:3]:
                    add(color, "printed", noun)
            for noun in noun_variants:
                add(color, noun)
    elif target == "폴로 티셔츠":
        for color in color_variants:
            add(color, "polo t-shirt")
            add(color, "polo shirt")
    elif target == "셔츠":
        pattern_variants = [""]
        if "striped" in pattern_tokens:
            pattern_variants = ["striped", "stripes"]
        elif "checked" in pattern_tokens:
            pattern_variants = ["checked", "check"]
        for color in color_variants:
            for pattern in pattern_variants:
                add(color, pattern, "shirt")
                add(color, pattern, "shirts")
            add(color, "shirt")
    elif target in {"백팩", "여행용 백팩"}:
        for color in color_variants:
            if "hiking" in usage_tokens:
                add(color, "rucksack")
                add(color, "hiking backpack")
            elif "training" in usage_tokens:
                add(color, "training backpack")
                add(color, "trng backpack")
                add(color, "sports backpack")
            else:
                add(color, "backpack")
                add(color, "solid backpack")
    elif target == "구두":
        for color in color_variants:
            add(color, "formal shoes")
            add(color, "dress shoes")
    elif target == "캐주얼 신발":
        for color in color_variants:
            if "canvas" in material_tokens:
                add(color, "canvas casual shoes")
                add(color, "canvas shoes")
            add(color, "casual shoes")

    if gender and target in {"티셔츠", "셔츠", "백팩", "여행용 백팩", "구두", "캐주얼 신발"}:
        gendered: list[str] = []
        for phrase in phrases[:]:
            if any(noun in phrase for noun in ["t-shirt", "tshirts", "shirt", "backpack", "shoes"]):
                gendered.append(f"{gender} {phrase}")
        phrases.extend(gendered)

    return phrases[:6]


def _score_discovery_phrase_bonus(query_text: str | None, product: dict) -> float:
    query = _normalize_discovery_query(query_text or "")
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

    bonus = 0.0
    exact_variants = _build_exact_phrase_variants(query)
    for phrase in exact_variants:
        phrase_tokens = _semantic_tokens(phrase)
        if not phrase_tokens:
            continue
        overlap = len(phrase_tokens & normalized_haystack)
        if overlap == len(phrase_tokens):
            bonus = max(bonus, 0.9 + 0.12 * len(phrase_tokens))
        elif overlap >= max(2, len(phrase_tokens) - 1):
            bonus = max(bonus, 0.35 + 0.08 * overlap)

    return min(1.8, bonus)


def _extract_product_slots(product: dict) -> dict[str, object]:
    haystack = " ".join(
        [
            str(product.get("name") or ""),
            str(product.get("category") or ""),
            str(product.get("color") or ""),
        ]
    ).lower()
    tokens = _semantic_tokens(haystack)

    colors: list[str] = []
    for canonical, family in _COLOR_FAMILIES.items():
        if any(color in haystack for color in family):
            colors.append(canonical)

    categories: set[str] = set()
    primary_target = ""
    for target, synonyms in _CATEGORY_TRANSLATIONS.items():
        normalized_synonyms = {_normalize_token(token) for token in synonyms if _normalize_token(token)}
        if any(token.lower() in haystack for token in synonyms) or normalized_synonyms & tokens:
            categories.add(target)
            if not primary_target:
                primary_target = target

    patterns: set[str] = set()
    if "printed" in haystack:
        patterns.add("printed")
    if "striped" in haystack or "stripes" in haystack:
        patterns.add("striped")
    if "checked" in haystack or "check" in haystack:
        patterns.add("checked")
    if any(token in haystack for token in ["solid", "plain"]):
        patterns.add("solid")
    if "sleeveless" in haystack:
        patterns.add("sleeveless")

    materials: set[str] = set()
    if "canvas" in haystack:
        materials.add("canvas")
    if any(token in haystack for token in ["leatherette", "leather"]):
        materials.add("leatherette")

    usages: set[str] = set()
    if any(token in haystack for token in ["training", "trng"]):
        usages.add("training")
    if "sports" in haystack or "track" in haystack:
        usages.add("sports")
    if "casual" in haystack:
        usages.add("casual")
    if any(token in haystack for token in ["formal shoes", "dress shoes", "formal"]):
        usages.add("formal")
    if any(token in haystack for token in ["travel", "rucksack", "hiking"]):
        usages.add("hiking")

    gender = ""
    if "boys" in haystack:
        gender = "boys"
    elif "girls" in haystack:
        gender = "girls"
    elif "kids" in haystack:
        gender = "kids"
    elif "men" in haystack:
        gender = "men"
    elif "women" in haystack:
        gender = "women"
    elif "unisex" in haystack:
        gender = "unisex"

    subtype = "generic"
    if "백팩" in categories or "여행용 백팩" in categories:
        if "rucksack" in haystack:
            subtype = "rucksack"
        elif any(token in haystack for token in ["training", "trng", "sports"]):
            subtype = "training_backpack"
        elif "printed" in haystack:
            subtype = "printed_backpack"
        elif any(token in haystack for token in ["leatherette", "leather"]):
            subtype = "leather_backpack"
        elif any(token in haystack for token in ["solid", "plain"]):
            subtype = "plain_backpack"
        else:
            subtype = "backpack"
    elif "구두" in categories or "캐주얼 신발" in categories or "운동화" in categories or "스포츠화" in categories:
        if "formal shoes" in haystack:
            subtype = "formal_shoes"
        elif "casual shoes" in haystack:
            subtype = "casual_shoes"
        elif "sports shoes" in haystack or "track" in haystack:
            subtype = "sports_shoes"
        elif "canvas" in haystack:
            subtype = "canvas_shoes"
    elif "티셔츠" in categories or "폴로 티셔츠" in categories or "셔츠" in categories:
        if "polo" in haystack:
            subtype = "polo_tshirt"
        elif "t-shirt" in haystack or "tee" in haystack or "tshirts" in haystack:
            subtype = "tshirt"
        elif "shirt" in haystack:
            subtype = "shirt"
    elif "자켓" in categories:
        if "sleeveless" in haystack:
            subtype = "sleeveless_jacket"
        elif "nehru" in haystack:
            subtype = "nehru_jacket"
        elif "tracksuit" in haystack:
            subtype = "tracksuit"
        elif "rain jacket" in haystack:
            subtype = "rain_jacket"
        else:
            subtype = "plain_jacket"
    elif "원피스" in categories:
        if "nightdress" in haystack or "babydoll" in haystack:
            subtype = "nightdress"
        else:
            subtype = "dress"
    elif "조끼" in categories:
        subtype = "waistcoat"

    return {
        "colors": _dedupe_terms(colors),
        "categories": categories,
        "patterns": patterns,
        "materials": materials,
        "usages": usages,
        "gender": gender,
        "subtype": subtype,
        "tokens": tokens,
        "haystack": haystack,
        "primary_target": primary_target,
    }


def _score_discovery_slot_alignment(query_text: str | None, product: dict) -> float:
    query = (query_text or "").strip()
    if not query:
        return 0.0

    query_slots = _extract_query_slots(query)
    product_slots = _extract_product_slots(product)
    score = 0.0

    query_colors = list(query_slots["colors"])
    product_colors = set(product_slots["colors"])
    if query_colors:
        matched = sum(1 for color in query_colors if color in product_colors)
        if matched:
            score += 0.45 * matched
        if len(query_colors) >= 2:
            if matched == len(query_colors):
                score += 0.55
            else:
                score -= 0.35

    target_terms = list(query_slots["target_terms"])
    categories = set(product_slots["categories"])
    if target_terms:
        primary_target = target_terms[0]
        if primary_target in categories:
            score += 0.8
        elif primary_target == "백팩" and "여행용 백팩" in categories:
            score += 0.55
        elif primary_target == "운동화" and "스포츠화" in categories:
            score += 0.55
        elif primary_target == "스포츠화" and "운동화" in categories:
            score += 0.55
        else:
            score -= 0.45

    usages = set(query_slots["usage_tokens"])
    product_usages = set(product_slots["usages"])
    if usages:
        overlap = usages & product_usages
        if overlap:
            score += 0.7 * len(overlap)
        elif any(token in usages for token in {"training", "hiking", "formal"}):
            score -= 0.6

    patterns = set(query_slots["patterns"])
    product_patterns = set(product_slots["patterns"])
    if patterns:
        overlap = patterns & product_patterns
        if overlap:
            score += 0.75 * len(overlap)
        else:
            score -= 0.55
    else:
        if product_patterns & {"printed", "checked", "striped"} and not usages:
            score -= 0.2

    materials = set(query_slots["materials"])
    product_materials = set(product_slots["materials"])
    if materials:
        if materials & product_materials:
            score += 0.65
        else:
            score -= 0.35

    query_gender = str(query_slots["gender"] or "")
    product_gender = str(product_slots["gender"] or "")
    if query_gender:
        if query_gender == product_gender:
            score += 0.35
        elif product_gender and product_gender != "unisex":
            score -= 0.25
    else:
        if product_gender in {"boys", "girls", "kids"}:
            score -= 0.45
        elif product_gender in {"men", "women", "unisex"}:
            score += 0.1

    subtype = str(product_slots["subtype"] or "")
    if target_terms:
        primary_target = target_terms[0]
        if primary_target == "백팩":
            if not usages and not patterns and not materials:
                if subtype == "plain_backpack":
                    score += 0.8
                elif subtype in {"training_backpack", "printed_backpack", "leather_backpack", "rucksack"}:
                    score -= 0.65
            if "training" in usages:
                if subtype == "training_backpack":
                    score += 0.95
                elif subtype == "rucksack":
                    score -= 0.55
            if "hiking" in usages:
                if subtype == "rucksack":
                    score += 0.9
            if "printed" in patterns:
                if subtype == "printed_backpack":
                    score += 0.9
                elif subtype == "rucksack":
                    score -= 0.5
        elif primary_target == "구두":
            if subtype == "formal_shoes":
                score += 0.85
            elif subtype in {"casual_shoes", "sports_shoes"}:
                score -= 0.8
        elif primary_target == "티셔츠":
            if subtype == "tshirt":
                score += 0.7
            elif subtype == "polo_tshirt" and "폴로" not in query:
                score -= 0.65
            elif subtype == "shirt":
                score -= 0.75
        elif primary_target == "셔츠":
            if subtype == "shirt":
                score += 0.7
            elif subtype == "tshirt":
                score -= 0.8
        elif primary_target == "자켓":
            if subtype == "plain_jacket":
                score += 0.75
            elif subtype in {"sleeveless_jacket", "nehru_jacket", "tracksuit", "rain_jacket"}:
                score -= 0.75
        elif primary_target == "원피스":
            if subtype == "dress":
                score += 0.45
            elif subtype == "nightdress":
                score -= 0.55

    return max(-3.0, min(4.5, score))


def _get_discovery_rerank_llm() -> ChatOpenAI | None:
    global _DISCOVERY_RERANK_LLM
    if os.getenv("DISCOVERY_LLM_RERANK_DISABLED", "").lower() in {"1", "true", "yes"}:
        return None
    if _DISCOVERY_RERANK_LLM is not None:
        return _DISCOVERY_RERANK_LLM
    try:
        model = os.getenv("DISCOVERY_LLM_RERANK_MODEL", "gpt-4o-mini")
        _DISCOVERY_RERANK_LLM = ChatOpenAI(model=model, temperature=0)
        return _DISCOVERY_RERANK_LLM
    except Exception as e:
        print(f"Discovery LLM reranker unavailable, fallback to heuristic order: {e}")
        _DISCOVERY_RERANK_LLM = None
        return None


def _parse_llm_ranked_product_ids(content: str, valid_ids: set[int]) -> list[int]:
    text = (content or "").strip()
    if not text:
        return []

    candidates = [text]
    fenced_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced_match:
        candidates.insert(0, fenced_match.group(1).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            parsed = parsed.get("ranked_ids") or parsed.get("ids") or parsed.get("product_ids")
        if not isinstance(parsed, list):
            continue
        ranked_ids: list[int] = []
        seen: set[int] = set()
        for item in parsed:
            try:
                pid = int(item)
            except (TypeError, ValueError):
                continue
            if pid in valid_ids and pid not in seen:
                ranked_ids.append(pid)
                seen.add(pid)
        if ranked_ids:
            return ranked_ids

    extracted_ids: list[int] = []
    seen: set[int] = set()
    for match in re.findall(r"\d+", text):
        pid = int(match)
        if pid in valid_ids and pid not in seen:
            extracted_ids.append(pid)
            seen.add(pid)
    return extracted_ids


def _llm_rerank_products(
    query_text: str | None,
    product_ids: List[int],
    products: List[dict],
) -> tuple[List[int], List[dict]]:
    query = (query_text or "").strip()
    if not query or len(products) < 2:
        return product_ids, products

    llm = _get_discovery_rerank_llm()
    if llm is None:
        return product_ids, products

    candidate_products = [product for product in products[: min(5, len(products))] if product.get("id") is not None]
    if len(candidate_products) < 2:
        return product_ids, products

    candidate_lines = []
    valid_ids: set[int] = set()
    for product in candidate_products:
        pid = int(product["id"])
        valid_ids.add(pid)
        candidate_lines.append(
            f"- id={pid} | name={product.get('name', '')} | category={product.get('category', '')} | color={product.get('color', '')}"
        )

    system_prompt = """당신은 패션 상품 reranker입니다.
사용자 질의와 가장 잘 맞는 상품부터 순서를 다시 정렬하세요.

우선순위:
1. 카테고리/세부 타입 정확 일치
2. 색상 정확 일치
3. 패턴/재질/용도 일치
4. 성별/연령대 일치

반드시 JSON 배열만 출력하세요. 예: [101, 202, 303]"""
    human_prompt = (
        f"질문: {query}\n"
        "후보 상품:\n"
        + "\n".join(candidate_lines)
        + "\n가장 적합한 순서대로 상품 id 배열만 반환하세요."
    )

    try:
        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt),
            ]
        )
        ranked_ids = _parse_llm_ranked_product_ids(str(response.content), valid_ids)
        if not ranked_ids:
            return product_ids, products

        leading_ids = [pid for pid in ranked_ids if pid in valid_ids]
        remaining_ids = [int(product["id"]) for product in candidate_products if int(product["id"]) not in leading_ids]
        reordered_head = leading_ids + remaining_ids

        by_id = {int(product["id"]): product for product in products if product.get("id") is not None}
        tail_ids = [pid for pid in product_ids if pid not in reordered_head]
        final_ids = reordered_head + tail_ids
        final_products = [by_id[pid] for pid in final_ids if pid in by_id]
        return final_ids, final_products
    except Exception as e:
        print(f"Discovery LLM reranking fallback to heuristic order: {e}")
        return product_ids, products


def _score_discovery_adjustment(query_text: str | None, product: dict) -> float:
    query = _normalize_discovery_query(query_text or "")
    if not query:
        return 0.0

    slots = _extract_query_slots(query)

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

    query_colors = list(slots["colors"])
    target_terms = list(slots["target_terms"])
    query_gender = str(slots["gender"] or "")
    usage_tokens = set(slots["usage_tokens"])
    pattern_tokens = set(slots["patterns"])
    material_tokens = set(slots["materials"])
    if query_colors:
        color_matched = False
        matched_color_count = 0
        for query_color in query_colors:
            color_family = _COLOR_FAMILIES.get(query_color, {query_color})
            if any(color in haystack for color in color_family):
                score += 0.9
                color_matched = True
                matched_color_count += 1
        if not color_matched:
            score -= 0.95
        elif len(query_colors) >= 2:
            if matched_color_count == len(query_colors):
                score += 1.25
            else:
                score -= 0.35

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
            conflict_penalty = 0.3 * len(conflicting_colors)
            if len(query_colors) == 1:
                conflict_penalty += 0.2 * len(conflicting_colors)
            score -= min(1.4, conflict_penalty)

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

    if target_terms and not matched_target:
        score -= 1.45
        if any(token in haystack for token in _ACCESSORY_MISMATCH_TOKENS):
            score -= 0.85

    if "백팩" in query:
        if "backpack" in haystack or "rucksack" in haystack:
            score += 0.5
        if len(query_colors) >= 2 and all(
            any(color in haystack for color in _COLOR_FAMILIES.get(query_color, {query_color}))
            for query_color in query_colors
        ) and ("backpack" in haystack or "rucksack" in haystack):
            score += 0.85
        if "duffle bag" in haystack or "duffel bag" in haystack:
            score -= 0.8
        if "messenger" in haystack or "messanger" in haystack or "laptop bag" in haystack:
            score -= 1.15
        if "rain cover" in haystack:
            score -= 1.0
        if "hiking" in usage_tokens:
            if "rucksack" in haystack:
                score += 1.15
            elif "backpack" in haystack:
                score += 0.3
            if "black" in haystack and "red" in query_colors:
                score -= 0.4
        if "training" in usage_tokens:
            if any(token in haystack for token in ["training", "trng", "sports"]):
                score += 1.25
            elif "backpack" in haystack:
                score -= 0.4
            if "rucksack" in haystack:
                score -= 0.55
        if "leatherette" in material_tokens:
            if "leatherette" in haystack or "leather" in haystack:
                score += 1.0
            elif "canvas" in haystack:
                score -= 0.25
        if "printed" in pattern_tokens:
            if "printed" in haystack and "backpack" in haystack:
                score += 0.95
            elif "rucksack" in haystack:
                score -= 0.8
        if not usage_tokens and not material_tokens and not pattern_tokens:
            if "backpack" in haystack and all(token not in haystack for token in ["rucksack", "training", "trng", "printed", "leatherette", "leather"]):
                score += 1.15
            if "solid" in haystack:
                score += 0.95
            if "rucksack" in haystack:
                score -= 0.65
            if any(token in haystack for token in ["training", "trng", "sports"]):
                score -= 1.15
            if "printed" in haystack:
                score -= 1.1
            if any(token in haystack for token in ["leatherette", "leather"]):
                score -= 1.15
        if any(token in haystack for token in ["laptop bag", "sleeve bag", "sling bag", "handbag"]):
            score -= 1.25
    if "운동 가방" in query:
        if "gym bag" in haystack or "duffel bag" in haystack or "duffle bag" in haystack:
            score += 0.8
        if "laptop bag" in haystack or "messenger bag" in haystack or "backpack" in haystack:
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
        if "canvas" in material_tokens:
            if "canvas" in haystack:
                score += 1.0
            elif "formal shoes" in haystack or "sports shoes" in haystack:
                score -= 0.35
    if "formal" in usage_tokens or "구두" in query:
        if "formal shoes" in haystack:
            score += 0.85
            if "black" in query_colors and "black" in haystack:
                score += 0.85
        if "casual shoes" in haystack or "sports shoes" in haystack:
            score -= 1.0
        if "shoes" in haystack and "formal shoes" not in haystack:
            score -= 0.8
        if "black" in query_colors and any(token in haystack for token in ["brown", "tan"]):
            score -= 1.8
    if "sports" in usage_tokens or "운동화" in query or "스포츠화" in query:
        if "sports shoes" in haystack or "track" in haystack:
            score += 0.8
        if "formal shoes" in haystack:
            score -= 0.8
        if "casual shoes" in haystack:
            score -= 0.45
        if "teens" in haystack:
            score -= 0.55
        if len(conflicting_colors) >= 1:
            score -= 0.8
        elif query_colors and "sports shoes" in haystack:
            score += 0.2
    if "티셔츠" in query:
        if "t-shirt" in haystack or "tee" in haystack:
            score += 0.65
        if "shirt" in haystack and "t-shirt" not in haystack:
            score -= 0.55
        if "sweatshirt" in haystack:
            score -= 0.85
        if "polo" in haystack and "폴로" not in query:
            score -= 1.05
        if "lounge top" in haystack:
            score -= 0.85
        if "printed" not in pattern_tokens and "printed" in haystack:
            score -= 0.35
        if "pack of" in haystack:
            score -= 0.5
        if "kidswear" in haystack:
            score -= 0.6
        if "camisole" in haystack or "innerwear" in haystack:
            score -= 1.0
    if "폴로" in query:
        if "polo" in haystack:
            score += 1.8
        elif any(token in haystack for token in ["tunic", "kurti", "kurta"]):
            score -= 1.35
        elif "shirt" in haystack and "t-shirt" not in haystack:
            score -= 0.4
        elif "t-shirt" in haystack or "tee" in haystack:
            score -= 1.1
    if "셔츠" in query:
        if "shirt" in haystack:
            score += 0.55
        if "t-shirt" in haystack or "tee" in haystack:
            score -= 0.95
        if any(token in haystack for token in ["scarf", "muffler", "tie", "cufflinks", "shrug"]):
            score -= 1.15
        if any(token in haystack for token in ["boys", "girls", "kids"]) and "남아" not in query and "여아" not in query and "키즈" not in query:
            score -= 0.95
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
            score += 1.0
        if "kurta" in haystack and "kurti" not in haystack and "kurtis" not in haystack:
            score -= 0.45
        if "kurta sets" in haystack or "dupatta" in haystack:
            score -= 0.9
    if "쿠르타" in query:
        if "kurtas" in haystack or "kurta" in haystack:
            score += 1.0
        if "kurti" in haystack or "kurtis" in haystack:
            score -= 0.35
        if "kurta sets" in haystack:
            score -= 0.75
    if "조끼" in query:
        if "waistcoat" in haystack or "vest" in haystack:
            score += 0.85
        if "jacket" in haystack or "blazer" in haystack:
            score -= 0.55
        if "dark grey" in query_colors:
            if "dark grey" in haystack or "charcoal" in haystack:
                score += 0.65
            elif "grey" in haystack:
                score -= 0.15
        elif "grey" in query_colors and ("dark grey" in haystack or "charcoal" in haystack):
            score -= 0.65
    if "자켓" in query:
        if "jacket" in haystack:
            score += 0.75
        if "sleeveless" in haystack:
            score -= 1.45
        if "nehru" in haystack and "민소매" not in query:
            score -= 0.95
        if "tracksuit" in haystack:
            score -= 0.8
        if "rain jacket" in haystack and "비" not in query and "우비" not in query:
            score -= 1.0
        if "jacket" in haystack and all(token not in haystack for token in ["sleeveless", "nehru", "rain jacket", "tracksuit"]):
            score += 0.7

    if matched_target and any(token in haystack for token in _ACCESSORY_MISMATCH_TOKENS):
        score -= 0.6

    for token in _extract_ascii_tokens(query):
        if token.lower() in haystack:
            score += 0.5

    translated_query = _translate_discovery_query(query)
    translated_tokens = _semantic_tokens(translated_query)
    overlap = translated_tokens & normalized_haystack
    score += min(1.5, len(overlap) * 0.18)

    if "striped" in pattern_tokens:
        if "striped" in haystack or "stripes" in haystack:
            score += 0.65
        if "checked" in haystack or "check" in haystack:
            score -= 0.35
        if "shirt" not in haystack and "셔츠" in query:
            score -= 0.6
        if "shirt" in haystack and "striped" not in haystack and "stripes" not in haystack:
            score -= 1.0
    if "printed" in pattern_tokens:
        if "printed" in haystack:
            score += 0.65
        if "sweatshirt" in haystack or "top" in haystack:
            score -= 0.65
        if any(other in haystack for other in ["boys", "girls", "kids"]):
            score -= 0.55
        if "shirt" in haystack and "t-shirt" not in haystack:
            score -= 0.4
    if "checked" in pattern_tokens:
        if "checked" in haystack or "check" in haystack:
            score += 0.65
        if "striped" in haystack or "stripes" in haystack:
            score -= 0.3
        if "shirt" not in haystack and "셔츠" in query:
            score -= 0.6
        if "shirt" in haystack and "checked" not in haystack and "check" not in haystack:
            score -= 1.2
    if "solid" in pattern_tokens:
        if "solid" in haystack or "plain" in haystack:
            score += 0.75
        if any(other in haystack for other in ["striped", "checked", "printed"]):
            score -= 0.45
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
        if "jumpsuit" in haystack:
            score -= 0.8
        if "nightdress" in haystack or "babydoll" in haystack:
            score -= 0.6
        if "camisole" in haystack:
            score -= 0.75
        if "printed" in haystack and "printed" not in pattern_tokens:
            score -= 0.4
        if not query_gender and any(token in haystack for token in ["girls", "boys", "kids"]):
            score -= 0.55
        if len(query_colors) >= 2:
            if all(any(color in haystack for color in _COLOR_FAMILIES.get(query_color, {query_color})) for query_color in query_colors):
                score += 0.8
            else:
                score -= 0.45
    if "백팩" in query:
        if "waist pouch" in haystack or "hip" in haystack or "messanger" in haystack:
            score -= 0.8

    if query_gender:
        if query_gender in haystack:
            score += 0.25
        elif any(other in haystack for other in ["women", "men", "boys", "girls", "kids"]):
            score -= 0.12
    elif any(other in haystack for other in ["boys", "girls", "kids"]):
        score -= 0.95
    elif any(other in haystack for other in ["women", "men", "unisex"]):
        score += 0.2
    if any(other in haystack for other in ["boys", "girls", "kids"]) and "키즈" not in query and "아동" not in query and "남아" not in query and "여아" not in query:
        score -= 0.45
    elif any(other in haystack for other in ["men", "women", "unisex"]):
        score += 0.1

    if any(term in query for term in ["구두", "신발", "운동화", "스포츠화"]):
        if "shoes" not in haystack and "shoe" not in haystack:
            score -= 1.1
    if any(term in query for term in ["백팩", "더플백", "운동 가방"]):
        if "bag" not in haystack and "backpack" not in haystack and "rucksack" not in haystack:
            score -= 1.2
    if any(term in query for term in ["셔츠", "티셔츠", "폴로"]):
        if not any(token in haystack for token in ["shirt", "t-shirt", "tee", "polo"]):
            score -= 1.1

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
    gender = None
    if _ecommerce_backend_available():
        SessionLocal, User, _product_crud, _product_schemas = _load_ecommerce_backend_primitives()
        db = SessionLocal()
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
    SessionLocal, _User, product_crud, product_schemas = _load_ecommerce_backend_primitives()
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
    SessionLocal, _User, product_crud, _product_schemas = _load_ecommerce_backend_primitives()
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

    SessionLocal, _User, product_crud, _product_schemas = _load_ecommerce_backend_primitives()
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
            phrase_bonus = _score_discovery_phrase_bonus(query, product)
            slot_score = _score_discovery_slot_alignment(query, product)
            composite_score = (base_score * 0.82) + (adjustment * 0.95) + (slot_score * 1.15) + phrase_bonus
            rescored.append((composite_score, pid))

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


def _build_keyword_queries(query_text: str) -> list[str]:
    queries: list[str] = []
    original = (query_text or "").strip()
    if original:
        queries.append(original)

    focused = _build_focused_variant(query_text)
    if focused and focused not in queries:
        queries.append(focused)

    slot_variant = _build_slot_variant(query_text)
    if slot_variant and slot_variant not in queries:
        queries.append(slot_variant)

    for phrase in _build_exact_phrase_variants(query_text):
        if phrase and phrase not in queries:
            queries.append(phrase)

    translated = _translate_discovery_query(query_text)
    if translated and translated not in queries:
        queries.append(translated)

    return queries[:10]


def _keyword_candidate_products(query_text: str, top_k: int) -> tuple[List[int], List[dict]]:
    candidate_lists: list[list[int]] = []
    products_by_id: dict[int, dict] = {}

    for keyword_query in _build_keyword_queries(query_text):
        ids, payloads = _keyword_search_products(keyword_query, max(top_k, 10))
        if not ids:
            continue
        candidate_lists.append(ids)
        for product in payloads:
            pid = product.get("id")
            if pid is not None:
                products_by_id[int(pid)] = product

    if not candidate_lists:
        translated_query = _translate_discovery_query(query_text) or query_text
        return _keyword_fallback_products(translated_query, top_k)

    merged_ids = _merge_product_ids(candidate_lists, top_k)
    merged_products = [products_by_id[pid] for pid in merged_ids if pid in products_by_id]
    return merged_ids, merged_products


def _rescue_candidate_products(query_text: str, top_k: int) -> tuple[List[int], List[dict]]:
    focused_query = _build_focused_variant(query_text)
    if not focused_query:
        return [], []

    rescue_ids, rescue_products = _keyword_search_products(focused_query, max(top_k, 10))
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
        if score >= 0.95
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
        hits = search_similar_product_hits_multimodal(
            image_bytes=bytes(image_bytes),
            text=query_text,
            top_k=top_k,
            search_mode=search_mode,
        )
        product_ids, products = _build_products_from_hits(hits)
        if _ecommerce_backend_available() and product_ids:
            fallback_products = _build_product_payloads(product_ids)
            if fallback_products:
                fallback_by_id = {
                    int(product["id"]): product
                    for product in fallback_products
                    if product.get("id") is not None
                }
                products = [fallback_by_id.get(int(product_id), product) for product_id, product in zip(product_ids, products)]
        print("CLIP SEARCH RESULT:", product_ids)
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
        hit_by_product_id: dict[int, SearchHit] = {}
        for variant in variants:
            hits = search_similar_product_hits_from_text(
                text=variant,
                top_k=variant_top_k,
                search_mode=search_mode,
            )
            if hits:
                candidate_lists.append([int(hit.product_id) for hit in hits])
                for hit in hits:
                    hit_by_product_id.setdefault(int(hit.product_id), hit)
        keyword_ids: list[int] = []
        keyword_products: list[dict[str, Any]] = []
        rescue_ids: list[int] = []
        rescue_products: list[dict[str, Any]] = []
        if _ecommerce_backend_available():
            keyword_ids, keyword_products = _keyword_candidate_products(query_text, top_k)
            if keyword_ids:
                candidate_lists.append(keyword_ids)
            rescue_ids, rescue_products = _rescue_candidate_products(query_text, top_k)
            if rescue_ids:
                candidate_lists.append(rescue_ids)
        product_ids = _merge_product_ids(candidate_lists, top_k)
        retrieval_hits = [hit_by_product_id[pid] for pid in product_ids if pid in hit_by_product_id]
        _retrieval_ids, products = _build_products_from_hits(retrieval_hits)
        if _ecommerce_backend_available() and product_ids:
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
        product_ids, products = _llm_rerank_products(query_text, product_ids, products)
        product_ids = product_ids[:top_k]
        products = products[:top_k]
        return {
            "ui_action": "show_product_list",
            "product_ids": product_ids,
            "products": products,
        }
    except Exception as e:
        print("TEXT CLIP SEARCH ERROR:", e)
        if _ecommerce_backend_available():
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
