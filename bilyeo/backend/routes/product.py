from flask import Blueprint, request, jsonify

from models.product import get_all_categories, get_all_products, get_product_by_id

product_bp = Blueprint("product", __name__)


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
    return jsonify({"products": products}), 200


@product_bp.route("/<int:product_id>", methods=["GET"])
def product_detail(product_id):
    """상품 상세 조회 API"""
    product = get_product_by_id(product_id)
    if not product:
        return jsonify({"error": "상품을 찾을 수 없습니다."}), 404

    return jsonify({"product": product}), 200
