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
    _build_focused_variant,
    _build_query_variants,
    _score_discovery_adjustment,
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
    assert any(variant == "pink track pants" for variant in variants)
    assert any("track pants" in variant for variant in variants)


def test_build_focused_variant_prefers_compact_search_phrase() -> None:
    assert _build_focused_variant("회색 백팩 보여줘") == "grey backpack"


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


def test_should_direct_text_search_for_specific_product_query() -> None:
    assert _should_direct_text_search("검은색 백팩 추천해줘") is True
