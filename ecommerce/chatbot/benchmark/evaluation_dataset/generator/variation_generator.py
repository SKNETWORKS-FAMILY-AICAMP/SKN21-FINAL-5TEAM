"""
Variation Generator
동일 의도의 다양한 표현 생성
"""
import json
from typing import List, Dict, Any

from ecommerce.chatbot.src.infrastructure.openai import get_openai_client


class VariationGenerator:
    """표현 변형 생성기"""
    
    def __init__(self):
        self.client = get_openai_client()
    
    def generate_variations(
        self,
        original_text: str,
        intent: str,
        num_variations: int = 20,
        variation_types: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        동일 의도의 다양한 표현 생성
        
        Args:
            original_text: 원본 텍스트
            intent: 의도
            num_variations: 생성할 변형 수
            variation_types: 변형 유형 (formal, informal, typo, abbreviation 등)
        """
        if variation_types is None:
            variation_types = ["formal", "informal", "typo", "abbreviation", "verbose"]
        
        variations = []
        
        # 각 변형 유형별로 생성
        samples_per_type = num_variations // len(variation_types)
        
        for var_type in variation_types:
            type_variations = self._generate_by_type(
                original_text,
                intent,
                var_type,
                samples_per_type
            )
            variations.extend(type_variations)
        
        return variations[:num_variations]
    
    def _generate_by_type(
        self,
        text: str,
        intent: str,
        variation_type: str,
        count: int
    ) -> List[Dict[str, Any]]:
        """특정 유형의 변형 생성"""
        
        type_instructions = {
            "formal": "격식체로 정중하게 (예: 합니다, 주세요)",
            "informal": "친근한 반말로 (예: 해줘, 알려줘, 볼래)",
            "typo": "자연스러운 오타 포함 (키보드 배치 고려, 1-2개)",
            "abbreviation": "줄임말이나 은어 사용 (예: ㅇㅇ, ㄱㄱ, 즐, 취소ㄱ)",
            "verbose": "자세하고 긴 표현으로",
            "casual": "초성이나 이모티콘 포함 가능",
            "question": "의문형으로 변경",
            "command": "명령형으로 변경"
        }
        
        instruction = type_instructions.get(variation_type, "자연스럽게")
        
        prompt = f"""당신은 한국어 표현 전문가입니다.

**원본 문장**: {text}
**의도**: {intent}
**변형 유형**: {variation_type} - {instruction}

위 문장을 **{count}가지 다른 방식**으로 표현해주세요.
의도는 동일하게 유지하고, {instruction} 표현으로 바꿔주세요.

**요구사항**:
1. 실제 사용자가 쓸 법한 자연스러운 표현
2. 의도는 반드시 동일하게 유지
3. 각 변형은 독립적이고 다양해야 함
4. 지나치게 부자연스러운 표현은 피하기

**출력 형식** (JSON):
{{
  "variations": [
    {{
      "text": "변형된 문장",
      "variation_type": "{variation_type}",
      "characteristics": "이 변형의 특징 (한 줄)"
    }}
  ]
}}
"""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "당신은 한국어 표현 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.9,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            variations = result.get("variations", [])
            
            return [
                {
                    "input": var["text"],
                    "original": text,
                    "intent": intent,
                    "variation_type": variation_type,
                    "characteristics": var.get("characteristics", ""),
                    "metadata": {
                        "generation_method": "llm",
                        "type": "variation"
                    }
                }
                for var in variations
            ]
            
        except Exception as e:
            print(f"⚠️  변형 생성 실패 ({variation_type}): {e}")
            return []
    
    def generate_paraphrases(
        self,
        text: str,
        intent: str,
        num_paraphrases: int = 10
    ) -> List[Dict[str, Any]]:
        """
        의미는 같지만 완전히 다른 문장 구조로 변경
        """
        prompt = f"""당신은 한국어 패러프레이즈 전문가입니다.

**원본 문장**: {text}
**의도**: {intent}

위 문장과 **의미는 동일하지만 완전히 다른 구조**로 {num_paraphrases}가지 문장을 만들어주세요.

**요구사항**:
1. 단어 순서 바꾸기
2. 능동/피동 전환
3. 문장 구조 재배치
4. 동의어 사용
5. 의도는 100% 동일하게 유지

**출력 형식** (JSON):
{{
  "paraphrases": [
    {{
      "text": "패러프레이즈된 문장",
      "structure_changes": "어떻게 바뀌었는지 설명"
    }}
  ]
}}
"""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "당신은 한국어 패러프레이즈 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.85,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            paraphrases = result.get("paraphrases", [])
            
            return [
                {
                    "input": p["text"],
                    "original": text,
                    "intent": intent,
                    "variation_type": "paraphrase",
                    "structure_changes": p.get("structure_changes", ""),
                    "metadata": {
                        "generation_method": "llm_paraphrase",
                        "type": "variation"
                    }
                }
                for p in paraphrases
            ]
            
        except Exception as e:
            print(f"⚠️  패러프레이즈 생성 실패: {e}")
            return []
    
    def generate_context_variations(
        self,
        text: str,
        intent: str,
        contexts: List[str],
        num_per_context: int = 5
    ) -> List[Dict[str, Any]]:
        """
        다양한 맥락을 추가한 변형 생성
        
        Args:
            contexts: 추가할 맥락 (예: ["급함", "불만", "감사", "궁금함"])
        """
        variations = []
        
        for context in contexts:
            prompt = f"""원본 문장에 **{context}**의 감정/맥락을 추가해서 {num_per_context}가지로 표현해주세요.

**원본 문장**: {text}
**의도**: {intent}
**추가할 맥락**: {context}

예시:
- 급함: "빨리 좀", "지금 당장"
- 불만: "왜 이래", "진짜"
- 감사: "고마워요", "감사합니다"

**출력 형식** (JSON):
{{
  "context_variations": [
    {{
      "text": "맥락이 추가된 문장",
      "added_expressions": "추가된 표현들"
    }}
  ]
}}
"""
            
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "당신은 한국어 감정 표현 전문가입니다."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.9,
                    response_format={"type": "json_object"}
                )
                
                result = json.loads(response.choices[0].message.content)
                context_vars = result.get("context_variations", [])
                
                for cv in context_vars:
                    variations.append({
                        "input": cv["text"],
                        "original": text,
                        "intent": intent,
                        "variation_type": "context",
                        "context": context,
                        "added_expressions": cv.get("added_expressions", ""),
                        "metadata": {
                            "generation_method": "llm_context",
                            "type": "variation"
                        }
                    })
                
            except Exception as e:
                print(f"⚠️  맥락 변형 생성 실패 ({context}): {e}")
        
        return variations
    
    def batch_generate_variations(
        self,
        samples: List[Dict[str, Any]],
        variations_per_sample: int = 15
    ) -> List[Dict[str, Any]]:
        """
        여러 샘플에 대해 일괄 변형 생성
        """
        all_variations = []
        
        for i, sample in enumerate(samples):
            text = sample.get("input", sample.get("text", ""))
            intent = sample.get("intent", "unknown")
            
            print(f"변형 생성 중... ({i+1}/{len(samples)}): {text[:30]}...")
            
            # 기본 변형
            variations = self.generate_variations(
                text,
                intent,
                num_variations=variations_per_sample
            )
            
            # 원본 샘플 정보 추가
            for var in variations:
                var["original_sample"] = sample
            
            all_variations.extend(variations)
        
        print(f"✅ 총 {len(all_variations)}개 변형 생성 완료")
        return all_variations


# ============================================
# CLI 실행
# ============================================

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    from datetime import datetime
    
    parser = argparse.ArgumentParser(description="표현 변형 생성")
    parser.add_argument("--input", type=str, required=True, help="입력 파일 (JSONL)")
    parser.add_argument("--output", type=str, help="출력 디렉토리")
    parser.add_argument("--variations", type=int, default=15, help="샘플당 변형 수")
    
    args = parser.parse_args()
    
    # 입력 파일 읽기
    samples = []
    with open(args.input, 'r', encoding='utf-8') as f:
        for line in f:
            samples.append(json.loads(line))
    
    print(f"📖 {len(samples)}개 샘플 로드 완료")
    
    # 변형 생성
    generator = VariationGenerator()
    variations = generator.batch_generate_variations(samples, args.variations)
    
    # 저장
    output_dir = args.output or Path(args.input).parent
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_path / f"variations_{timestamp}.jsonl"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for var in variations:
            f.write(json.dumps(var, ensure_ascii=False) + '\n')
    
    print(f"💾 저장 완료: {output_file}")
