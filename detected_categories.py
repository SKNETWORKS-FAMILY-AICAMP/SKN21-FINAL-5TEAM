import json

def get_cats():
    faq_path = r'c:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\data\raw\musinsa_faq\musinsa_faq_20260203_162139_final.json'
    terms_path = r'c:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\data\raw\ecommerce_standard\ecommerce_standard_preprocessed.json'
    
    with open(faq_path, 'r', encoding='utf-8') as f:
        faq_data = json.load(f)
    with open(terms_path, 'r', encoding='utf-8') as f:
        terms_data = json.load(f)
        
    faq_cats = set()
    for item in faq_data:
        faq_cats.add(item['payload']['main_category'])
        
    terms_cats = set()
    for item in terms_data:
        cat = item.get('metadata', {}).get('category')
        if cat: terms_cats.add(cat)
        
    result = {
        "faq_main_categories": sorted(list(faq_cats)),
        "terms_categories": sorted(list(terms_cats))
    }
    with open('detected_categories.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    get_cats()
