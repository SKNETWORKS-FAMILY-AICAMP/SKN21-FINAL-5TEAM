"""
무신사 FAQ 스크래핑 스크립트 (개선된 버전)

개선 사항:
- 클릭 대신 URL 직접 이동을 사용하여 안정성 확보
- Playwright Locator API를 적극 활용하여 요소 찾기 실패 확률 감소
- 예외 처리 강화 및 디버깅 로그 추가
"""

import asyncio
import json
import csv
from pathlib import Path
from typing import List, Dict
from datetime import datetime
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError


class MusinsaFAQScraper:
    """무신사 FAQ 스크래퍼"""
    
    # 사용자 제공 카테고리 ID 매핑 (000 ~ 006)
    CATEGORY_MAP = {
        '회원 정보': '000',
        '상품/AS 문의': '001',
        '주문/결제': '002',
        '배송': '003',
        '취소/교환/반품': '004',
        '서비스': '005',
        '이용 안내': '006'
    }
    
    def __init__(self, output_dir: str = "data/raw/musinsa_faq"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.faqs: List[Dict] = []
        
    async def scrape_all_faqs(self):
        """모든 FAQ 수집"""
        async with async_playwright() as p:
            # headless=True로 설정 (디버깅 시 변경 가능)
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={'width': 1280, 'height': 800})
            page = await context.new_page()
            
            try:
                for cat_name, cat_id in self.CATEGORY_MAP.items():
                    target_url = f"https://www.musinsa.com/cs/faq?mainCategory={cat_id}"
                    print(f"\n{'='*60}")
                    print(f"👉 [{cat_name} ({cat_id})] 이동 중: {target_url}")
                    print(f"{'='*60}")
                    
                    try:
                        # 페이지 이동 (재시도 로직 추가)
                        for attempt in range(3):
                            try:
                                await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                                break
                            except Exception as e:
                                if attempt == 2: raise e
                                print(f"      Running retry {attempt+1}/3 due to error: {e}")
                                await asyncio.sleep(2)
                        
                        await page.wait_for_timeout(3000) # 페이지 렌더링 대기
                        
                        # 소분류 탐색 없이 바로 현재 페이지(전체 리스트) 수집
                        print(f"      ▶ 메인 카테고리 전체 목록 수집")
                        await self._collect_faqs(page, cat_name, "전체")

                    except Exception as e:
                        print(f"   ❌ 카테고리 페이지 로딩 실패: {e}")
                
                print(f"\n✅ 총 {len(self.faqs)}개의 FAQ 수집 완료!")
                
            finally:
                await browser.close()



    async def _collect_faqs(self, page: Page, main_cat: str, sub_cat: str):
        """현재 뷰의 FAQ 아이템 수집 (Robust version)"""
        try:
            # 질문 버튼들 찾기 (radix ID를 가진 버튼들)
            # wait_for_selector를 사용하여 로딩 보장
            try:
                await page.wait_for_selector('button[id^="radix-"]', state="attached", timeout=10000)
            except:
                print("         (FAQ 아이템 없음)")
                return

            # 전체 개수 파악
            # all()을 쓰면 핸들이 stale될 수 있으므로 개수만 파악하고 index로 접근
            locators = page.locator('button[id^="radix-"]')
            count = await locators.count()
            
            print(f"         ✓ {count}개의 질문 발견, 수집 시작...")
            
            for i in range(count):
                try:
                    # 매 반복마다 locator를 새로 가져옴 (Stale Element 방지)
                    button = locators.nth(i)
                    
                    # 화면에 안보이면 스크롤 (중요)
                    await button.scroll_into_view_if_needed()
                    
                    # 텍스트 추출 (질문)
                    text_content = await button.text_content()
                    if not text_content: continue
                    text_content = text_content.strip()
                    
                    # 현재 상태 확인 (data-state="open" or "closed")
                    state = await button.get_attribute("data-state")
                    
                    # 닫혀있다면 클릭해서 열기
                    if state != "open":
                        try:
                            # timeout을 짧게 주어 매달리지 않게 함
                            await button.click(timeout=3000)
                            # 애니메이션 대기
                            await page.wait_for_timeout(500)
                        except Exception as e:
                            print(f"         ⚠️ 클릭 실패 (Index {i}): {e}")
                            continue

                    # 답변 찾기
                    btn_id = await button.get_attribute("id")
                    
                    # 답변 div 찾기 로직 (ID 기반 추적)
                    # 1. 2024년 기준 Radix UI Accordion 패턴: Button -> Sibling Div (Content)
                    # 2. 또는 Button -> Parent(Header) -> Sibling Div (Content)
                    
                    answer_text = await page.evaluate(f"""
                        (btnId) => {{
                            const btn = document.getElementById(btnId);
                            if (!btn) return "";
                            
                            // 1. 바로 다음 형제 시도
                            let content = btn.nextElementSibling;
                            
                            // 2. 없으면 부모의 형제 시도 (Header 감싸져 있는 경우)
                            if (!content && btn.parentElement) {{
                                content = btn.parentElement.nextElementSibling;
                            }}
                            
                            return content ? content.innerText.trim() : "";
                        }}
                    """, btn_id)
                    
                    # 수집 성공 시 저장
                    if text_content and answer_text:
                        faq_item = {
                            "main_category": main_cat,
                            "sub_category": sub_cat,
                            "question": text_content,
                            "answer": answer_text,
                            "scraped_at": datetime.now().isoformat()
                        }
                        
                        if not self._is_duplicate(faq_item):
                            self.faqs.append(faq_item)
                            # 진행 상황 표시 (10개 단위)
                            if (i + 1) % 10 == 0:
                                print(f"           - {i+1}/{count} 완료")
                            
                    # 닫기 (공간 확보 및 상태 초기화)
                    # 다시 상태 확인 후 열려있으면 닫기
                    current_state = await button.get_attribute("data-state")
                    if current_state == "open":
                        try:
                            await button.click(timeout=2000)
                            await page.wait_for_timeout(200) 
                        except:
                            pass # 닫기 실패는 치명적이지 않음
                    
                except Exception as e:
                    # 개별 아이템 실패는 무시하고 계속 진행
                    print(f"         ⚠️ 아이템 {i} 처리 중 에러: {e}")
                    continue
                    
        except Exception as e:
            print(f"         ❌ FAQ 수집 루프 중 에러: {e}")

    def _is_duplicate(self, faq_item: Dict) -> bool:
        return any(
            x['question'] == faq_item['question'] and x['answer'] == faq_item['answer']
            for x in self.faqs
        )

    def save_results(self):
        """결과 저장"""
        if not self.faqs:
            print("⚠ 저장할 데이터가 없습니다.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = self.output_dir / f"musinsa_faq_{timestamp}.json"
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.faqs, f, ensure_ascii=False, indent=2)
            
        print(f"💾 저장 완료: {json_path}")


async def main():
    scraper = MusinsaFAQScraper()
    await scraper.scrape_all_faqs()
    scraper.save_results()

if __name__ == "__main__":
    asyncio.run(main())
