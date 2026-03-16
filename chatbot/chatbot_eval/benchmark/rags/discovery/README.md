# Discovery RAG Eval

`discovery` 평가는 아래 흐름을 대상으로 합니다.

`Discovery Subagent -> VLM (CLIP MODEL) -> Retrieve`

우선 아래 2가지를 기본 지표로 보는 것을 권장합니다.

- Retrieval Hit Rate: 정답 상품이 top-k 안에 포함되는지
- Response Grounding: 최종 추천/설명이 실제 검색 결과와 일치하는지

구성

- `data/`: 평가용 입력과 골드 정답
- `src/`: 데이터 로더, 메트릭, 평가기
- `reports/`: 실행 결과 저장
- `run.py`: 엔트리 포인트
