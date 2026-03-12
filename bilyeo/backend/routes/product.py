import json
import os
from datetime import datetime

from flask import Blueprint, request, jsonify

from models.product import get_all_categories, get_all_products, get_product_by_id

product_bp = Blueprint("product", __name__)

# image_usage.json 경로 (bilyeo/scripts/image_usage.json)
_USAGE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "image_usage.json")
_CLASS_B_LIMIT = 10_000_000  # Class B 월 무료 한도


def _load_usage() -> dict:
    current_month = datetime.now().strftime("%Y-%m")
    try:
        with open(_USAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        base = data.get("base", {"class_a": 0, "class_b": 0, "storage_bytes": 0})
        if data.get("current", {}).get("month") != current_month:
            data["current"] = {
                "month": current_month,
                "class_a": base["class_a"],
                "class_b": base["class_b"],
                "storage_bytes": base["storage_bytes"],
            }
            _save_usage(data)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        data = {
            "base": {"class_a": 0, "class_b": 0, "storage_bytes": 0},
            "current": {"month": current_month, "class_a": 0, "class_b": 0, "storage_bytes": 0},
        }
        _save_usage(data)
        return data


def _save_usage(data: dict):
    with open(_USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def _check_and_increment_class_b(count: int = 1) -> bool:
    """Class B 한도 확인 후 초과 시 False, 정상이면 카운트 증가 후 True 반환."""
    data = _load_usage()
    current = data["current"]
    if current["class_b"] + count > _CLASS_B_LIMIT:
        return False
    current["class_b"] += count
    _save_usage(data)
    return True


@product_bp.route("/categories", methods=["GET"])
def list_categories():
    """카테고리 목록 조회 API"""
    categories = get_all_categories()
    return jsonify({"categories": categories}), 200


@product_bp.route("", methods=["GET"])
def list_products():
    """상품 목록 조회 API"""
    category = request.args.get("category")
    search = request.args.get("search")

    products = get_all_products(category=category, search=search)

    image_count = sum(1 for p in products if p.get("image_url"))
    if image_count > 0 and not _check_and_increment_class_b(image_count):
        return jsonify({"error": "이미지 조회 한도(월 1,000만 회)를 초과했습니다."}), 503

    return jsonify({"products": products}), 200


@product_bp.route("/<int:product_id>", methods=["GET"])
def product_detail(product_id):
    """상품 상세 조회 API"""
    product = get_product_by_id(product_id)
    if not product:
        return jsonify({"error": "상품을 찾을 수 없습니다."}), 404

    if product.get("image_url") and not _check_and_increment_class_b(1):
        return jsonify({"error": "이미지 조회 한도(월 1,000만 회)를 초과했습니다."}), 503

    return jsonify({"product": product}), 200
