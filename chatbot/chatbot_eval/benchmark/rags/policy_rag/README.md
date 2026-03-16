# Policy RAG Eval

`policy_rag` 평가는 아래 흐름을 대상으로 합니다.

`Policy RAG SubAgent -> Query Transformation -> Sparse/Dense Retrieve -> Qdrant`

우선 아래 3가지를 기본 지표로 보는 것을 권장합니다.

- Query Transformation 적절성
- Retrieval Hit Rate
- Answer Groundedness / Correctness

구성

- `data/`: 질의, 정답 문서, 정답 핵심 사실
- `src/`: 데이터 로더, 메트릭, 평가기
- `reports/`: 실행 결과 저장
- `run.py`: 엔트리 포인트
