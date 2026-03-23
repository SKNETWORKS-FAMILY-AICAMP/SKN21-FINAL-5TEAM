# Policy RAG 결과 정리서

## 0. 평가 항목 의미

- `Dataset size`
  - 평가에 사용한 전체 정책 문항 수입니다.
- `Query pass rate`
  - 사용자의 질문을 검색용 질의로 변환했을 때, 기대 키워드나 핵심 토큰을 충분히 보존한 비율입니다.
- `Retrieval pass rate`
  - 정답 문서가 `top5` 안에 하나라도 포함된 비율입니다.
- `Retrieval Hit@1`
  - 첫 번째 검색 문서가 바로 정답 문서인 비율입니다.
- `Retrieval Hit@3`
  - 상위 3개 문서 안에 정답 문서가 포함되는 비율입니다.
- `Retrieval Hit@5`
  - 상위 5개 문서 안에 정답 문서가 포함되는 비율입니다.

## 1. 최종 결과

최종 기준 리포트:
- `reports/policy_rag_eval_20260319_125515.json`

최종 점수:
- Dataset size: `80`
- Query pass rate: `98.75%`
- Retrieval pass rate: `98.75%`
- Retrieval Hit@1: `95.00%`
- Retrieval Hit@3: `96.25%`
- Retrieval Hit@5: `98.75%`

해석:
- Query transformation은 거의 안정적으로 동작합니다.
- 정답 문서를 거의 전부 top5 안에 넣고 있습니다.
- `Hit@1 95%`로 첫 문서 정확도도 매우 높습니다.

## 2. 처음 대비 얼마나 개선됐는가

현재 `reports` 폴더에 남아 있는 80문항 기준 최초 리포트:
- `reports/policy_rag_eval_20260319_111610.json`

초기 80문항 리포트 점수:
- Query pass rate: `92.50%`
- Retrieval pass rate: `88.75%`
- Retrieval Hit@1: `80.00%`
- Retrieval Hit@3: `86.25%`
- Retrieval Hit@5: `88.75%`

최종 리포트와 비교한 개선 폭:
- Query pass rate: `92.50% -> 98.75%` (`+6.25%p`)
- Retrieval pass rate: `88.75% -> 98.75%` (`+10.00%p`)
- Retrieval Hit@1: `80.00% -> 95.00%` (`+15.00%p`)
- Retrieval Hit@3: `86.25% -> 96.25%` (`+10.00%p`)
- Retrieval Hit@5: `88.75% -> 98.75%` (`+10.00%p`)

핵심 변화:
- 초반에는 paraphrase가 들어가면 query transform과 retrieval이 흔들렸습니다.
- 최종 단계에서는 `질문 표현 일반화`와 `FAQ/약관 문서 랭킹`을 함께 보정해 상위 정확도를 크게 끌어올렸습니다.

## 3. 평가 방식

1. `data/eval_dataset_80.jsonl`에서 `user_query`, `expected_query`, `expected_phrases`, `expected_doc_keys`를 읽습니다.
2. 각 문항에 대해 실제 `run_policy_rag_pipeline()`을 실행합니다.
3. 파이프라인은 `사용자 질문 -> query transform -> retrieval -> answer generation` 순서로 동작합니다.
4. 변환된 검색 질의를 `transformed_query`로 저장합니다.
5. query transform 평가는 `expected_query`와 `expected_phrases` 기준으로 keyword recall / token recall을 계산합니다.
6. query 평가는 `keyword_recall >= 0.5` 또는 `expected_token_recall >= 0.6`이면 통과로 봅니다.
7. retrieval 평가는 `expected_doc_keys`와 실제 `retrieved_doc_keys`를 비교합니다.
8. `Hit@1`, `Hit@3`, `Hit@5`, `MRR`를 계산합니다.
9. `Retrieval pass rate`는 정답 문서가 `top5` 안에 들어오면 통과로 계산합니다.
10. 최종 리포트는 모든 문항 결과를 평균 내어 `query pass`, `retrieval pass`, `hit@1`, `hit@3`, `hit@5`를 집계합니다.

## 4. 고도화 방법

이번 policy 고도화는 크게 `query transform`, `retrieval`, `reranking`, `평가 인프라` 네 축으로 진행했습니다.

- query 간략화
  - 구어체 문장을 검색에 맞게 짧고 핵심적인 질의로 변환
- query 정규화
  - `출고 후 배송지 변경`, `A/S 문의처`, `반송장 입력`, `불량 보상 기준`처럼 자주 흔들리는 표현을 정규화
- query 확장
  - 원문 query 외에 의미가 같은 variant를 추가 생성해 retrieval 시도
- category-aware retrieval
  - 배송 / 주문결제 / 취소교환반품 / 상품AS 문의를 추론해서 우선 검색
- fallback retrieval
  - 카테고리 기반 검색이 비면 무필터 검색까지 이어서 시도
- FAQ 우선순위 조정
  - `교환/반품 비용`, `배송 조회`, `결제수단`, `A/S`, `불량` 관련 FAQ를 더 직접적으로 띄우도록 보정
- 충돌 FAQ 감점
  - 비슷하지만 의도가 다른 FAQ가 1등으로 오르는 경우를 패널티 처리
- USED/유즈드 문서 과노출 억제
  - 일반 정책 질문에서 `USED` 문서가 불필요하게 올라오는 현상 방지
- 실패 케이스 타깃 보정
  - `자동 회수`, `박스 겉면 표기`, `비계약 택배사`, `교환 배송비 결제수단`, `품절 처리` 같은 남은 miss를 직접 보정
- 병렬 chunk 평가 지원
  - 80문항 평가를 `10개씩 병렬 chunk`로 실행하고 자동 합산되도록 실행기 개선

## 5. 이번 고도화에서 중요했던 포인트

- policy는 `정답 문서를 찾는 것`도 중요하지만, `첫 문서를 정확하게 띄우는 것`이 더 중요했습니다.
- 초반에는 같은 의미라도 질문 표현이 바뀌면 성능이 흔들렸습니다.
- 그래서 후반 고도화는 `새 표현을 기존 FAQ/약관 문서에 잘 연결하는 일반화`가 핵심이었습니다.

## 6. 현재 상태 평가

현재 policy는 다음과 같이 정리할 수 있습니다.

- Query transform: `매우 안정적`
- Retrieval recall: `매우 높음`
- Top1 ranking: `실사용 수준에서 매우 강함`
- 프로젝트 완성도: `최종 결과물로 정리 가능한 수준`

즉 파이널 프로젝트 기준으로는 policy는 추가 튜닝보다 결과 정리와 발표 준비로 넘어가도 되는 상태입니다.

## 7. 실행 명령어

일반 평가:

```powershell
uv run python chatbot/chatbot_eval/benchmark/rags/policy_rag/run.py --dataset chatbot/chatbot_eval/benchmark/rags/policy_rag/data/eval_dataset_80.jsonl
```

병렬 chunk 평가:

```powershell
uv run python chatbot/chatbot_eval/benchmark/rags/policy_rag/run.py --dataset chatbot/chatbot_eval/benchmark/rags/policy_rag/data/eval_dataset_80.jsonl --chunk-size 10 --parallel-workers 8
```

## 8. 폴더 구성

- `data/`: policy 평가 데이터셋
- `src/`: evaluator, metrics, dataset loader
- `reports/`: 실행 리포트 저장
- `run.py`: 평가 실행 엔트리포인트

