import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def test_promotion_judge_promotes_on_second_repeat():
    from chatbot.src.onboarding.promotion_judge import PromotionJudge

    judge = PromotionJudge(threshold=2)

    first = judge.decide(
        failure_signature="frontend_target_detection:build_artifact_selected",
        count=1,
        current_scope="run_only",
    )
    second = judge.decide(
        failure_signature="frontend_target_detection:build_artifact_selected",
        count=2,
        current_scope="run_only",
    )

    assert first["promote"] is False
    assert first["repair_scope"] == "run_only"
    assert second["promote"] is True
    assert second["repair_scope"] == "generator_promoted"


def test_promotion_judge_does_not_promote_site_local_signature():
    from chatbot.src.onboarding.promotion_judge import PromotionJudge

    decision = PromotionJudge(threshold=2).decide(
        failure_signature="response_schema_mismatch:chat-auth-token",
        count=2,
        current_scope="run_only",
    )

    assert decision["promote"] is False
    assert decision["site_local"] is True
    assert decision["repair_scope"] == "run_only"


def test_promotion_judge_blocks_generator_recommendation_below_threshold():
    from chatbot.src.onboarding.promotion_judge import PromotionJudge

    decision = PromotionJudge(threshold=2).decide(
        failure_signature="frontend_mount_violation:routes_child_violation",
        count=1,
        current_scope="run_only",
        recommendation_scope="generator_promoted",
    )

    assert decision["promote"] is False
    assert decision["repair_scope"] == "run_only"
    assert decision["recommended_scope"] == "generator_promoted"
    assert decision["reason"] == "below_promotion_threshold"


def test_promotion_judge_blocks_site_local_generator_recommendation():
    from chatbot.src.onboarding.promotion_judge import PromotionJudge

    decision = PromotionJudge(threshold=2).decide(
        failure_signature="response_schema_mismatch:chat-auth-token",
        count=2,
        current_scope="run_only",
        recommendation_scope="generator_promoted",
    )

    assert decision["promote"] is False
    assert decision["site_local"] is True
    assert decision["repair_scope"] == "run_only"
    assert decision["recommended_scope"] == "generator_promoted"
    assert decision["reason"] == "site_local_signature"
