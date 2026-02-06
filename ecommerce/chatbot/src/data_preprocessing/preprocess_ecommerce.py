"""
전자상거래 표준약관 전처리 스크립트 v4
- 문맥적 보충(Context Enrichment) 추가
- 포맷: [제4조 서비스의 제공 및 변경] (1항 업무범위) 1. 재화 또는 용역에...
- 메타데이터 개선: article_no, paragraph, sub_point, source 포함
"""

import json
import re
from pathlib import Path

# 카테고리 매핑
CATEGORY_MAP = {
    "제1조": "일반",
    "제2조": "일반",
    "제3조": "약관",
    "제4조": "서비스",
    "제5조": "서비스",
    "제6조": "회원",
    "제7조": "회원",
    "제8조": "회원",
    "제9조": "구매/결제",
    "제10조": "구매/결제",
    "제11조": "구매/결제",
    "제12조": "구매/결제",
    "제13조": "배송",
    "제14조": "취소/반품/교환",
    "제15조": "취소/반품/교환",
    "제16조": "취소/반품/교환",
    "제17조": "개인정보",
    "제18조": "의무/책임",
    "제19조": "의무/책임",
    "제20조": "의무/책임",
    "제21조": "연결몰",
    "제22조": "저작권",
    "제23조": "분쟁해결",
    "제24조": "분쟁해결",
}

# 항별 문맥 설명 (Context Summary)
# 키: "제X조-항번호" 형식
PARAGRAPH_CONTEXT = {
    # 제4조
    "제4조-①": "업무범위",
    "제4조-②": "서비스내용변경",
    "제4조-③": "변경통지",
    "제4조-④": "손해배상",
    # 제5조
    "제5조-①": "서비스중단사유",
    "제5조-②": "중단손해배상",
    "제5조-③": "서비스종료보상",
    # 제6조
    "제6조-①": "가입신청",
    "제6조-②": "가입거부사유",
    "제6조-③": "가입성립시점",
    "제6조-④": "정보변경의무",
    # 제7조
    "제7조-①": "탈퇴요청",
    "제7조-②": "자격제한사유",
    "제7조-③": "자격상실",
    "제7조-④": "등록말소절차",
    # 제8조
    "제8조-①": "개별통지",
    "제8조-②": "게시판공지",
    # 제9조
    "제9조-①": "구매신청절차",
    "제9조-②": "개인정보제3자제공",
    "제9조-③": "개인정보취급위탁",
    # 제10조
    "제10조-①": "계약거부사유",
    "제10조-②": "계약성립시점",
    "제10조-③": "승낙의사내용",
    # 제11조
    "제11조-": "결제방법",
    # 제12조
    "제12조-①": "수신확인",
    "제12조-②": "변경취소요청",
    # 제13조
    "제13조-①": "배송기한",
    "제13조-②": "배송정보명시",
    # 제14조
    "제14조-": "환급절차",
    # 제15조
    "제15조-①": "청약철회기간",
    "제15조-②": "반품제한사유",
    "제15조-③": "제한예외",
    "제15조-④": "계약불이행철회",
    # 제16조
    "제16조-①": "환급기한",
    "제16조-②": "결제취소요청",
    "제16조-③": "반환비용부담",
    "제16조-④": "발송비표시",
    # 제17조
    "제17조-①": "최소수집원칙",
    "제17조-②": "사전수집금지",
    "제17조-③": "수집동의",
    "제17조-④": "목적외이용금지",
    "제17조-⑤": "동의요건고지",
    "제17조-⑥": "열람정정요구",
    "제17조-⑦": "취급자제한",
    "제17조-⑧": "정보파기",
    "제17조-⑨": "동의거절권리",
    # 제18조
    "제18조-①": "법령준수의무",
    "제18조-②": "보안시스템의무",
    "제18조-③": "부당광고책임",
    "제18조-④": "광고메일제한",
    # 제19조
    "제19조-①": "ID관리책임",
    "제19조-②": "제3자이용금지",
    "제19조-③": "도난통보의무",
    # 제20조
    "제20조-": "금지행위",
    # 제21조
    "제21조-①": "연결몰정의",
    "제21조-②": "보증책임면제",
    # 제22조
    "제22조-①": "저작권귀속",
    "제22조-②": "무단이용금지",
    "제22조-③": "사용시통보",
    # 제23조
    "제23조-①": "피해보상기구",
    "제23조-②": "불만우선처리",
    "제23조-③": "분쟁조정",
    # 제24조
    "제24조-①": "관할법원",
    "제24조-②": "준거법",
}

# 항 번호를 숫자로 변환
PARA_TO_NUM = {
    "①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5",
    "⑥": "6", "⑦": "7", "⑧": "8", "⑨": "9", "⑩": "10",
    "⑪": "11", "⑫": "12", "⑬": "13", "⑭": "14", "⑮": "15"
}


def clean_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_article_info(content: str):
    match = re.match(r'^(제\d+조)\s*\(([^)]+)\)', content)
    if match:
        return match.group(1), match.group(2)
    match = re.match(r'^(제\d+조)', content)
    if match:
        return match.group(1), ""
    return None, None


def get_article_num(article_no: str) -> str:
    """제4조 -> 4"""
    match = re.search(r'제(\d+)조', article_no)
    return match.group(1) if match else ""


def split_by_paragraphs(content: str):
    pattern = r'(?=\s?[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])'
    parts = re.split(pattern, content)
    return [p.strip() for p in parts if p.strip()]


def split_by_clauses(content: str):
    pattern = r'(?=\s+\d+\.\s)'
    parts = re.split(pattern, content)
    return [p.strip() for p in parts if p.strip()]


def has_clauses(content: str) -> bool:
    matches = re.findall(r'\s+\d+\.\s', content)
    return len(matches) >= 2


def extract_paragraph_intro(content: str) -> str:
    match = re.search(r'^(.*?)(?=\s+1\.\s)', content)
    if match:
        intro = match.group(1).strip()
        intro = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]\s*', '', intro)
        return intro
    return ""


def get_context_label(article_no: str, paragraph_no: str) -> str:
    """문맥 레이블 가져오기"""
    key = f"{article_no}-{paragraph_no}"
    return PARAGRAPH_CONTEXT.get(key, "")


def process_ecommerce_terms(json_data: list) -> list:
    processed_chunks = []
    
    all_contents = []
    for item in json_data:
        content = item.get("전자상거래(인터넷사이버몰) 표준약관", "")
        if content:
            all_contents.append(content)
    
    current_article = None
    current_title = ""
    current_paragraphs = []
    articles = []
    
    for content in all_contents:
        article_no, title = extract_article_info(content)
        
        if article_no:
            if current_article:
                articles.append({
                    "article_no": current_article,
                    "title": current_title,
                    "paragraphs": current_paragraphs
                })
            current_article = article_no
            current_title = title if title else ""
            remaining = re.sub(r'^제\d+조\s*\([^)]+\)\s*', '', content)
            if remaining.strip():
                current_paragraphs = [remaining.strip()]
            else:
                current_paragraphs = []
        else:
            if current_article:
                current_paragraphs.append(content)
    
    if current_article:
        articles.append({
            "article_no": current_article,
            "title": current_title,
            "paragraphs": current_paragraphs
        })
    
    for article in articles:
        article_no = article["article_no"]
        title = article["title"]
        paragraphs = article["paragraphs"]
        category = CATEGORY_MAP.get(article_no, "기타")
        article_num = get_article_num(article_no)
        
        full_content = " ".join(paragraphs)
        sub_items = split_by_paragraphs(full_content)
        header = f"[{article_no} {title}]" if title else f"[{article_no}]"
        
        if len(sub_items) <= 1:
            if has_clauses(full_content):
                intro = extract_paragraph_intro(full_content)
                clauses = split_by_clauses(full_content)
                context_label = get_context_label(article_no, "")
                
                for clause in clauses:
                    if not clause.strip():
                        continue
                    
                    clause_match = re.match(r'^(\d+)\.\s', clause)
                    clause_no = clause_match.group(1) if clause_match else ""
                    
                    # 문맥적 보충 포맷
                    if context_label and clause_no:
                        context_part = f"({context_label})"
                    else:
                        context_part = ""
                    
                    if intro and clause_no:
                        chunk_text = f"{header} {context_part} {intro} {clean_text(clause)}"
                    else:
                        chunk_text = f"{header} {context_part} {clean_text(clause)}"
                    
                    chunk_text = re.sub(r'\s+', ' ', chunk_text).strip()
                    
                    processed_chunks.append({
                        "metadata": {
                            "article_no": article_num,
                            "title": title,
                            "category": category,
                            "paragraph": "",
                            "sub_point": clause_no,
                            "source": "전자상거래표준약관"
                        },
                        "text": chunk_text
                    })
            else:
                chunk_text = f"{header} {clean_text(full_content)}"
                processed_chunks.append({
                    "metadata": {
                        "article_no": article_num,
                        "title": title,
                        "category": category,
                        "paragraph": "",
                        "sub_point": "",
                        "source": "전자상거래표준약관"
                    },
                    "text": chunk_text
                })
        else:
            for sub in sub_items:
                if not sub.strip():
                    continue
                
                paragraph_match = re.match(r'^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])', sub)
                paragraph_no = paragraph_match.group(1) if paragraph_match else ""
                paragraph_num = PARA_TO_NUM.get(paragraph_no, "")
                context_label = get_context_label(article_no, paragraph_no)
                
                if has_clauses(sub):
                    intro = extract_paragraph_intro(sub)
                    clauses = split_by_clauses(sub)
                    
                    for clause in clauses:
                        if not clause.strip():
                            continue
                        
                        clause_match = re.match(r'^(\d+)\.\s', clause)
                        clause_no = clause_match.group(1) if clause_match else ""
                        
                        # 문맥적 보충 포맷: [제4조 서비스의 제공 및 변경] (1항 업무범위) ① ...
                        if context_label:
                            context_part = f"({paragraph_num}항 {context_label})"
                        else:
                            context_part = f"({paragraph_num}항)"
                        
                        if intro and clause_no:
                            chunk_text = f"{header} {context_part} {paragraph_no} {intro} {clean_text(clause)}"
                        elif paragraph_no:
                            text_without_para = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]\s*', '', clause)
                            chunk_text = f"{header} {context_part} {paragraph_no} {clean_text(text_without_para)}"
                        else:
                            chunk_text = f"{header} {clean_text(clause)}"
                        
                        chunk_text = re.sub(r'\s+', ' ', chunk_text).strip()
                        
                        processed_chunks.append({
                            "metadata": {
                                "article_no": article_num,
                                "title": title,
                                "category": category,
                                "paragraph": paragraph_num,
                                "sub_point": clause_no,
                                "source": "전자상거래표준약관"
                            },
                            "text": chunk_text
                        })
                else:
                    # 호가 없는 항
                    if context_label:
                        context_part = f"({paragraph_num}항 {context_label})"
                    else:
                        context_part = f"({paragraph_num}항)"
                    
                    chunk_text = f"{header} {context_part} {clean_text(sub)}"
                    chunk_text = re.sub(r'\s+', ' ', chunk_text).strip()
                    
                    processed_chunks.append({
                        "metadata": {
                            "article_no": article_num,
                            "title": title,
                            "category": category,
                            "paragraph": paragraph_num,
                            "sub_point": "",
                            "source": "전자상거래표준약관"
                        },
                        "text": chunk_text
                    })
    
    return processed_chunks


def main():
    base_dir = Path(__file__).resolve().parent
    input_file = base_dir / "ecommerce_standard.json"
    output_file = base_dir / "ecommerce_standard_preprocessed.json"
    
    print(f"[INPUT] File: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"[INFO] Original items: {len(data)}")
    
    chunks = process_ecommerce_terms(data)
    
    print(f"[INFO] Generated chunks: {len(chunks)}")
    
    lengths = [len(c['text']) for c in chunks]
    print(f"[STAT] Min: {min(lengths)}, Max: {max(lengths)}, Avg: {sum(lengths)//len(lengths)} chars")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    
    print(f"[DONE] Saved: {output_file}")
    
    # 샘플 출력
    print("\n[SAMPLE] Context-enriched chunks:")
    samples = [c for c in chunks if c['metadata'].get('sub_point')][:3]
    for i, chunk in enumerate(samples):
        print(f"\n--- Sample {i+1} ---")
        print(f"Metadata: {chunk['metadata']}")
        print(f"Text: {chunk['text']}")


if __name__ == "__main__":
    main()
