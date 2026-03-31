from __future__ import annotations

from pathlib import Path


def test_refund_order_selection_does_not_inline_confirm() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "shared_widget"
        / "chatbotfab.tsx"
    ).read_text(encoding="utf-8")

    assert "선택한 주문으로 반품 접수를 진행할까요?" not in source
    assert "confirm_order_action" in source
