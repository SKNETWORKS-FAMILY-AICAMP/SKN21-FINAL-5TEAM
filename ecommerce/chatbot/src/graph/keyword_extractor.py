import json
import re
from collections import Counter

def extract_keywords():
    faq_path = r'c:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\data\raw\musinsa_faq\musinsa_faq_20260203_162139_final.json'
    terms_path = r'c:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\data\raw\ecommerce_standard\ecommerce_standard_preprocessed.json'
    
    category_keywords = {}
    
    # Simple mapping for terms
    terms_mapping = {
        "배송": "배송",
        "취소": "취소/반품/교환",
        "반품": "취소/반품/교환",
        "교환": "취소/반품/교환",
        "주문": "주문/결제",
        "결제": "주문/결제",
        "회원": "회원 정보",
        "상품": "상품/AS 문의",
        "AS": "상품/AS 문의",
        "약관": "약관"
    }

    def clean_and_split(text):
        if not text: return []
        # Extract Han characters
        words = re.findall(r'[가-힣]{2,}', text)
        return words

    # FAQ
    with open(faq_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for item in data:
            m_cat = item['payload']['main_category']
            # Map to our standard categories
            target_cat = None
            if "배송" in m_cat: target_cat = "배송"
            elif any(k in m_cat for k in ["취소", "반품", "교환"]): target_cat = "취소/반품/교환"
            elif any(k in m_cat for k in ["주문", "결제"]): target_cat = "주문/결제"
            elif "회원" in m_cat: target_cat = "회원 정보"
            elif any(k in m_cat for k in ["상품", "AS"]): target_cat = "상품/AS 문의"
            elif "약관" in m_cat: target_cat = "약관"
            
            if target_cat:
                if target_cat not in category_keywords: category_keywords[target_cat] = Counter()
                # Use question and answer summary
                category_keywords[target_cat].update(clean_and_split(item['payload']['question']))
                category_keywords[target_cat].update(clean_and_split(item['payload']['summary']))

    # Terms
    with open(terms_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for item in data:
            raw_cat = item.get('metadata', {}).get('category', '')
            target_cat = None
            if "배송" in raw_cat: target_cat = "배송"
            elif any(k in raw_cat for k in ["취소", "반품", "교환"]): target_cat = "취소/반품/교환"
            elif any(k in raw_cat for k in ["주문", "결제"]): target_cat = "주문/결제"
            elif "회원" in raw_cat: target_cat = "회원 정보"
            elif any(k in raw_cat for k in ["상품", "AS"]): target_cat = "상품/AS 문의"
            elif "약관" in raw_cat: target_cat = "약관"
            else: target_cat = "약관" # Default for terms
            
            if target_cat not in category_keywords: category_keywords[target_cat] = Counter()
            category_keywords[target_cat].update(clean_and_split(item['metadata'].get('title', '')))

    # Get top keywords for each
    result = {}
    for cat, counter in category_keywords.items():
        # Top 100 keywords
        result[cat] = [word for word, count in counter.most_common(100)]
    
    # Add manual important keywords
    manual_keywords = {
        "배송": ["택배", "언제", "도착", "송장", "추적"],
        "취소/반품/교환": ["환불", "철회", "하자", "오배송", "작아요", "커요"],
        "주문/결제": ["영수증", "가상계좌", "입금"],
        "회원 정보": ["비밀번호", "로그인", "탈퇴"],
        "상품/AS 문의": ["사이즈", "정품", "재고", "옷", "의류"],
        "약관": ["법", "의무", "책임", "조항"]
    }
    
    for cat, words in manual_keywords.items():
        if cat in result:
            for w in words:
                if w not in result[cat]: result[cat].append(w)
        else:
            result[cat] = words

    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    extract_keywords()
