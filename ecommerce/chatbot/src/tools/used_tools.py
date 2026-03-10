import uuid
from typing import Any
from urllib.parse import urljoin
from decimal import Decimal

import httpx
from langchain_core.tools import tool

from ecommerce.chatbot.src.core.config import settings
from ecommerce.platform.backend.app.database import SessionLocal
from ecommerce.platform.backend.app.router.products.models import (
    Category,
    UsedProductCondition,
    UsedProduct,
    UsedProductOption,
    UsedProductStatus,
)


def _call_products_api(
    path: str,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict | list:
    """products API를 여러 base/path 조합으로 호출합니다."""
    endpoint_candidates = [f"/products{path}", f"/api/v1/products{path}"]

    base_candidates: list[str] = []
    configured_base = (getattr(settings, "BACKEND_API_URL", "") or "").rstrip("/")
    if configured_base:
        base_candidates.append(configured_base)
        if configured_base.endswith(":3000"):
            base_candidates.append(configured_base[:-5] + ":8000")

    base_candidates.extend(["http://localhost:8000", "http://127.0.0.1:8000"])

    # 중복 제거 (순서 유지)
    dedup_bases: list[str] = []
    for base in base_candidates:
        if base and base not in dedup_bases:
            dedup_bases.append(base)

    last_error: Exception | None = None

    for base in dedup_bases:
        for endpoint in endpoint_candidates:
            try:
                url = urljoin(base + "/", endpoint.lstrip("/"))
                response = httpx.request(
                    method,
                    url,
                    json=data,
                    params=params,
                    timeout=10.0,
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                last_error = e

    raise RuntimeError(f"Products API 호출 실패: {last_error}")


@tool
def open_used_sale_form() -> dict:
    """
    [CRITICAL] 중고 판매 등록 시 텍스트로 슬롯을 묻지 말고,
    반드시 이 도구를 호출해 프론트엔드 입력 폼 UI를 띄웁니다.
    """
    category_options: list[dict[str, Any]] = []
    condition_options: list[dict[str, Any]] = []

    # 1) DB 직조회 (가장 안정적)
    db = SessionLocal()
    try:
        categories = (
            db.query(Category)
            .filter(Category.is_active.is_(True))
            .order_by(Category.id.asc())
            .all()
        )
        category_options = [
            {"id": int(c.id), "name": str(c.name)}
            for c in categories
            if c.id is not None and c.name
        ]

        conditions = (
            db.query(UsedProductCondition)
            .order_by(UsedProductCondition.id.asc())
            .all()
        )
        condition_options = [
            {
                "id": int(cond.id),
                "name": str(cond.condition_name),
                "description": cond.description,
            }
            for cond in conditions
            if cond.id is not None and cond.condition_name
        ]
    except Exception:
        category_options = []
        condition_options = []
    finally:
        db.close()

    # 2) DB 실패 시 API fallback
    if not category_options or not condition_options:
        if not category_options:
            try:
                raw_categories = _call_products_api(
                    "/categories",
                    method="GET",
                    params={"is_active": True, "limit": 200},
                )
                if isinstance(raw_categories, list):
                    category_options = [
                        {
                            "id": int(item["id"]),
                            "name": str(item.get("name", "")),
                        }
                        for item in raw_categories
                        if isinstance(item, dict) and item.get("id") is not None
                    ]
            except Exception:
                category_options = []

        if not condition_options:
            try:
                raw_conditions = _call_products_api("/used/conditions", method="GET")
                if isinstance(raw_conditions, list):
                    condition_options = [
                        {
                            "id": int(item["id"]),
                            "name": str(item.get("condition_name", "")),
                            "description": item.get("description"),
                        }
                        for item in raw_conditions
                        if isinstance(item, dict) and item.get("id") is not None
                    ]
            except Exception:
                condition_options = []

    if not condition_options:
        condition_options = [
            {"id": 1, "name": "S급", "description": None},
            {"id": 2, "name": "A급", "description": None},
            {"id": 3, "name": "B급", "description": None},
        ]

    return {
        "ui_action": "show_used_sale_form",
        "message": "중고 판매 등록 정보를 입력해주세요.",
        "ui_data": {
            "category_options": category_options,
            "condition_options": condition_options,
            "category_placeholder": "예: 상의, 하의, 신발 등",
            "item_name_placeholder": "예: 나이키 후드집업",
            "description_placeholder": "상품 상태, 사용감, 하자 여부 등을 구체적으로 입력해주세요.",
            "price_placeholder": "희망 가격(선택)",
        },
    }


@tool
def register_used_sale(
    category_id: int,
    item_name: str,
    description: str,
    condition_id: int,
    expected_price: int | None = None,
    user_id: int = 1,
) -> dict:
    """
    유즈드(중고) 판매 신청을 실제 백엔드 API에 등록합니다.
    - products.used 생성
    - 기본 used option(수량 1) 생성
    """

    if not item_name.strip():
        return {"error": "상품명은 필수입니다."}
    if not description.strip():
        return {"error": "설명은 필수입니다."}
    if not category_id:
        return {"error": "카테고리를 선택해주세요."}
    if condition_id not in {1, 2, 3}:
        return {"error": "condition_id는 usedproductconditions의 ID(1,2,3) 중 하나여야 합니다."}

    price = int(expected_price) if expected_price and int(expected_price) > 0 else 1

    try:
        created = _call_products_api(
            "/used",
            method="POST",
            data={
                "category_id": int(category_id),
                "seller_id": int(user_id),
                "name": item_name.strip(),
                "description": description.strip(),
                "tags": None,
                "price": price,
                "condition_id": int(condition_id),
                "status": "PENDING",
            },
        )

        if not isinstance(created, dict) or created.get("id") is None:
            return {"error": "중고상품 생성 응답이 올바르지 않습니다."}

        used_product_id = int(created["id"])

        _call_products_api(
            f"/used/{used_product_id}/options",
            method="POST",
            data={
                "used_product_id": used_product_id,
                "size_name": None,
                "color": None,
                "quantity": 1,
                "is_active": True,
            },
        )

        tracking_id = f"USED-{str(uuid.uuid4())[:8].upper()}"
        return {
            "success": True,
            "message": (
                f"중고 판매가 성공적으로 등록되었습니다. "
                f"상품명은 '{item_name.strip()}'이며, 희망가는 {price:,}원입니다."
            ),
            "tracking_id": tracking_id,
            "used_product_id": used_product_id,
            "status": created.get("status", "PENDING"),
            "next_steps": "관리자 검수 이후 판매 상태가 업데이트됩니다.",
        }
    except Exception:
        # API 라우팅이 환경별로 다를 수 있으므로 DB fallback 경로를 제공
        db = SessionLocal()
        try:
            category = (
                db.query(Category)
                .filter(Category.id == int(category_id), Category.is_active.is_(True))
                .first()
            )
            if not category:
                return {"error": "유효한 카테고리를 찾을 수 없습니다."}

            condition = (
                db.query(UsedProductCondition)
                .filter(UsedProductCondition.id == int(condition_id))
                .first()
            )
            if not condition:
                return {"error": "유효한 상품 상태(condition_id)를 찾을 수 없습니다."}

            used_product = UsedProduct(
                category_id=int(category_id),
                seller_id=int(user_id),
                name=item_name.strip(),
                description=description.strip(),
                tags=None,
                price=Decimal(str(price)),
                condition_id=int(condition_id),
                status=UsedProductStatus.PENDING,
            )

            db.add(used_product)
            db.flush()

            used_option = UsedProductOption(
                used_product_id=int(used_product.id),
                size_name=None,
                color=None,
                quantity=1,
                is_active=True,
            )
            db.add(used_option)
            db.commit()
            db.refresh(used_product)

            tracking_id = f"USED-{str(uuid.uuid4())[:8].upper()}"
            return {
                "success": True,
                "message": (
                    f"중고 판매가 성공적으로 등록되었습니다. "
                    f"상품명은 '{item_name.strip()}'이며, 희망가는 {price:,}원입니다."
                ),
                "tracking_id": tracking_id,
                "used_product_id": int(used_product.id),
                "status": str(used_product.status.value if hasattr(used_product.status, 'value') else used_product.status),
                "next_steps": "관리자 검수 이후 판매 상태가 업데이트됩니다.",
            }
        except Exception as db_error:
            db.rollback()
            return {"error": f"중고상품 등록 실패: {str(db_error)}"}
        finally:
            db.close()


@tool
def request_pickup(
    sale_id: str,  # 판매 신청 ID
    pickup_date: str,
    pickup_address: str,
    user_id: int = 1,
) -> dict:
    """
    중고 판매 물품의 수거를 신청합니다.
    """
    if not sale_id:
        return {"error": "판매 신청 접수 번호(sale_id)가 필요합니다."}

    if not pickup_date or not pickup_address:
        return {"error": "수거 희망 날짜와 주소를 모두 입력해주세요."}

    return {
        "success": True,
        "message": f"수거 신청 완료: {pickup_date}에 '{pickup_address}'(으)로 방문 예정입니다.",
        "sale_id": sale_id,
        "status": "수거 대기중",
    }
