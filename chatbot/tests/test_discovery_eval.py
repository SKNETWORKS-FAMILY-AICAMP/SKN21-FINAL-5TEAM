from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chatbot.chatbot_eval.benchmark.rags.discovery.src.evaluator import evaluate
from chatbot.chatbot_eval.benchmark.rags.discovery.src.metrics import (
    score_grounding,
    score_retrieval,
)
from chatbot.src.graph.nodes.discovery_subagent import _should_direct_text_search
from chatbot.src.tools.recommendation_tools import (
    _build_slot_variant,
    _build_keyword_queries,
    _extract_query_slots,
    _extract_product_slots,
    _build_focused_variant,
    _build_query_variants,
    _llm_rerank_products,
    _normalize_discovery_query,
    _parse_llm_ranked_product_ids,
    _score_discovery_adjustment,
    _score_discovery_phrase_bonus,
    _score_discovery_slot_alignment,
    _translate_discovery_query,
)


def test_score_retrieval_normalizes_ids() -> None:
    result = score_retrieval(
        expected_ids=["101", "202"],
        predicted_ids=[101, 303, "202"],
    )

    assert result["passed"] is True
    assert result["hit_at_1"] == 1
    assert result["hit_at_3"] == 1
    assert result["hit_at_5"] == 1
    assert result["matched_product_ids"] == ["101", "202"]


def test_score_grounding_uses_answer_and_product_metadata() -> None:
    result = score_grounding(
        answer_text="화이트 셔츠 느낌으로 골라봤어요.",
        retrieved_products=[
            {"id": 1, "name": "린넨 셔츠", "category": "Topwear", "color": "White"},
        ],
        expected_keywords=["화이트", "셔츠"],
    )

    assert result["passed"] is True
    assert result["keyword_recall"] == 1.0


def test_discovery_evaluator_builds_report(monkeypatch, tmp_path: Path) -> None:
    dataset_path = tmp_path / "discovery_eval.jsonl"
    rows = [
        {
            "id": "discovery_text_001",
            "user_query": "화이트 셔츠 추천해줘",
            "expected_product_ids": ["101"],
            "expected_keywords": ["화이트", "셔츠"],
        },
        {
            "id": "discovery_image_001",
            "user_query": "이 사진이랑 비슷한 셔츠 찾아줘",
            "image_url": "tests/assets/shirt.jpg",
            "expected_product_ids": ["202"],
            "expected_keywords": ["셔츠"],
        },
    ]
    dataset_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )

    responses = {
        "discovery_text_001": {
            "task": "SEARCH_SIMILAR_TEXT",
            "retrieved_products": [
                {"id": 101, "name": "화이트 린넨 셔츠", "category": "Topwear", "color": "White"},
            ],
            "answer_content": "화이트 셔츠 위주로 골랐어요.",
            "ui_action_required": "show_product_list",
        },
        "discovery_image_001": {
            "task": "SEARCH_SIMILAR_IMAGE",
            "retrieved_products": [
                {"id": 202, "name": "오버핏 셔츠", "category": "Topwear", "color": "Blue"},
            ],
            "answer_content": "비슷한 셔츠를 찾았습니다.",
            "ui_action_required": "show_product_list",
        },
    }

    def fake_run_discovery_pipeline(
        user_query: str,
        image_url: str | None = None,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        user_info: dict | None = None,
    ) -> dict:
        if image_url:
            return responses["discovery_image_001"]
        return responses["discovery_text_001"]

    monkeypatch.setattr(
        "chatbot.chatbot_eval.benchmark.rags.discovery.src.evaluator.run_discovery_pipeline",
        fake_run_discovery_pipeline,
    )

    report = evaluate(dataset_path=dataset_path, limit=None)

    assert report["dataset_size"] == 2
    assert report["retrieval_pass_rate"] == 1.0
    assert report["retrieval_hit_at_1"] == 1.0
    assert report["grounding_pass_rate"] == 1.0
    assert report["grounding_keyword_recall"] == 1.0


def test_discovery_evaluator_accepts_alternative_gold_product_ids(
    monkeypatch, tmp_path: Path
) -> None:
    dataset_path = tmp_path / "discovery_eval_multi_gold.jsonl"
    row = {
        "id": "discovery_text_multi_gold",
        "user_query": "네이비 폴로 티셔츠 보여줘",
        "expected_product_ids": ["7744"],
        "acceptable_product_ids": ["7925", "8612"],
        "expected_keywords": ["polo", "navy"],
    }
    dataset_path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")

    def fake_run_discovery_pipeline(
        user_query: str,
        image_url: str | None = None,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        user_info: dict | None = None,
    ) -> dict:
        return {
            "task": "SEARCH_SIMILAR_TEXT",
            "retrieved_products": [
                {"id": 7925, "name": "Proline Men Navy Polo T-shirt", "category": "Topwear", "color": "Navy"},
            ],
            "answer_content": "네이비 폴로 티셔츠를 찾았습니다.",
            "ui_action_required": "show_product_list",
        }

    monkeypatch.setattr(
        "chatbot.chatbot_eval.benchmark.rags.discovery.src.evaluator.run_discovery_pipeline",
        fake_run_discovery_pipeline,
    )

    report = evaluate(dataset_path=dataset_path, limit=None)
    result = report["results"][0]

    assert report["retrieval_pass_rate"] == 1.0
    assert report["retrieval_hit_at_1"] == 1.0
    assert result["expected_product_ids"] == ["7744"]
    assert result["acceptable_product_ids"] == ["7925", "8612"]
    assert result["gold_product_ids"] == ["7744", "7925", "8612"]
    assert result["retrieval_eval"]["matched_product_ids"] == ["7925"]


def test_translate_discovery_query_adds_english_search_terms() -> None:
    translated = _translate_discovery_query("검은색 백팩 추천해줘")

    assert "black" in translated
    assert "backpack" in translated


def test_build_query_variants_keeps_original_and_translated_query() -> None:
    variants = _build_query_variants("핑크 트레이닝 바지 보여줘")

    assert variants[0] == "핑크 트레이닝 바지 보여줘"
    assert any("pink" in variant and "track pants" in variant for variant in variants)
    assert any("track pants" in variant for variant in variants)


def test_build_focused_variant_prefers_compact_search_phrase() -> None:
    assert _build_focused_variant("회색 백팩 보여줘") == "grey backpack"


def test_build_keyword_queries_include_original_focused_and_translated() -> None:
    queries = _build_keyword_queries("검은 캔버스 캐주얼 신발 추천해줘")

    assert queries[0] == "검은 캔버스 캐주얼 신발 추천해줘"
    assert any("casual shoes" in query for query in queries)
    assert any("canvas" in query for query in queries)


def test_build_keyword_queries_add_exact_phrase_variants_for_tshirt() -> None:
    queries = _build_keyword_queries("검은 프린트 티셔츠 보여줘")

    assert any("black printed t-shirt" == query for query in queries)
    assert any("black printed tshirts" == query for query in queries)


def test_build_keyword_queries_add_dark_blue_variant_for_navy_striped_shirt() -> None:
    queries = _build_keyword_queries("남색 스트라이프 셔츠 추천해줘")

    assert any("navy blue striped shirt" == query for query in queries)
    assert any("dark blue striped shirt" == query for query in queries)


def test_build_keyword_queries_add_training_backpack_variants() -> None:
    queries = _build_keyword_queries("검은색 트레이닝 백팩 추천해줘")

    assert any("black training backpack" == query for query in queries)
    assert any("black trng backpack" == query for query in queries)


def test_score_discovery_phrase_bonus_prefers_exact_formal_shoe_title() -> None:
    query = "검은색 정장 구두 추천해줘"
    exact_match = {
        "name": "Buckaroo Men Moles Black Formal Shoes",
        "category": "구두",
        "color": "Black",
    }
    weak_match = {
        "name": "Puma Men Metamostro Black Shoes",
        "category": "캐주얼화",
        "color": "Black",
    }

    assert _score_discovery_phrase_bonus(query, exact_match) > _score_discovery_phrase_bonus(
        query, weak_match
    )


def test_parse_llm_ranked_product_ids_reads_json_array() -> None:
    content = "[9041, 22126, 30260]"

    ranked_ids = _parse_llm_ranked_product_ids(content, {9041, 22126, 30260, 99999})

    assert ranked_ids == [9041, 22126, 30260]


def test_llm_rerank_products_reorders_head_with_mock_llm(monkeypatch) -> None:
    class FakeLLM:
        def invoke(self, messages):
            class Response:
                content = "[4585, 7056, 20938]"
            return Response()

    monkeypatch.setattr(
        "chatbot.src.tools.recommendation_tools._get_discovery_rerank_llm",
        lambda: FakeLLM(),
    )

    product_ids = [7056, 20938, 4585, 51330]
    products = [
        {"id": 7056, "name": "Nike Unisex Trng Max Black Backpack", "category": "백팩", "color": "Black"},
        {"id": 20938, "name": "Fastrack Men Leatherette Black Backpack", "category": "백팩", "color": "Black"},
        {"id": 4585, "name": "Wildcraft Unisex Black Solid Backpack", "category": "백팩", "color": "Black"},
        {"id": 51330, "name": "Wildcraft Unisex Black Rain Cover for Backpacks", "category": "기타", "color": "Black"},
    ]

    reranked_ids, reranked_products = _llm_rerank_products("검은색 백팩 추천해줘", product_ids, products)

    assert reranked_ids[:3] == [4585, 7056, 20938]
    assert [product["id"] for product in reranked_products[:3]] == [4585, 7056, 20938]


def test_extract_query_slots_structures_discovery_query() -> None:
    slots = _extract_query_slots("검은 캔버스 캐주얼 신발 추천해줘")

    assert slots["colors"] == ["black"]
    assert "캐주얼 신발" in slots["target_terms"]
    assert "casual" in slots["usage_tokens"]
    assert "canvas" in slots["materials"]


def test_extract_query_slots_prefers_tshirt_over_nested_shirt_term() -> None:
    slots = _extract_query_slots("검은 프린트 티셔츠 보여줘")

    assert slots["target_terms"][0] == "티셔츠"


def test_extract_product_slots_structures_backpack_features() -> None:
    product = {
        "name": "Wildcraft Unisex Green Printed Backpack",
        "category": "백팩",
        "color": "Green",
    }

    slots = _extract_product_slots(product)

    assert "백팩" in slots["categories"]
    assert "green" in slots["colors"]
    assert "printed" in slots["patterns"]
    assert slots["subtype"] == "printed_backpack"


def test_score_discovery_slot_alignment_prefers_plain_backpack_for_generic_query() -> None:
    query = "검은색 백팩 추천해줘"
    plain = {
        "name": "Wildcraft Unisex Black Solid Backpack",
        "category": "백팩",
        "color": "Black",
    }
    training = {
        "name": "Nike Unisex Trng Max Black Backpack",
        "category": "백팩",
        "color": "Black",
    }

    assert _score_discovery_slot_alignment(query, plain) > _score_discovery_slot_alignment(
        query, training
    )


def test_score_discovery_slot_alignment_prefers_plain_tshirt_over_polo_for_generic_query() -> None:
    query = "남색 티셔츠 추천해줘"
    plain = {
        "name": "ADIDAS Men Navy Blue T-shirt",
        "category": "티셔츠",
        "color": "Navy Blue",
    }
    polo = {
        "name": "Proline Men Navy Polo T-shirt",
        "category": "티셔츠",
        "color": "Navy Blue",
    }

    assert _score_discovery_slot_alignment(query, plain) > _score_discovery_slot_alignment(
        query, polo
    )


def test_build_slot_variant_uses_structured_slots() -> None:
    variant = _build_slot_variant("보라색 줄무늬 셔츠 찾아줘")

    assert "purple" in variant
    assert "shirt" in variant
    assert "striped" in variant


def test_normalize_discovery_query_maps_holdout_synonyms_to_canonical_terms() -> None:
    normalized = _normalize_discovery_query("검은 정장화랑 파란 배낭 보여줘")

    assert "구두" in normalized
    assert "백팩" in normalized


def test_extract_query_slots_recognizes_duffle_style_bag_expression() -> None:
    slots = _extract_query_slots("회색 더플 스타일 가방 찾아줘")

    assert "더플백" in slots["target_terms"]
    assert "duffle bag" in slots["category_synonyms"]


def test_build_query_variants_prioritizes_normalized_and_exact_phrase_queries() -> None:
    variants = _build_query_variants("검은 정장화 추천해줘")

    assert variants[0] == "검은 구두 추천해줘"
    assert any("black formal shoes" in variant for variant in variants)


def test_translate_discovery_query_handles_additional_korean_modifiers() -> None:
    translated = _translate_discovery_query("하늘색 폴로 티셔츠 보여줘")

    assert "aqua" in translated
    assert "polo t-shirt" in translated


def test_score_discovery_adjustment_prefers_matching_category_and_color() -> None:
    query = "검은색 백팩 추천해줘"
    matching_product = {
        "name": "Wildcraft Unisex Black Solid Backpack",
        "category": "백팩",
        "color": "Black",
    }
    mismatching_product = {
        "name": "Facit Men Grey Comfort Briefs",
        "category": "브리프",
        "color": "Grey",
    }

    assert (
        _score_discovery_adjustment(query, matching_product)
        > _score_discovery_adjustment(query, mismatching_product)
    )


def test_score_discovery_adjustment_penalizes_non_matching_category_even_when_color_matches() -> None:
    query = "여행 갈 때 멜 파란 배낭 있어?"
    backpack = {
        "name": "Wildcraft Unisex Blue & Grey Rucksack",
        "category": "백팩",
        "color": "Blue",
    }
    mascara = {
        "name": "Streetwear Blue Mascara 02",
        "category": "마스카라",
        "color": "Blue",
    }

    assert _score_discovery_adjustment(query, backpack) > _score_discovery_adjustment(
        query, mascara
    )


def test_score_discovery_adjustment_penalizes_waist_pouch_for_backpack_query() -> None:
    query = "회색 백팩 보여줘"
    backpack = {
        "name": "Wildcraft Unisex Grey Backpack",
        "category": "백팩",
        "color": "Grey",
    }
    waist_pouch = {
        "name": "Wildcraft Unisex Grey waist pouch",
        "category": "힙색",
        "color": "Grey",
    }

    assert _score_discovery_adjustment(query, backpack) > _score_discovery_adjustment(
        query, waist_pouch
    )


def test_score_discovery_adjustment_prefers_matching_color_backpack() -> None:
    query = "회색 백팩 보여줘"
    grey_backpack = {
        "name": "Wildcraft Unisex Grey Backpack",
        "category": "백팩",
        "color": "Grey",
    }
    black_backpack = {
        "name": "Wildcraft Unisex Black Solid Backpack",
        "category": "백팩",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, grey_backpack) > _score_discovery_adjustment(
        query, black_backpack
    )


def test_score_discovery_adjustment_prefers_plain_backpack_for_generic_backpack_query() -> None:
    query = "검은색 백팩 추천해줘"
    plain_backpack = {
        "name": "Wildcraft Unisex Black Solid Backpack",
        "category": "백팩",
        "color": "Black",
    }
    training_backpack = {
        "name": "Nike Unisex Trng Max Black Backpack",
        "category": "백팩",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, plain_backpack) > _score_discovery_adjustment(
        query, training_backpack
    )


def test_score_discovery_adjustment_penalizes_leatherette_backpack_for_generic_query() -> None:
    query = "검은색 백팩 추천해줘"
    plain_backpack = {
        "name": "Wildcraft Unisex Black Solid Backpack",
        "category": "백팩",
        "color": "Black",
    }
    leatherette_backpack = {
        "name": "Fastrack Men Leatherette Black Backpack",
        "category": "백팩",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, plain_backpack) > _score_discovery_adjustment(
        query, leatherette_backpack
    )


def test_score_discovery_adjustment_prefers_plain_backpack_over_printed_for_generic_query() -> None:
    query = "주황색 백팩 보여줘"
    plain_backpack = {
        "name": "Peter England Unisex Orange Backpack",
        "category": "백팩",
        "color": "Orange",
    }
    printed_backpack = {
        "name": "Wildcraft Unisex Orange Printed Backpack",
        "category": "백팩",
        "color": "Orange",
    }

    assert _score_discovery_adjustment(query, plain_backpack) > _score_discovery_adjustment(
        query, printed_backpack
    )


def test_score_discovery_adjustment_prefers_printed_backpack_when_query_mentions_printed() -> None:
    query = "초록색 프린트 백팩 찾아줘"
    printed_backpack = {
        "name": "Wildcraft Unisex Green Printed Backpack",
        "category": "백팩",
        "color": "Green",
    }
    rucksack = {
        "name": "Wildcraft Unisex Green & Grey Rucksack",
        "category": "등산 백팩",
        "color": "Green",
    }

    assert _score_discovery_adjustment(query, printed_backpack) > _score_discovery_adjustment(
        query, rucksack
    )


def test_score_discovery_adjustment_prefers_rucksack_for_hiking_backpack_query() -> None:
    query = "빨간색 등산 백팩 보여줘"
    rucksack = {
        "name": "Wildcraft Unisex Red & Grey Rucksack",
        "category": "백팩",
        "color": "Red",
    }
    regular_backpack = {
        "name": "Wildcraft Unisex Red Backpack",
        "category": "백팩",
        "color": "Red",
    }

    assert _score_discovery_adjustment(query, rucksack) > _score_discovery_adjustment(
        query, regular_backpack
    )


def test_score_discovery_adjustment_prefers_multicolor_backpack_when_query_mentions_two_colors() -> None:
    query = "회색에 주황 포인트 있는 백팩 보여줘"
    multicolor_backpack = {
        "name": "Wildcraft Unisex Grey & Orange Rucksack",
        "category": "백팩",
        "color": "Grey Orange",
    }
    grey_backpack = {
        "name": "Wildcraft Unisex Grey Backpack",
        "category": "백팩",
        "color": "Grey",
    }

    assert _score_discovery_adjustment(query, multicolor_backpack) > _score_discovery_adjustment(
        query, grey_backpack
    )


def test_score_discovery_adjustment_prefers_leatherette_backpack_for_leather_query() -> None:
    query = "검은 가죽 느낌 백팩 찾아줘"
    leatherette_backpack = {
        "name": "Fastrack Men Leatherette Black Backpack",
        "category": "백팩",
        "color": "Black",
    }
    plain_backpack = {
        "name": "Wildcraft Unisex Black Solid Backpack",
        "category": "백팩",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, leatherette_backpack) > _score_discovery_adjustment(
        query, plain_backpack
    )


def test_score_discovery_adjustment_penalizes_messenger_bag_for_backpack_query() -> None:
    query = "검은색 백팩 추천해줘"
    backpack = {
        "name": "Wildcraft Unisex Black Solid Backpack",
        "category": "백팩",
        "color": "Black",
    }
    messenger_bag = {
        "name": "Peter England Unisex Black Messenger Bag",
        "category": "메신저백",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, backpack) > _score_discovery_adjustment(
        query, messenger_bag
    )


def test_score_discovery_adjustment_prefers_gym_bag_for_sports_bag_query() -> None:
    query = "검은색 운동 가방 추천해줘"
    gym_bag = {
        "name": "Fastrack Men Black Gym Bag",
        "category": "더플백",
        "color": "Black",
    }
    laptop_bag = {
        "name": "Nike Unisex Allegian Black Laptop Bag",
        "category": "노트북 가방",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, gym_bag) > _score_discovery_adjustment(
        query, laptop_bag
    )


def test_score_discovery_adjustment_prefers_tshirt_over_shirt_for_tshirt_query() -> None:
    query = "흰색 티셔츠 찾아줘"
    tshirt = {
        "name": "Puma Men White T-shirt",
        "category": "티셔츠",
        "color": "White",
    }
    shirt = {
        "name": "Arrow Men White Shirt",
        "category": "셔츠",
        "color": "White",
    }

    assert _score_discovery_adjustment(query, tshirt) > _score_discovery_adjustment(
        query, shirt
    )


def test_score_discovery_adjustment_prefers_plain_tshirt_over_polo_for_generic_tshirt_query() -> None:
    query = "남색 티셔츠 추천해줘"
    plain_tshirt = {
        "name": "ADIDAS Men Navy Blue T-shirt",
        "category": "티셔츠",
        "color": "Navy Blue",
    }
    polo_tshirt = {
        "name": "Proline Men Navy Polo T-shirt",
        "category": "티셔츠",
        "color": "Navy Blue",
    }

    assert _score_discovery_adjustment(query, plain_tshirt) > _score_discovery_adjustment(
        query, polo_tshirt
    )


def test_score_discovery_adjustment_prefers_striped_shirt_over_muffler() -> None:
    query = "보라색 줄무늬 셔츠 찾아줘"
    striped_shirt = {
        "name": "Peter England Men Stripes Purple Shirt",
        "category": "셔츠",
        "color": "Purple",
    }
    muffler = {
        "name": "Proline White Striped Muffler",
        "category": "머플러",
        "color": "White",
    }

    assert _score_discovery_adjustment(query, striped_shirt) > _score_discovery_adjustment(
        query, muffler
    )


def test_score_discovery_adjustment_prefers_checked_shirt_over_boys_shirt() -> None:
    query = "빨간 체크 셔츠 찾아줘"
    adult_checked_shirt = {
        "name": "United Colors of Benetton Men Check Red Shirts",
        "category": "셔츠",
        "color": "Red",
    }
    boys_checked_shirt = {
        "name": "Gini and Jony Boys Check Red Shirt",
        "category": "셔츠",
        "color": "Red",
    }

    assert _score_discovery_adjustment(query, adult_checked_shirt) > _score_discovery_adjustment(
        query, boys_checked_shirt
    )


def test_score_discovery_adjustment_prefers_polo_tshirt_over_tunic() -> None:
    query = "주황색 폴로 티셔츠 추천해줘"
    polo = {
        "name": "Basics Men Orange & White Polo T-shirt",
        "category": "티셔츠",
        "color": "White",
    }
    tunic = {
        "name": "Mineral Women Orange Tunic",
        "category": "튜닉",
        "color": "Orange",
    }

    assert _score_discovery_adjustment(query, polo) > _score_discovery_adjustment(
        query, tunic
    )


def test_score_discovery_adjustment_prefers_exact_polo_over_generic_tshirt() -> None:
    query = "검은 폴로 티셔츠 추천해줘"
    polo = {
        "name": "Nike Men Club Pique Black Polo T-shirt",
        "category": "티셔츠",
        "color": "Black",
    }
    tshirt = {
        "name": "Angry Birds Men Black T-shirt",
        "category": "티셔츠",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, polo) > _score_discovery_adjustment(
        query, tshirt
    )


def test_score_discovery_adjustment_prefers_exact_checked_shirt_over_plain_shirt() -> None:
    query = "빨간 체크 셔츠 찾아줘"
    checked_shirt = {
        "name": "United Colors of Benetton Men Check Red Shirts",
        "category": "셔츠",
        "color": "Red",
    }
    plain_shirt = {
        "name": "Provogue Men Eternity Red Shirt",
        "category": "셔츠",
        "color": "Red",
    }

    assert _score_discovery_adjustment(query, checked_shirt) > _score_discovery_adjustment(
        query, plain_shirt
    )


def test_score_discovery_adjustment_prefers_adult_checked_shirt_over_boys_checked_shirt() -> None:
    query = "빨간 체크 셔츠 찾아줘"
    adult_checked_shirt = {
        "name": "United Colors of Benetton Men Check Red Shirts",
        "category": "셔츠",
        "color": "Red",
    }
    boys_checked_shirt = {
        "name": "Gini and Jony Boys Check Red Shirt",
        "category": "셔츠",
        "color": "Red",
    }

    assert _score_discovery_adjustment(query, adult_checked_shirt) > _score_discovery_adjustment(
        query, boys_checked_shirt
    )


def test_score_discovery_adjustment_prefers_adult_jeans_over_kids_jeans() -> None:
    query = "검은색 청바지 찾아줘"
    adult_jeans = {
        "name": "United Colors of Benetton Women Denim Black Jeans",
        "category": "청바지",
        "color": "Black",
    }
    kids_jeans = {
        "name": "Palm Tree Boys Solid Black Jeans",
        "category": "청바지",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, adult_jeans) > _score_discovery_adjustment(
        query, kids_jeans
    )


def test_score_discovery_adjustment_prefers_capris_for_capri_pants_query() -> None:
    query = "검은색 카프리 바지 추천해줘"
    capris = {
        "name": "ADIDAS Men's Long Black Capris",
        "category": "트레이닝 바지",
        "color": "Black",
    }
    lounge_pants = {
        "name": "Hanes Men Black Lounge Pant",
        "category": "라운지 팬츠",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, capris) > _score_discovery_adjustment(
        query, lounge_pants
    )


def test_score_discovery_adjustment_prefers_sleeveless_dress_over_camisole() -> None:
    query = "핑크색 민소매 원피스 보여줘"
    dress = {
        "name": "Forever New Women Pink Sleeveless Dress",
        "category": "드레스",
        "color": "Pink",
    }
    camisole = {
        "name": "Jockey Pink Camisole",
        "category": "캐미솔",
        "color": "Pink",
    }

    assert _score_discovery_adjustment(query, dress) > _score_discovery_adjustment(
        query, camisole
    )


def test_score_discovery_adjustment_prefers_printed_tshirt_over_sweatshirt() -> None:
    query = "회색 프린트 티셔츠 추천해줘"
    printed_tshirt = {
        "name": "Inkfruit Men Grey Melange Printed T-shirt",
        "category": "티셔츠",
        "color": "Grey Melange",
    }
    sweatshirt = {
        "name": "Quechua Men Warm Fleece Grey Sweatshirt",
        "category": "맨투맨",
        "color": "Grey",
    }

    assert _score_discovery_adjustment(query, printed_tshirt) > _score_discovery_adjustment(
        query, sweatshirt
    )


def test_score_discovery_adjustment_prefers_adult_printed_tshirt_over_boys_variant() -> None:
    query = "회색 프린트 티셔츠 추천해줘"
    adult_tshirt = {
        "name": "Inkfruit Men Grey Melange Printed T-shirt",
        "category": "티셔츠",
        "color": "Grey Melange",
    }
    boys_tshirt = {
        "name": "Avengers Boys Grey Printed T-shirt",
        "category": "티셔츠",
        "color": "Grey Melange",
    }

    assert _score_discovery_adjustment(query, adult_tshirt) > _score_discovery_adjustment(
        query, boys_tshirt
    )


def test_score_discovery_adjustment_prefers_single_color_sports_shoes() -> None:
    query = "파란색 스포츠화 추천해줘"
    single_color = {
        "name": "ADIDAS Men CC Oscillate M Blue Sports Shoes",
        "category": "스포츠화",
        "color": "Blue",
    }
    multicolor = {
        "name": "Puma Women Faas 300 Blue & Pink Sports Shoes",
        "category": "스포츠화",
        "color": "Blue",
    }

    assert _score_discovery_adjustment(query, single_color) > _score_discovery_adjustment(
        query, multicolor
    )


def test_score_discovery_adjustment_prefers_sports_shoes_over_teens_casual_for_sports_query() -> None:
    query = "검은색 스포츠화 추천해줘"
    sports_shoes = {
        "name": "Nike Men Ballista Black Sports Shoes",
        "category": "운동화",
        "color": "Black",
    }
    teens_casual = {
        "name": "Enroute Teens Black Shoes",
        "category": "캐주얼 신발",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, sports_shoes) > _score_discovery_adjustment(
        query, teens_casual
    )


def test_score_discovery_adjustment_prefers_canvas_casual_shoes_for_canvas_query() -> None:
    query = "검은 캔버스 캐주얼 신발 추천해줘"
    canvas_shoes = {
        "name": "Converse Men Black CT Lace Color Hi Canvas Shoes",
        "category": "캐주얼 신발",
        "color": "Black",
    }
    sports_shoes = {
        "name": "Nike Men Black Sports Shoes",
        "category": "운동화",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, canvas_shoes) > _score_discovery_adjustment(
        query, sports_shoes
    )


def test_score_discovery_adjustment_penalizes_camisole_for_tshirt_query() -> None:
    query = "흰색 티셔츠 찾아줘"
    tshirt = {
        "name": "Lee Women's White T-shirt",
        "category": "티셔츠",
        "color": "White",
    }
    camisole = {
        "name": "Hanes Women White Camisole",
        "category": "이너웨어",
        "color": "White",
    }

    assert _score_discovery_adjustment(query, tshirt) > _score_discovery_adjustment(
        query, camisole
    )


def test_score_discovery_adjustment_penalizes_sweatshirt_for_tshirt_query() -> None:
    query = "검은 프린트 티셔츠 보여줘"
    tshirt = {
        "name": "Angry Birds Men Black Printed T-shirt",
        "category": "티셔츠",
        "color": "Black",
    }
    sweatshirt = {
        "name": "Levis Men Printed Black Sweatshirt",
        "category": "맨투맨",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, tshirt) > _score_discovery_adjustment(
        query, sweatshirt
    )


def test_score_discovery_adjustment_prefers_kurta_over_kurta_set() -> None:
    query = "검은 쿠르타 추천해줘"
    kurta = {
        "name": "Vishudh Women Small Flower Print Black Kurtas",
        "category": "쿠르타",
        "color": "Black",
    }
    kurta_set = {
        "name": "Biba Women Black Printed Kurta with Dupatta",
        "category": "쿠르타 세트",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, kurta) > _score_discovery_adjustment(
        query, kurta_set
    )


def test_score_discovery_adjustment_prefers_dark_grey_waistcoat_for_dark_grey_query() -> None:
    query = "진회색 조끼 추천해줘"
    dark_grey = {
        "name": "Scullers Men Dark Grey Waistcoat",
        "category": "조끼",
        "color": "Dark Grey",
    }
    grey = {
        "name": "Scullers Men Grey Waistcoat",
        "category": "조끼",
        "color": "Grey",
    }

    assert _score_discovery_adjustment(query, dark_grey) > _score_discovery_adjustment(
        query, grey
    )


def test_score_discovery_adjustment_prefers_plain_jacket_over_sleeveless_variant() -> None:
    query = "검은 남성 자켓 추천해줘"
    plain_jacket = {
        "name": "Just Natural Men Black Jacket",
        "category": "자켓",
        "color": "Black",
    }
    sleeveless_jacket = {
        "name": "Fabindia Men Black Sleeveless Jacket",
        "category": "자켓",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, plain_jacket) > _score_discovery_adjustment(
        query, sleeveless_jacket
    )


def test_score_discovery_adjustment_prefers_plain_blue_jacket_over_sleeveless_nehru() -> None:
    query = "파란색 남성 자켓 보여줘"
    plain_jacket = {
        "name": "ADIDAS Men Solid Blue Jacket",
        "category": "자켓",
        "color": "Blue",
    }
    nehru_jacket = {
        "name": "Fabindia Men Reversible Blue Sleeveless Jacket",
        "category": "네루 재킷",
        "color": "Blue",
    }

    assert _score_discovery_adjustment(query, plain_jacket) > _score_discovery_adjustment(
        query, nehru_jacket
    )


def test_score_discovery_adjustment_prefers_plain_dress_over_kids_printed_dress() -> None:
    query = "파란색 원피스 추천해줘"
    women_dress = {
        "name": "Femella Women Blue Dress",
        "category": "원피스",
        "color": "Blue",
    }
    girls_printed_dress = {
        "name": "Gini and Jony Girls Printed Teal Dress",
        "category": "원피스",
        "color": "Blue",
    }

    assert _score_discovery_adjustment(query, women_dress) > _score_discovery_adjustment(
        query, girls_printed_dress
    )


def test_score_discovery_adjustment_prefers_black_formal_over_brown_formal_for_black_query() -> None:
    query = "검은색 정장 구두 추천해줘"
    black_formal = {
        "name": "Buckaroo Men Black Formal Shoes",
        "category": "구두",
        "color": "Black",
    }
    brown_formal = {
        "name": "Provogue Men Brown Formal Shoes",
        "category": "구두",
        "color": "Brown",
    }

    assert _score_discovery_adjustment(query, black_formal) > _score_discovery_adjustment(
        query, brown_formal
    )


def test_score_discovery_adjustment_prefers_exact_formal_shoe_over_generic_black_shoe() -> None:
    query = "검은색 정장 구두 추천해줘"
    formal = {
        "name": "Buckaroo Men Moles Black Formal Shoes",
        "category": "구두",
        "color": "Black",
    }
    generic = {
        "name": "Puma Men Metamostro Black Shoes",
        "category": "캐주얼화",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, formal) > _score_discovery_adjustment(
        query, generic
    )


def test_score_discovery_adjustment_prefers_exact_formal_shoe_over_generic_black_shoe() -> None:
    query = "검은색 정장 구두 추천해줘"
    formal = {
        "name": "Buckaroo Men Moles Black Formal Shoes",
        "category": "구두",
        "color": "Black",
    }
    generic = {
        "name": "Puma Men Metamostro Black Shoes",
        "category": "캐주얼화",
        "color": "Black",
    }

    assert _score_discovery_adjustment(query, formal) > _score_discovery_adjustment(
        query, generic
    )


def test_score_discovery_adjustment_prefers_exact_grey_waistcoat_over_dark_grey_for_generic_query() -> None:
    query = "회색 조끼 보여줘"
    grey = {
        "name": "Scullers Men Grey Waistcoat",
        "category": "조끼",
        "color": "Grey",
    }
    dark_grey = {
        "name": "Scullers Men Dark Grey Waistcoat",
        "category": "조끼",
        "color": "Grey",
    }

    assert _score_discovery_adjustment(query, grey) > _score_discovery_adjustment(
        query, dark_grey
    )


def test_score_discovery_adjustment_prefers_multicolor_dress_for_two_color_query() -> None:
    query = "흰색이랑 파란색 원피스 찾아줘"
    multicolor = {
        "name": "Palm Tree Girls Beyonce White & Blue Dress",
        "category": "드레스",
        "color": "White",
    }
    white_only = {
        "name": "Gini and Jony Girls White Dress",
        "category": "드레스",
        "color": "White",
    }

    assert _score_discovery_adjustment(query, multicolor) > _score_discovery_adjustment(
        query, white_only
    )


def test_should_direct_text_search_for_specific_product_query() -> None:
    assert _should_direct_text_search("검은색 백팩 추천해줘") is True
