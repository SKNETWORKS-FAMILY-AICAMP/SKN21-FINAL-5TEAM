import os
import pandas as pd
import random
from typing import List, Dict, Optional
from langchain_core.tools import tool
from ecommerce.chatbot.src.core.config import settings

# Path to the sampled dataset
DATA_PATH = os.path.join(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
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
    preference: str,
    gender: Optional[str] = None,
    season: Optional[str] = None,
    limit: int = 3,
) -> dict:
    """
    사용자의 선호도, 성별, 계절 등을 바탕으로 옷을 추천합니다.
    챗봇이 의류나 패션 아이템을 추천할 때 사용합니다.

    Args:
        preference: 서치할 키워드 또는 선호 스타일 (ex. '캐주얼', '정장', '파란색 티셔츠' 등)
        gender: 성별 필터 ('Men', 'Women', 'Boys', 'Girls', 'Unisex') (선택사항)
        season: 계절 필터 ('Summer', 'Winter', 'Fall', 'Spring') (선택사항)
        limit: 추천할 상품 최대 개수 (기본값 3)
    """
    df = _get_dataframe()
    if df.empty:
        return {"error": "상품 데이터를 로드할 수 없습니다."}

    # 1. Base filter
    filtered = df.copy()

    # 성별 필터링
    if gender:
        # Men, Women 필터에 좀 더 다채롭게 매핑하기
        g_map = {
            "남성": "Men",
            "남자": "Men",
            "여성": "Women",
            "여자": "Women",
            "공용": "Unisex",
        }
        target_gender = g_map.get(gender, gender)
        # 대소문자 무시 검색
        filtered = filtered[
            filtered["gender"].str.contains(target_gender, case=False, na=False)
        ]

    # 계절 필터링
    if season:
        s_map = {"봄": "Spring", "여름": "Summer", "가을": "Fall", "겨울": "Winter"}
        target_season = s_map.get(season, season)
        filtered = filtered[
            filtered["season"].str.contains(target_season, case=False, na=False)
        ]

    # 2. Keyword matching on display name or usage
    if preference:
        # "파란색" -> "Blue", "원피스" -> "Dress" 와 같이 기본적인 키워드 맵핑 (선택사항)이지만,
        # 여기서는 문자열 단순 매칭으로 진행
        # 보다 정확도를 높이려면 LLM 쿼리 시 영어 키워드로 변환해달라고 프롬프트 단에서 요청할 수 있음

        pref_lower = preference.lower()

        # 키워드가 너무 길면 분절해서 찾거나 OR 조건 등을 쓸 수 있지만 단순하게 contains
        mask = (
            filtered["productDisplayName"].str.contains(
                pref_lower, case=False, na=False
            )
            | filtered["usage"].str.contains(pref_lower, case=False, na=False)
            | filtered["baseColour"].str.contains(pref_lower, case=False, na=False)
            | filtered["articleType"].str.contains(pref_lower, case=False, na=False)
        )
        keyword_filtered = filtered[mask]

        # 만약 키워드로 필터링 했을 때 결과가 하나도 없다면 필터 무시 (최소한의 추천을 위해)
        if not keyword_filtered.empty:
            filtered = keyword_filtered

    # 3. Random Sampling
    if len(filtered) == 0:
        return {"message": "조건에 맞는 상품을 찾지 못했습니다."}

    sample_size = min(len(filtered), limit)
    sampled = filtered.sample(n=sample_size)

    results = []
    for _, row in sampled.iterrows():
        results.append(
            {
                "id": int(row["id"]),
                "name": str(row["productDisplayName"]),
                "category": f"{row['masterCategory']} > {row['subCategory']} > {row['articleType']}",
                "color": str(row["baseColour"]),
                "season": str(row["season"]),
                "usage": str(row["usage"]),
            }
        )

    return {
        "success": True,
        "message": f"총 {len(results)}개의 상품을 추천합니다.",
        "recommendations": results,
    }


from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage


@tool
def search_by_image(image_url: str) -> dict:
    """
    이미지(URL)를 기반으로 해당 이미지 속 옷과 유사한 상품을 추천/검색합니다.
    """
    if not image_url:
        return {"error": "이미지 URL이 필요합니다."}

    prompt = """
    이 이미지에 있는 주요 의류(옷)의 특징을 분석해주세요.
    반드시 다음 세 가지 항목을 포함하여 쉼표로 구분해 짧게 답변해주세요.
    1. 색상 (예: 검정색, 빨간색, 파란색 등)
    2. 옷 종류/카테고리 (예: 티셔츠, 청바지, 원피스, 셔츠 등)
    3. 스타일이나 분위기 (예: 캐주얼, 포멀, 스포티 등)
    
    답변 예시: 검정색, 셔츠, 포멀
    """

    try:
        # GPT-4o-mini Vision 호출
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        response = llm.invoke(
            [
                SystemMessage(content="You are a fashion expert assistant."),
                HumanMessage(
                    content=[
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ]
                ),
            ]
        )

        # 분석된 텍스트
        features_text = response.content.strip()
        print(f"[Vision Analysis Result] {features_text}")

        # 분석된 텍스트를 recommend_clothes 도구에 그대로 넘겨서 검색
        return recommend_clothes.invoke({"preference": features_text, "limit": 5})

    except Exception as e:
        return {
            "error": f"이미지 분석 중 오류 발생 (올바른 이미지 URL인지 확인해주세요): {str(e)}"
        }
