import os
import pandas as pd
from typing import List, Optional
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from ecommerce.platform.backend.app.database import SessionLocal
from ecommerce.platform.backend.app.models import User
from ecommerce.platform.backend.app.router.products import crud as product_crud
from ecommerce.chatbot.src.tools.image_search_tools import search_similar_images_from_bytes

# Path to the sampled dataset
DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "processed",
    "fashion-1000-balanced",
    "sampled_styles.csv",
)

# Global dataframe cache
_DF_CACHE = None


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
    [중요] 사용자가 어떤 카테고리(상의, 하의, 아우터, 속옷, 신발 등)를 찾는지 불명확한 경우 (예: "파티복 추천해줘")
    이 도구를 호출하지 말고 사용자에게 어떤 옷의 종류를 찾는지 먼저 질문하세요.

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
        "ui_data": results,
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
            payloads.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "price": float(product.price),
                    "category": category,
                    "color": color,
                    "season": None,
                }
            )
        return payloads
    finally:
        db.close()


@tool
def search_by_image(image_bytes: bytes, top_k: int = 5) -> dict:
    """
    CLIP/FAISS를 활용해 업로드된 이미지와 유사한 상품을 추천합니다.
    """

    if not isinstance(image_bytes, (bytes, bytearray)):
        return {"error": "이미지 바이트 데이터를 전달해주세요."}

    try:
        product_ids = search_similar_images_from_bytes(image_bytes, top_k)
        print("FAISS SEARCH RESULT:", product_ids)
        products = _build_product_payloads(product_ids)
        return {
            "ui_action": "show_product_list",
            "product_ids": product_ids,
            "products": products,
        }
    except Exception as e:
        print("IMAGE SEARCH ERROR:", e)
        return {"error": f"이미지 검색 실패: {str(e)}"}
