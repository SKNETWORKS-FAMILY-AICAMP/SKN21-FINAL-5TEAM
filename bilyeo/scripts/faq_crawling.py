"""
FAQ 크롤링 스크립트
올리브영 FAQ 페이지(온라인몰)에서 카테고리별 질문 제목과 내용을 크롤링합니다.

사용법: python faq_crawling.py

사전 설치:
  pip install curl_cffi
"""
import sys
import os
import re
import time

# backend 디렉토리를 path에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from models.faq import insert_faq_batch

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
        if resp.status_code == 200 and len(resp.text) > 500:
            return resp.text
        print(f"  [fetch] 응답 코드: {resp.status_code}, 길이: {len(resp.text)}")
    except Exception as e:
        print(f"  [fetch] 요청 실패: {e}")
    return ""


# ===== HTML 파서 =====

def parse_subcategory_codes_for_tab(html: str, tab_code: str = "200") -> dict[str, str]:
    """HTML에서 특정 대분류 탭(twoTabsIdxXXX) 내 서브카테고리 코드를 추출합니다.

    Args:
        html: FAQ 페이지 전체 HTML
        tab_code: 대분류 탭 코드 (온라인몰=200)

    Returns:
        {카테고리명: 코드} 딕셔너리
    """
    # twoTabsIdx200 영역만 추출
    pattern = rf'<ul\s+class="twoTabs\s+twoTabsIdx{tab_code}">(.*?)</ul>'
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        return {}

    tab_html = match.group(1)
    # <li data-cd="XXX" data-value="카테고리명"> 추출
    items = re.findall(r'<li\s+data-cd="(\d+)"\s+data-value="([^"]+)"', tab_html)
    return {name: code for code, name in items}


class FAQHTMLParser(HTMLParser):
    """올리브영 FAQ 리스트 HTML을 파싱합니다.

    구조:
      div.list-customer > ul > li
        a.tit[data-value="질문"] > strong(카테고리)
        ul.conts > li.question > div.pdzero(답변)
    """

    def __init__(self):
        super().__init__()
        self.faqs = []
        self._in_tit = False
        self._in_strong = False
        self._in_conts = False
        self._question = ""
        self._category = ""
        self._answer_buf = ""
        self._tit_text_buf = ""

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        cls = attr.get("class", "")
        classes = cls.split()

        # a.tit - 질문 제목 링크
        if tag == "a" and "tit" in classes:
            self._in_tit = True
            self._question = attr.get("data-value", "")
            self._category = ""
            self._tit_text_buf = ""

        # strong inside a.tit - 카테고리 라벨
        if tag == "strong" and self._in_tit:
            self._in_strong = True

        # div.pdzero - 답변 본문 영역 (ul.conts > li.question > div.pdzero)
        if tag == "div" and "pdzero" in classes:
            self._in_conts = True
            self._answer_buf = ""

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return

        if self._in_strong:
            self._category = text
        elif self._in_tit:
            self._tit_text_buf += " " + text
        elif self._in_conts:
            self._answer_buf += text + "\n"

    def handle_endtag(self, tag):
        if tag == "strong" and self._in_strong:
            self._in_strong = False

        if tag == "a" and self._in_tit:
            self._in_tit = False
            # data-value가 없으면 텍스트에서 질문 추출
            if not self._question:
                q = self._tit_text_buf.strip()
                if self._category and q.startswith(self._category):
                    q = q[len(self._category):].strip()
                self._question = q

        if tag == "div" and self._in_conts:
            self._in_conts = False
            # &nbsp; 등 특수 공백 정리
            answer = self._answer_buf.replace("\xa0", " ").strip()

            if self._question:
                self.faqs.append({
                    "category": self._category,
                    "question": self._question,
                    "answer": answer,
                })
            self._question = ""
            self._category = ""
            self._answer_buf = ""


def parse_faq_items(html: str) -> list[dict]:
    """HTML에서 FAQ 항목들을 파싱합니다."""
    parser = FAQHTMLParser()
    parser.feed(html)
    return parser.faqs


def get_max_page(html: str) -> int:
    """HTML 페이지네이션에서 최대 페이지 번호를 추출합니다."""
    # data-page-no 속성에서 페이지 번호 추출
    page_nums = [int(n) for n in re.findall(r'data-page-no="(\d+)"', html)]
    if not page_nums:
        return 1
    # 현재 페이지는 <strong>으로 표시되므로 별도 추출
    current = re.findall(r'<strong[^>]*>(\d+)</strong>', html)
    page_nums.extend(int(n) for n in current)
    return max(page_nums)


# ===== 올리브영 FAQ 크롤링 =====

# 크롤링 대상 카테고리 (온라인몰 탭 내 서브카테고리)
TARGET_CATEGORIES = [
    "주문",
    "취소/교환/반품",
    "배송일정",
    "오배송",
    "분실",
    "파손",
    "회원",
    "불량",
    "유통기한",
    "오류",
]


def crawl_oliveyoung() -> list[dict]:
    """올리브영 온라인몰 FAQ를 카테고리별로 크롤링합니다."""
    print("\n=== 올리브영 FAQ 크롤링 시작 ===")

    session = get_session()

    base_url = (
        "https://www.oliveyoung.co.kr/store/counsel/getFaqList.do"
        "?faqLrclCd=200"
        "&t_page=%EA%B3%A0%EA%B0%9D%EC%84%BC%ED%84%B0&t_click=FAQ"
    )

    # 1단계: 메인 페이지 접속으로 쿠키 획득
    print("\n[1단계] 올리브영 메인 페이지 접속 (쿠키 획득)...")
    try:
        resp = session.get("https://www.oliveyoung.co.kr", timeout=15)
        print(f"  메인 페이지 응답: {resp.status_code}")
    except Exception as e:
        print(f"  메인 페이지 접속 실패: {e}")
    time.sleep(2)

    # 2단계: FAQ 기본 페이지에서 서브카테고리 코드 추출
    print("\n[2단계] FAQ 페이지에서 서브카테고리 코드 추출...")
    base_html = fetch_html(session, base_url)
    if not base_html:
        print("  FAQ 기본 페이지 로드 실패")
        return []

    subcategory_codes = parse_subcategory_codes_for_tab(base_html, "200")
    print(f"  발견된 서브카테고리: {subcategory_codes}")

    # 3단계: 각 카테고리별 크롤링
    all_faq = []

    for category_name in TARGET_CATEGORIES:
        print(f"\n--- 카테고리: {category_name} ---")

        code = subcategory_codes.get(category_name)
        if not code:
            print(f"  '{category_name}'의 서브카테고리 코드를 찾을 수 없습니다. 건너뜁니다.")
            continue

        page_num = 1
        while True:
            category_url = f"{base_url}&faqMdclCd={code}&pageIdx={page_num}"
            html = fetch_html(session, category_url)
            if not html:
                print(f"  페이지 {page_num}: HTML 가져오기 실패")
                break

            page_faq = parse_faq_items(html)
            if not page_faq:
                if page_num == 1:
                    print(f"  FAQ 항목을 찾을 수 없습니다.")
                break

            for faq in page_faq:
                faq["category"] = category_name
            all_faq.extend(page_faq)
            print(f"  페이지 {page_num}: {len(page_faq)}건 수집")

            # 다음 페이지 확인
            max_page = get_max_page(html)
            if page_num >= max_page:
                break
            page_num += 1
            time.sleep(2)

    print(f"\n올리브영 FAQ 수집 완료: 총 {len(all_faq)}건")
    return all_faq


# ===== 메인 =====

def main():
    all_faq = crawl_oliveyoung()

    # DB 저장
    if all_faq:
        # dict -> (source, category, question, answer) 튜플 변환
        faq_tuples = [
            ("올리브영", faq["category"], faq["question"], faq["answer"])
            for faq in all_faq
        ]
        inserted = insert_faq_batch(faq_tuples)
        print(f"\n=== DB 저장 완료: {inserted}건 신규 삽입 (총 {len(all_faq)}건 수집) ===")
    else:
        print("\n크롤링된 FAQ가 없습니다.")


if __name__ == "__main__":
    main()
