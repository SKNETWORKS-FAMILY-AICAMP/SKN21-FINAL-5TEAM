import json
import re
import uuid
import os

def clean_text(text):
    if not text or not isinstance(text, str): return ""
    
    # 1. 브랜드 및 시스템 명칭 표준화 (가상 쇼핑몰 환경)
    branding_replacements = [
        (r'무신사 스탠다드|MUSINSA STANDARD', '자체 브랜드(PB)'),
        (r'무신사 부티크|MUSINSA BOUTIQUE|부티크', '프리미엄 관'),
        (r'무신사|MUSINSA', '저희 서비스'),
        (r'29CM|솔드아웃|Soldout', '제휴 플랫폼'),
        (r'나이키 코리아|나이키', '제휴 브랜드'),
        (r'마이페이지|마이 페이지', '마이메뉴'),
        (r'NICE 평가정보|NICE 평가 정보|NICE평가정보', '본인 인증 기관'),
        (r'롯데택배', '지정 택배사'),
        (r'GS25|CU|세븐일레븐', '제휴 편의점'),
        (r'더현대서울|현대백화점', '지정 오프라인 매장'),
        (r'성수점|성수역 \d+번 출구', '공식 오프라인 쇼룸'),
        (r'알림톡', '서비스 알림'),
        (r'패피스', '제휴 수선 서비스'),
        (r'용정콜렉션|용정 콜렉션', '전문 검수 기관'),
        (r'보블릭', '제휴 라이프스타일 업체'),
        (r'프린트베이커리', '제휴 컬렉터블 업체'),
    ]
    for p, r in branding_replacements:
        text = re.sub(p, r, text, flags=re.IGNORECASE)

    # 2. 크롤링 흔적 및 UI 요소 제거
    ui_elements = [
        r'\[.*?가기\]', r'\[.*?확인\]', r'\[.*?보기\]', r'\[.*?클릭\]',
        r'.*?하러\s*가기', r'.*?확인하기', r'.*?보러\s*가기', r'.*?문의하기',
        r'클릭해\s*주세요', r'눌러\s*주세요', r'이동합니다',
        r'모바일\(앱/웹\)\s*:', r'PC\s*:', r'APP\s*:', r'웹\s*:',
        r'[가-힣A-Z ]+\s*>\s*[가-힣A-Z ]+(\s*>\s*[가-힣A-Z ]+)*', # 설정 > 메뉴 경로
        r'오른쪽 위 톱니바퀴',
    ]
    for p in ui_elements:
        text = re.sub(p, '', text)

    # 3. 비정상 텍스트 및 오타 교정
    text = text.replace("[]", "[해당 메뉴]")
    text = text.replace("ipplepplepple ID", "Apple ID")
    text = text.replace("ipple", "Apple")
    text = text.replace("Applepple", "Apple")
    text = text.replace("무배당발", "당일 배송 서비스")
    text = text.replace("→ .", "→ [해당 메뉴]에서 확인하실 수 있습니다.")
    text = text.replace("모바일 .", ".")
    
    # 4. 중복 단어 제거 (인접한 동일 단어)
    text = re.sub(r'([가-힣\s]{2,8})\1', r'\1', text)
    text = re.sub(r'([가-힣]{2,})\s?\1', r'\1', text)
    
    # 5. 불완전한 문장 끝 처리
    if text.endswith(('훼', '있습니', '로그인을')):
        text = re.sub(r'\s+[가-힣]+$', '.', text)

    # 6. 문법 및 문장 부호 정리
    text = re.sub(r'\s+[은는이가의을를와과에]\s*\.?$', '.', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r'\s+', ' ', text)
    
    # 문두 주어 보강
    text = re.sub(r'^(을|를|이|가)\s', '해당 상품을 ', text)
    
    return text.strip()

def deduplicate_sentences(text):
    if not text: return ""
    sentences = re.split(r'(?<=[.!?])\s+|\n', text)
    unique_sentences = []
    seen = set()
    for s in sentences:
        s = s.strip()
        if s and s not in seen:
            unique_sentences.append(s)
            seen.add(s)
    return " ".join(unique_sentences)

def generate_summary(answer):
    if not answer: return ""
    match = re.search(r'^.*?[.!?](\s|$)', answer, re.DOTALL)
    summary = match.group(0).strip() if match else answer.split('\n')[0].strip()
    summary = re.sub(r'[은는이가의을를와과에]$', '', summary).strip()
    if not summary.endswith(('.', '!', '?', ')')):
        summary += "."
    return summary[:150]

def process_faq(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    processed = []
    for item in data:
        # 질문 앞에 붙은 불필요한 카테고리 접두어 제거 로직 포함
        q_raw = item.get('question', '')
        q_raw = re.sub(r'^(로그인/정보|회원 혜택|AS 문의|이벤트|입점/제휴|회원 정보|배송 문제/기타|교환/반품)', '', q_raw).strip()
        
        q = clean_text(q_raw)
        a = clean_text(item.get('answer', ''))
        
        # 문장 단위 중복 제거
        q = deduplicate_sentences(q)
        a = deduplicate_sentences(a)
        
        if not q or not a: continue
        
        p = {
            "main_category": clean_text(item.get('main_category', '기타')),
            "sub_category": clean_text(item.get('sub_category', '전체')),
            "question": q,
            "answer": a,
            "summary": generate_summary(a),
            "full_context": f"질문: {q}\n답변: {a}"
        }
        
        processed.append({
            "id": str(uuid.uuid4()),
            "vector_input": p["full_context"],
            "payload": p
        })
        
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)
    print(f"Cleanup complete: {len(processed)} items saved to {output_path}")

if __name__ == "__main__":
    raw_file = 'musinsa_faq_20260203_162139.json'
    final_file = 'musinsa_faq_20260203_162139_final.json'
    if os.path.exists(raw_file):
        process_faq(raw_file, final_file)
    else:
        print(f"❌ 원본 파일({raw_file})을 찾을 수 없습니다.")
