# RAG Benchmark

`rags` 폴더는 두 가지 평가 축의 뼈대를 담습니다.

- `discovery/`: Discovery Subagent -> VLM(CLIP) -> Retrieve 경로 평가
- `policy_rag/`: Policy RAG SubAgent -> Query Transformation -> Hybrid Retrieve 경로 평가

현재는 폴더 및 파일 뼈대만 준비된 상태입니다.
실제 평가는 각 폴더의 `data/`에 골드 데이터셋을 채우고 `run.py`에서 실행 흐름을 연결하면 됩니다.
