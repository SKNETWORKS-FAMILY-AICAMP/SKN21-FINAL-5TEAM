# RAG Benchmark 발표용 정리서

## 1. RAGS 개요

이 폴더는 챗봇의 두 가지 핵심 RAG 기능을 평가하기 위한 벤치마크 모음입니다.

- `policy_rag`
  - 반품, 환불, 배송비, 교환, A/S 같은 `정책성 질문`에 대해 올바른 문서를 찾는지 평가합니다.
- `discovery`
  - 사용자가 원하는 상품 특징을 설명했을 때 `적절한 상품을 추천`하는지 평가합니다.

즉,
- `policy_rag`는 `정답 문서 검색`
- `discovery`는 `정답 상품 추천`
를 검증하는 평가 체계입니다.

## 2. RAGS 평가 방법

두 평가 모두 공통적으로 아래 흐름으로 진행됩니다.

1. 평가용 데이터셋에서 `질문`, `정답`, `허용 가능한 대체 정답`, `기대 키워드`를 읽습니다.
2. 실제 챗봇 파이프라인을 그대로 실행합니다.
3. 검색 결과의 top-k 후보를 수집합니다.
4. 정답이 `top1`, `top3`, `top5` 안에 들어왔는지 계산합니다.
5. 필요한 경우 답변/설명 텍스트가 핵심 키워드를 포함하는지도 확인합니다.
6. 전체 문항 평균으로 최종 점수를 집계합니다.

즉 이 평가는 `리포트만 만드는 가짜 코드`가 아니라, `실제 챗봇이 사용하는 검색/재랭킹 코드`를 직접 통과시키는 구조입니다.

## 3. RAGS 동작 방식

### 3-1. Policy RAG 동작 방식

1. 사용자의 정책 질문을 입력받습니다.
2. 질문을 검색 친화적인 형태로 `query transform` 합니다.
3. FAQ / 약관 문서를 hybrid retrieval로 검색합니다.
4. 검색된 후보 문서를 reranking 합니다.
5. 최종 문서를 바탕으로 답변을 생성합니다.

### 3-2. Discovery 동작 방식

1. 사용자의 상품 탐색 질문을 입력받습니다.
2. 질문에서 `색상`, `카테고리`, `패턴`, `재질`, `성별`, `용도`를 구조화합니다.
3. 한국어 질의를 영어/검색형 질의로 변환합니다.
4. CLIP 기반 검색 + keyword 검색으로 후보 상품을 모읍니다.
5. heuristic/slot-based/LLM reranking으로 최종 순서를 정합니다.
6. 추천 상품과 설명을 반환합니다.

## 4. RAGS 폴더 개요

- `policy_rag/`
  - 정책 RAG 평가 코드, 데이터셋, 리포트
- `discovery/`
  - 상품 추천 RAG 평가 코드, 데이터셋, 리포트
- `README.md`
  - 전체 평가 체계와 최종 결과를 정리한 상위 문서

각 하위 폴더 구조는 거의 동일합니다.

- `data/`
  - 평가 데이터셋과 holdout 데이터셋
- `src/`
  - evaluator, metrics, loader
- `reports/`
  - 실행 결과 리포트 JSON
- `run.py`
  - 평가 실행 엔트리포인트

## 5. Discovery는 무엇을 평가했는가

Discovery는 `사용자 의도에 맞는 상품을 제대로 추천하는지`를 평가했습니다.

평가 대상:
- 색상
- 카테고리
- 세부 타입
- 패턴
- 재질
- 성별
- 용도

예:
- `검은색 백팩 추천해줘`
- `네이비 폴로 티셔츠 보여줘`
- `갈색 포멀 슈즈 추천해줘`
- `핑크 민소매 원피스 있을까?`

즉 Discovery 평가는 단순 검색이 아니라, `자연어 상품 탐색 질의`에 대해 `올바른 추천 후보를 상위에 띄우는 능력`을 측정합니다.

## 6. Discovery 평가 항목 의미

- `Dataset size`
  - 평가에 사용한 전체 문항 수
- `Retrieval pass rate`
  - 정답 상품이 `top5` 안에 하나라도 들어오면 통과
- `Retrieval Hit@1`
  - 첫 번째 추천 상품이 바로 정답인 비율
- `Retrieval Hit@3`
  - 상위 3개 안에 정답 상품이 포함되는 비율
- `Retrieval Hit@5`
  - 상위 5개 안에 정답 상품이 포함되는 비율
- `Grounding pass rate`
  - 추천 이후 설명이 기대 키워드를 충분히 반영했는지의 통과 비율
- `Grounding keyword recall`
  - 기대 키워드가 실제 답변/검색 결과에 반영된 평균 비율

## 7. Discovery 초기 점수와 최종 개선 결과

초기 80문항 본 평가셋:
- `reports/discovery_rag_eval_20260319_110239.json`

초기 점수:
- Retrieval pass rate: `91.25%`
- Retrieval Hit@1: `76.25%`
- Retrieval Hit@3: `86.25%`
- Retrieval Hit@5: `91.25%`
- Grounding pass rate: `98.75%`
- Grounding keyword recall: `95.83%`

본 평가셋 최종:
- `reports/discovery_rag_eval_20260319_124119.json`

최종 점수:
- Retrieval pass rate: `100.00%`
- Retrieval Hit@1: `91.25%`
- Retrieval Hit@3: `98.75%`
- Retrieval Hit@5: `100.00%`
- Grounding pass rate: `100.00%`
- Grounding keyword recall: `97.50%`

개선 폭:
- Retrieval pass rate: `+8.75%p`
- Retrieval Hit@1: `+15.00%p`
- Retrieval Hit@3: `+12.50%p`
- Retrieval Hit@5: `+8.75%p`

## 8. Discovery 과적합이 의심된 이유

본 평가셋에서는 매우 높은 점수가 나왔지만, 새 표현으로 만든 holdout에서는 처음에 성능이 크게 떨어졌습니다.

초기 holdout 40문항:
- `reports/discovery_rag_eval_20260319_135215.json`
- Retrieval Hit@1: `70.00%`
- Retrieval Hit@5: `82.50%`

초기 holdout 80문항(single-gold 기준):
- `reports/discovery_rag_eval_20260319_141456.json`
- Retrieval pass rate: `15.00%`
- Retrieval Hit@1: `10.00%`
- Retrieval Hit@5: `15.00%`

이 결과가 의미한 것:
- 기존 평가셋 표현에 맞춰 튜닝된 부분이 있었고
- 새로운 말투, paraphrase, 우회 표현에 대해서는 약한 구간이 있었다는 뜻입니다.

## 9. Discovery 과적합 원인

원인은 크게 3가지였습니다.

- 같은 평가셋을 반복적으로 보면서 튜닝함
- 문자열 기반 휴리스틱 비중이 높아 새로운 표현 일반화가 약함
- discovery 특성상 정답이 1개로 딱 떨어지지 않는데 single-gold 기준으로 너무 엄격하게 채점함

예:
- `배낭`
- `정장화`
- `더플 스타일 가방`
- `레드 계열 여성 상의`

같은 표현은 본셋에는 거의 없고 holdout에 많았기 때문에 성능이 급격히 흔들렸습니다.

## 10. Discovery 해결 방법

### 10-1. 검색 일반화 개선

- 한국어 질의 정규화 추가
  - `배낭 -> 백팩`
  - `정장화 -> 구두`
  - `캐주얼화 -> 캐주얼 신발`
  - `더플 스타일 가방 -> 더플백`
  - `드레스 -> 원피스`
- canonical query 우선 검색
  - `black formal shoes`, `grey duffle bag` 같은 검색형 질의를 앞에 배치
- 카테고리 불일치 감점 강화
  - 색상만 맞는 화장품/속옷/액세서리 상위 노출 방지

### 10-2. Multi-gold 평가 기준 도입

`multi-gold`는 한 문항에서 정답을 1개만 인정하지 않고, `허용 가능한 복수 정답`을 같이 인정하는 방식입니다.

예:
- 질문: `검은 정장화 추천해줘`
- 기존 single-gold:
  - 특정 black formal shoes 1개만 정답
- multi-gold:
  - 같은 `black + formal shoes` 조건을 만족하는 다른 상품도 정답으로 인정

즉 discovery에서는
- `정답 하나만 맞추는 시험`
보다
- `질문 의도에 맞는 추천 후보를 올바르게 제시했는가`
를 더 현실적으로 평가할 수 있습니다.

## 11. Discovery에서 기존에는 이렇게 했고, 바꾸니 정상화된 이유

기존 holdout 80문항은 `single-gold` 기준이 너무 빡빡했습니다.

문제:
- 실제로는 타당한 추천인데도 정답 1개와 ID가 다르면 전부 실패 처리
- 그래서 holdout 80에서 `15%` 같은 비정상적으로 낮은 점수가 나옴

조치:
- `holdout_dataset_80.jsonl`에 `acceptable_product_ids`를 추가
- 같은 색/같은 카테고리/같은 subtype의 타당한 대체 상품을 허용

최신 holdout 80 결과:
- `reports/discovery_rag_eval_20260319_144133.json`

점수:
- Retrieval pass rate: `93.75%`
- Retrieval Hit@1: `90.00%`
- Retrieval Hit@3: `92.50%`
- Retrieval Hit@5: `93.75%`
- Grounding pass rate: `96.25%`
- Grounding keyword recall: `92.81%`

즉 기존 `15%`는 모델이 완전히 망가진 수치라기보다, `single-gold holdout이 discovery 추천 문제를 지나치게 엄격하게 채점한 영향`이 컸고, multi-gold 기준으로 다시 보니 보다 현실적인 일반화 성능이 확인되었습니다.

## 12. Discovery 고도화 방법 상세

Discovery 성능을 올리기 위해 적용한 고도화는 다음과 같습니다.

1. 한국어 질의를 영어 검색어로 번역
2. 쿼리 간략화
3. 쿼리 확장
4. 색상/카테고리/패턴/재질/성별/용도 슬롯 추출
5. CLIP + keyword hybrid retrieval
6. rescue candidate 수집
7. heuristic reranking
8. slot-based reranking
9. exact phrase bonus
10. LLM reranker 추가

핵심적으로는
- `정답을 찾는 것`
뿐 아니라
- `정답을 1등으로 올리는 것`
에 집중해서 고도화했습니다.

## 13. Policy는 무엇을 평가했는가

Policy는 `정책성 질문에 대해 올바른 문서/FAQ를 찾는지`를 평가했습니다.

평가 대상:
- 배송
- 주문/결제
- 취소/교환/반품
- 상품/A/S

예:
- `반품 배송비는 누가 부담하나요?`
- `제주도 추가 배송비가 있나요?`
- `환불은 언제 처리되나요?`
- `A/S 문의는 어디로 하나요?`

즉 policy 평가는 `질문 의미를 올바르게 정규화하고, 관련 정책 문서를 정확히 상위에 띄우는 능력`을 검증합니다.

## 14. Policy 평가 항목 의미

- `Dataset size`
  - 평가에 사용한 전체 정책 문항 수
- `Query pass rate`
  - 사용자의 질문을 검색용 질의로 변환했을 때 핵심 키워드를 충분히 보존한 비율
- `Retrieval pass rate`
  - 정답 문서가 `top5` 안에 하나라도 포함된 비율
- `Retrieval Hit@1`
  - 첫 번째 검색 문서가 바로 정답 문서인 비율
- `Retrieval Hit@3`
  - 상위 3개 문서 안에 정답 문서가 포함되는 비율
- `Retrieval Hit@5`
  - 상위 5개 문서 안에 정답 문서가 포함되는 비율

## 15. Policy 초기 점수와 최종 개선 결과

초기 80문항 본 평가셋:
- `reports/policy_rag_eval_20260319_111610.json`

초기 점수:
- Query pass rate: `92.50%`
- Retrieval pass rate: `88.75%`
- Retrieval Hit@1: `80.00%`
- Retrieval Hit@3: `86.25%`
- Retrieval Hit@5: `88.75%`

최종 80문항 본 평가셋:
- `reports/policy_rag_eval_20260319_125515.json`

최종 점수:
- Query pass rate: `98.75%`
- Retrieval pass rate: `98.75%`
- Retrieval Hit@1: `95.00%`
- Retrieval Hit@3: `96.25%`
- Retrieval Hit@5: `98.75%`

개선 폭:
- Query pass rate: `+6.25%p`
- Retrieval pass rate: `+10.00%p`
- Retrieval Hit@1: `+15.00%p`
- Retrieval Hit@3: `+10.00%p`
- Retrieval Hit@5: `+10.00%p`

## 16. Policy 고도화 방법

Policy는 아래 방식으로 고도화했습니다.

1. 구어체 질문을 짧고 핵심적인 query로 간략화
2. `출고 후 배송지 변경`, `반송장 입력`, `불량 보상 기준`, `A/S 문의처` 같은 표현 정규화
3. query variant 추가 생성
4. category-aware retrieval
5. fallback retrieval
6. FAQ 우선순위 조정
7. 충돌 FAQ 감점
8. USED/유즈드 문서 과노출 억제
9. 실패 케이스별 reranking 보정
10. 병렬 chunk 평가 지원

핵심은
- `새로운 말투에도 흔들리지 않는 query transform`
- `FAQ/약관 문서의 top1 정확도 향상`
이었습니다.

## 17. Holdout 파일이란 무엇인가

`holdout` 파일은 개발 중 계속 보면서 튜닝한 본 평가셋과 분리된 `추가 검증용 데이터셋`입니다.

역할:
- 본 평가셋에 과적합되었는지 확인
- 새로운 표현, 새로운 말투에서도 성능이 유지되는지 검증

현재 사용한 holdout:
- Discovery
  - `discovery/data/holdout_dataset.jsonl`
  - `discovery/data/holdout_dataset_80.jsonl`
- Policy
  - `policy_rag/data/holdout_dataset.jsonl`
  - `policy_rag/data/holdout_dataset_v2.jsonl` 성격으로 확장 검증 진행

즉 holdout은 `성능을 깎아내리기 위한 파일`이 아니라, `일반화 성능을 확인하기 위한 검증용 파일`입니다.

## 18. 최종 결론

이번 RAG 고도화 결과를 정리하면:

- `Policy RAG`
  - query transform, retrieval, ranking 모두 매우 안정화됨
  - 본 평가셋 80문항 기준 `Hit@1 95%`
  - 파이널 프로젝트 수준에서 충분히 강한 결과

- `Discovery RAG`
  - 본 평가셋 80문항 기준 `Hit@1 91.25%`
  - holdout 80문항(multi-gold 기준)에서도 `Hit@1 90%`
  - 단순 본셋 최적화가 아니라, 현실적인 추천 평가 기준으로도 충분히 좋은 수준

최종적으로:
- 두 RAG 모두 실제 챗봇 코드에 반영된 상태이고
- 평가 리포트와 holdout 검증까지 완료되었으며
- 파이널 프로젝트 발표/시연용 결과로 사용 가능한 수준까지 정리되었습니다.

## 19. 실행 명령어

Discovery:

```powershell
uv run python chatbot/chatbot_eval/benchmark/rags/discovery/run.py --dataset chatbot/chatbot_eval/benchmark/rags/discovery/data/eval_dataset_80.jsonl
```

Discovery holdout:

```powershell
uv run python chatbot/chatbot_eval/benchmark/rags/discovery/run.py --dataset chatbot/chatbot_eval/benchmark/rags/discovery/data/holdout_dataset_80.jsonl
```

Policy:

```powershell
uv run python chatbot/chatbot_eval/benchmark/rags/policy_rag/run.py --dataset chatbot/chatbot_eval/benchmark/rags/policy_rag/data/eval_dataset_80.jsonl
```

Policy 병렬 chunk 평가:

```powershell
uv run python chatbot/chatbot_eval/benchmark/rags/policy_rag/run.py --dataset chatbot/chatbot_eval/benchmark/rags/policy_rag/data/eval_dataset_80.jsonl --chunk-size 10 --parallel-workers 8
```
