"""
상품 크롤링 스크립트
올리브영 상품 페이지에서 카테고리별 상품 정보를 크롤링합니다.

사용법: python product_crawling.py

사전 설치:
  pip install curl_cffi
"""
import sys
import os
import time

# backend 디렉토리를 path에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from models import get_connection

from curl_cffi import requests as curl_requests
from html.parser import HTMLParser


# ===== HTTP 세션 =====

def get_session() -> curl_requests.Session:
    """Chrome TLS 지문을 흉내내는 세션을 반환합니다."""
    session = curl_requests.Session(impersonate="chrome")
    return session


def fetch_html(session: curl_requests.Session, url: str) -> str:
    """세션으로 HTML을 가져옵니다."""
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code == 200 and len(resp.text) > 1000:
            return resp.text
        print(f"  [fetch] 응답 코드: {resp.status_code}, 길이: {len(resp.text)}")
    except Exception as e:
        print(f"  [fetch] 요청 실패: {e}")
    return ""


class ProductHTMLParser(HTMLParser):
    """올리브영 상품 리스트 HTML을 파싱합니다."""

    def __init__(self):
        super().__init__()
        self.products = []
        self._current = {}
        self._in_flag = False
        self._capture = None  # "name", "brand", "price"
        self._text_buf = ""

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        cls = attr.get("class", "")
        if tag == "li" and "flag" in cls:
            self._in_flag = True
            self._current = {"name": "", "brand": "", "price": 0,
                             "description": "", "image_url": "", "stock": 100}
        if not self._in_flag:
            return
        if "tx_name" in cls or "prd_name" in cls:
            self._capture = "name"
            self._text_buf = ""
        elif "tx_brand" in cls or "prd_brand" in cls:
            self._capture = "brand"
            self._text_buf = ""
        elif "tx_num" in cls:
            self._capture = "price"
            self._text_buf = ""
        if tag == "img" and self._in_flag:
            src = attr.get("src", "")
            if src and not self._current.get("image_url"):
                self._current["image_url"] = src

    def handle_data(self, data):
        if self._capture:
            self._text_buf += data.strip()

    def handle_endtag(self, tag):
        if self._capture and self._text_buf:
            if self._capture == "price":
                price_text = self._text_buf.replace(",", "")
                self._current["price"] = int(price_text) if price_text.isdigit() else 0
            else:
                self._current[self._capture] = self._text_buf
            self._capture = None
            self._text_buf = ""
        if tag == "li" and self._in_flag:
            if self._current.get("name"):
                self.products.append(self._current)
            self._current = {}
            self._in_flag = False


# ===== DB 저장 =====

def insert_product_batch(product_list: list[dict]) -> int:
    """상품 데이터를 일괄 삽입합니다. 이름+브랜드 기준 중복은 무시합니다.

    Args:
        product_list: [{"name", "brand", "price", "description", "image_url", "category", "stock"}, ...] 형태의 리스트

    Returns:
        신규 삽입 건수
    """
    conn = get_connection()
    cursor = conn.cursor()
    inserted = 0
    try:
        for product in product_list:
            cursor.execute("""
                MERGE INTO products p
                USING (SELECT :name AS name, :brand AS brand FROM dual) d
                ON (p.name = d.name AND p.brand = d.brand)
                WHEN NOT MATCHED THEN
                    INSERT (name, brand, price, description, image_url, category, stock)
                    VALUES (:name, :brand, :price, :description, :image_url, :category, :stock)
            """, {
                "name": product["name"],
                "brand": product["brand"],
                "price": product["price"],
                "description": product.get("description", ""),
                "image_url": product.get("image_url", ""),
                "category": product.get("category", ""),
                "stock": product.get("stock", 0),
            })
            inserted += cursor.rowcount
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return inserted


# ===== 올리브영 상품 크롤링 =====

# 스킨케어 서브카테고리 (왼쪽 사이드바 7개)
SUBCATEGORIES = [
    "스킨/토너",
    "에센스/세럼/앰플",
    "크림",
    "로션",
    "미스트/오일",
    "스킨케어세트",
    "스킨케어 디바이스",
]

MAX_PRODUCTS_PER_CATEGORY = 20  # 카테고리당 최대 수집 상품 수

# 서브카테고리별 URL
SUBCATEGORY_URLS = {
    "스킨/토너": "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100010013&isLoginCnt=1&aShowCnt=0&bShowCnt=0&cShowCnt=0&trackingCd=Cat100000100010013_MID&trackingCd=Cat100000100010013_MID&t_page=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EA%B4%80&t_click=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EC%83%81%EC%84%B8_%EC%A4%91%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC&t_1st_category_type=%EB%8C%80_%EC%8A%A4%ED%82%A8%EC%BC%80%EC%96%B4&t_2nd_category_type=%EC%A4%91_%EC%8A%A4%ED%82%A8%2F%ED%86%A0%EB%84%88",
    "에센스/세럼/앰플": "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100010014&isLoginCnt=2&aShowCnt=0&bShowCnt=0&cShowCnt=0&trackingCd=Cat100000100010014_MID&trackingCd=Cat100000100010014_MID&t_page=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EA%B4%80&t_click=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EC%83%81%EC%84%B8_%EC%A4%91%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC&t_1st_category_type=%EB%8C%80_%EC%8A%A4%ED%82%A8%EC%BC%80%EC%96%B4&t_2nd_category_type=%EC%A4%91_%EC%97%90%EC%84%BC%EC%8A%A4%2F%EC%84%B8%EB%9F%BC%2F%EC%95%B0%ED%94%8C",
    "크림": "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100010015&isLoginCnt=3&aShowCnt=0&bShowCnt=0&cShowCnt=0&trackingCd=Cat100000100010015_MID&trackingCd=Cat100000100010015_MID&t_page=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EA%B4%80&t_click=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EC%83%81%EC%84%B8_%EC%A4%91%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC&t_1st_category_type=%EB%8C%80_%EC%8A%A4%ED%82%A8%EC%BC%80%EC%96%B4&t_2nd_category_type=%EC%A4%91_%ED%81%AC%EB%A6%BC",
    "로션": "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100010016&isLoginCnt=4&aShowCnt=0&bShowCnt=0&cShowCnt=0&trackingCd=Cat100000100010016_MID&trackingCd=Cat100000100010016_MID&t_page=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EA%B4%80&t_click=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EC%83%81%EC%84%B8_%EC%A4%91%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC&t_1st_category_type=%EB%8C%80_%EC%8A%A4%ED%82%A8%EC%BC%80%EC%96%B4&t_2nd_category_type=%EC%A4%91_%EB%A1%9C%EC%85%98",
    "미스트/오일": "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100010010&isLoginCnt=5&aShowCnt=0&bShowCnt=0&cShowCnt=0&trackingCd=Cat100000100010010_MID&trackingCd=Cat100000100010010_MID&t_page=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EA%B4%80&t_click=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EC%83%81%EC%84%B8_%EC%A4%91%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC&t_1st_category_type=%EB%8C%80_%EC%8A%A4%ED%82%A8%EC%BC%80%EC%96%B4&t_2nd_category_type=%EC%A4%91_%EB%AF%B8%EC%8A%A4%ED%8A%B8%2F%EC%98%A4%EC%9D%BC",
    "스킨케어세트": "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100010017&isLoginCnt=6&aShowCnt=0&bShowCnt=0&cShowCnt=0&trackingCd=Cat100000100010017_MID&trackingCd=Cat100000100010017_MID&t_page=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EA%B4%80&t_click=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EC%83%81%EC%84%B8_%EC%A4%91%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC&t_1st_category_type=%EB%8C%80_%EC%8A%A4%ED%82%A8%EC%BC%80%EC%96%B4&t_2nd_category_type=%EC%A4%91_%EC%8A%A4%ED%82%A8%EC%BC%80%EC%96%B4%EC%84%B8%ED%8A%B8",
    "스킨케어 디바이스": "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100010018&isLoginCnt=7&aShowCnt=0&bShowCnt=0&cShowCnt=0&trackingCd=Cat100000100010018_MID&trackingCd=Cat100000100010018_MID&t_page=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EA%B4%80&t_click=%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC%EC%83%81%EC%84%B8_%EC%A4%91%EC%B9%B4%ED%85%8C%EA%B3%A0%EB%A6%AC&t_1st_category_type=%EB%8C%80_%EC%8A%A4%ED%82%A8%EC%BC%80%EC%96%B4&t_2nd_category_type=%EC%A4%91_%EC%8A%A4%ED%82%A8%EC%BC%80%EC%96%B4%20%EB%94%94%EB%B0%94%EC%9D%B4%EC%8A%A4",
}


def parse_products_from_html(html: str, max_count: int = 20) -> list[dict]:
    """HTML 문자열에서 상품 정보를 파싱합니다."""
    parser = ProductHTMLParser()
    parser.feed(html)
    return parser.products[:max_count]


def crawl_oliveyoung() -> list[dict]:
    """올리브영 스킨케어 서브카테고리별 상위 20개 상품을 크롤링합니다."""
    print("\n=== 올리브영 스킨케어 상품 크롤링 시작 ===")

    session = get_session()

    # 1단계: 메인 페이지 접속으로 쿠키 획득
    print("\n[1단계] 올리브영 메인 페이지 접속 (쿠키 획득)...")
    try:
        resp = session.get("https://www.oliveyoung.co.kr", timeout=15)
        print(f"  메인 페이지 응답: {resp.status_code}")
    except Exception as e:
        print(f"  메인 페이지 접속 실패: {e}")

    time.sleep(2)

    # 2단계: 각 서브카테고리 크롤링 (페이지네이션으로 20건 확보)
    all_products = []

    for subcategory, url in SUBCATEGORY_URLS.items():
        print(f"\n--- 서브카테고리: {subcategory} ---")

        collected = []
        page_idx = 1

        while len(collected) < MAX_PRODUCTS_PER_CATEGORY:
            paged_url = f"{url}&pageIdx={page_idx}&rowsPerPage=24"
            html = fetch_html(session, paged_url)
            if not html:
                print(f"  페이지 {page_idx}: HTML 가져오기 실패, 건너뜁니다.")
                break

            products = parse_products_from_html(html)
            if not products:
                print(f"  페이지 {page_idx}: 상품 없음, 종료")
                break

            collected.extend(products)
            print(f"  페이지 {page_idx}: {len(products)}건 파싱 (누적 {len(collected)}건)")
            page_idx += 1
            time.sleep(2)

        # 카테고리당 최대 20건까지만 사용
        collected = collected[:MAX_PRODUCTS_PER_CATEGORY]
        for product in collected:
            product["category"] = subcategory
        all_products.extend(collected)
        print(f"  최종 수집: {len(collected)}건")

    print(f"\n올리브영 스킨케어 상품 수집 완료: 총 {len(all_products)}건")
    return all_products


# ===== 메인 =====

def main():
    all_products = crawl_oliveyoung()

    # DB 저장
    if all_products:
        inserted = insert_product_batch(all_products)
        print(f"\n=== DB 저장 완료: {inserted}건 신규 삽입 (총 {len(all_products)}건 수집) ===")
    else:
        print("\n크롤링된 상품이 없습니다.")


if __name__ == "__main__":
    main()
