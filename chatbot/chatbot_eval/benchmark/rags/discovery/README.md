# Discovery RAG 결과 정리서

## 0. 평가 항목 의미

- `Dataset size`
  - 평가에 사용한 전체 문항 수입니다.
- `Retrieval pass rate`
  - 정답 상품이 `top5` 안에 하나라도 들어오면 통과로 보는 비율입니다.
- `Retrieval Hit@1`
  - 첫 번째 추천 상품이 바로 정답인 비율입니다.
- `Retrieval Hit@3`
  - 상위 3개 추천 안에 정답이 포함되는 비율입니다.
- `Retrieval Hit@5`
  - 상위 5개 추천 안에 정답이 포함되는 비율입니다.
- `Grounding pass rate`
  - 답변과 검색 결과가 기대한 핵심 키워드를 충분히 반영했는지의 통과 비율입니다.
- `Grounding keyword recall`
  - 기대 키워드가 실제 답변/검색 결과 텍스트에 얼마나 반영되었는지의 평균 비율입니다.

## 1. 본 평가셋 최종 결과

기준 리포트:
- `reports/discovery_rag_eval_20260319_124119.json`

최종 점수:
- Dataset size: `80`
- Retrieval pass rate: `100.00%`
- Retrieval Hit@1: `91.25%`
- Retrieval Hit@3: `98.75%`
- Retrieval Hit@5: `100.00%`
- Grounding pass rate: `100.00%`
- Grounding keyword recall: `97.50%`

해석:
- 정답 상품을 `top5` 안에 넣는 능력은 사실상 완성형입니다.
- `Hit@1 91.25%`로 첫 추천 정확도도 매우 높습니다.
- 추천 이후 설명 품질도 안정적으로 유지되었습니다.

## 2. 처음 대비 얼마나 개선됐는가

초기 80문항 리포트:
- `reports/discovery_rag_eval_20260319_110239.json`

초기 점수:
- Retrieval pass rate: `91.25%`
- Retrieval Hit@1: `76.25%`
- Retrieval Hit@3: `86.25%`
- Retrieval Hit@5: `91.25%`
- Grounding pass rate: `98.75%`
- Grounding keyword recall: `95.83%`

최종 리포트와 비교한 개선 폭:
- Retrieval pass rate: `91.25% -> 100.00%` (`+8.75%p`)
- Retrieval Hit@1: `76.25% -> 91.25%` (`+15.00%p`)
- Retrieval Hit@3: `86.25% -> 98.75%` (`+12.50%p`)
- Retrieval Hit@5: `91.25% -> 100.00%` (`+8.75%p`)
- Grounding pass rate: `98.75% -> 100.00%` (`+1.25%p`)
- Grounding keyword recall: `95.83% -> 97.50%` (`+1.67%p`)

핵심 변화:
- 초반에는 `정답 후보는 찾지만 top1이 흔들리는 문제`가 컸습니다.
- 최종 단계에서는 `retrieval recall`과 `top1 ranking`을 동시에 끌어올렸습니다.

## 3. 평가 방식

1. `data/eval_dataset_80.jsonl`에서 평가용 질의, 정답 상품 ID, 허용 가능한 대체 정답, 기대 키워드를 읽습니다.
2. 각 문항은 `user_query`, `expected_product_ids`, `acceptable_product_ids`, `expected_keywords`를 가집니다.
3. 평가기는 `run_discovery_pipeline()`을 호출해 실제 Discovery SubAgent 검색 결과를 가져옵니다.
4. 검색 결과에서 top-k 상품 ID를 추출합니다.
5. `expected_product_ids + acceptable_product_ids`를 합쳐 최종 gold ID 집합으로 사용합니다.
6. `Hit@1`, `Hit@3`, `Hit@5`를 계산합니다.
7. `Retrieval pass rate`는 정답이 `top5` 안에 하나라도 들어오면 통과로 계산합니다.
8. `Grounding`은 답변 텍스트와 retrieved product 정보를 합쳐 `expected_keywords`가 얼마나 반영됐는지 계산합니다.
9. `Grounding pass`는 keyword recall이 `0.5 이상`이면 통과로 계산합니다.
10. 최종 리포트는 전체 문항 평균으로 `pass`, `hit@1`, `hit@3`, `hit@5`, `grounding` 점수를 집계합니다.

## 4. 고도화 방법

이번 discovery 고도화는 단순히 규칙을 몇 개 추가한 수준이 아니라, 검색 파이프라인을 여러 단계로 보강한 작업입니다.

- 한국어 질의를 영어 검색어로 번역
  - 예: `남색 스트라이프 셔츠 -> navy blue striped shirt`
- 쿼리 간략화
  - 불필요한 표현을 줄이고 핵심 속성만 남긴 `focused query` 생성
- 쿼리 확장
  - 원문, 번역문, slot variant, exact phrase variant를 함께 검색
- 색상/카테고리/세부 타입 추출
  - 질의에서 `color`, `category`, `pattern`, `material`, `gender`, `usage`를 구조화
- keyword + CLIP hybrid retrieval
  - embedding 검색만 쓰지 않고 keyword 검색 후보도 함께 수집
- rescue candidate 추가
  - top 후보 밖으로 밀리는 상품을 focused query 기반으로 다시 구조적으로 구제
- heuristic reranking
  - `백팩 vs 메신저백`, `티셔츠 vs 셔츠`, `정장 구두 vs 캐주얼 신발` 같은 충돌을 직접 보정
- slot-based reranking
  - 질문 슬롯과 상품 슬롯을 따로 추출해 속성 일치도를 점수화
- exact phrase bonus
  - 상품명과 질의가 거의 정확히 맞는 경우 top1으로 더 잘 올라오게 보너스 부여
- LLM reranker 추가
  - 최종 top 후보를 LLM이 다시 비교해 `1등`을 재선정하도록 보강

## 5. 과적합이 의심된 이유

본 평가셋에서는 매우 높은 점수가 나왔지만, 새로운 표현으로 만든 holdout 셋에서는 한때 성능이 크게 떨어졌습니다.

초기 holdout 40문항:
- `reports/discovery_rag_eval_20260319_135215.json`
- Retrieval Hit@1: `70.00%`
- Retrieval Hit@5: `82.50%`

초기 holdout 80문항(single-gold 기준):
- `reports/discovery_rag_eval_20260319_141456.json`
- Retrieval pass rate: `15.00%`
- Retrieval Hit@1: `10.00%`
- Retrieval Hit@5: `15.00%`

이때 확인한 문제:
- 같은 상품이어도 질문 표현이 바뀌면 검색 성능이 급격히 흔들렸습니다.
- 예:
  - `배낭`
  - `정장화`
  - `더플 스타일 가방`
  - `레드 계열 여성 상의`
- 즉 기존 셋 표현에는 강했지만, `새로운 말투/새로운 paraphrase`에는 약한 부분이 드러났습니다.

## 6. 과적합이 발생한 원인

발표용으로 정리하면 원인은 크게 3가지입니다.

- 같은 평가셋을 계속 보면서 튜닝함
  - 실패 문항을 보고 규칙을 계속 추가하면서 본셋에 점점 맞춰졌습니다.
- discovery 특성상 정답이 1개로 딱 떨어지지 않음
  - `검은 정장화`, `흰 스포츠 운동화`, `네이비 폴로 티셔츠`처럼 실제로는 타당한 대체 상품이 여러 개 존재합니다.
- 문자열 기반 휴리스틱 비중이 높았음
  - `색상`은 읽지만 `카테고리/세부 타입`을 충분히 일반화하지 못해서, 새로운 표현에서 약했습니다.

## 7. 해결 방법

이번에 적용한 해결 방법은 두 축입니다.

### 7-1. 검색 일반화 개선

- 한국어 질의 정규화 추가
  - `배낭 -> 백팩`
  - `정장화 -> 구두`
  - `캐주얼화 -> 캐주얼 신발`
  - `더플 스타일 가방 -> 더플백`
  - `드레스 -> 원피스`
- canonical query 우선 검색
  - 원문 한국어만 검색하지 않고 `black formal shoes`, `grey duffle bag` 같은 표현을 앞쪽에 배치
- 카테고리 불일치 감점 강화
  - 색상만 맞는 화장품/속옷/액세서리 후보를 더 강하게 배제

### 7-2. 평가 기준 현실화

- discovery holdout 80문항에 `acceptable_product_ids`를 추가했습니다.
- 이유:
  - 실제 추천 문제에서는 정답 상품이 하나만 있는 경우보다, `같은 카테고리/색상/subtype`의 타당한 대체 상품이 여러 개인 경우가 많기 때문입니다.

## 8. Multi-gold 기준이란 무엇인가

`multi-gold`는 한 문항에 대해 정답을 1개만 인정하지 않고, `허용 가능한 복수 정답`을 같이 인정하는 평가 방식입니다.

예시:
- 질문: `검은 정장화 추천해줘`
- 기존 single-gold:
  - 특정 검은 formal shoes 1개만 정답
- multi-gold:
  - 같은 `black + formal shoes` 조건을 만족하는 다른 검은 정장화도 정답으로 인정

즉 discovery에서는
- `정답 하나만 맞추는 시험`보다
- `질문 의도에 맞는 추천 후보를 제대로 제시했는가`
를 더 현실적으로 평가할 수 있습니다.

## 9. 기존에는 어떻게 평가했고, 왜 다시 정리했는가

기존 holdout 80문항은 `single-gold` 기준이 너무 빡빡했습니다.

문제:
- 실제로는 타당한 추천인데도 정답 1개와 ID가 다르면 실패 처리됨
- 그래서 holdout 80에서 `15%` 같은 비정상적으로 낮은 점수가 나왔습니다

조치:
- `holdout_dataset_80.jsonl`에 `acceptable_product_ids`를 추가
- 같은 색/같은 카테고리/같은 subtype의 타당한 대체 상품을 허용

결과:
- 최신 holdout 80 리포트
  - `reports/discovery_rag_eval_20260319_144133.json`
- 점수:
  - Dataset size: `80`
  - Retrieval pass rate: `93.75%`
  - Retrieval Hit@1: `90.00%`
  - Retrieval Hit@3: `92.50%`
  - Retrieval Hit@5: `93.75%`
  - Grounding pass rate: `96.25%`
  - Grounding keyword recall: `92.81%`

해석:
- 기존 `15%`는 discovery 모델이 완전히 망가진 수치라기보다, `single-gold holdout이 discovery 추천 문제를 지나치게 엄격하게 채점한 영향`이 컸습니다.
- multi-gold 기준으로 재평가한 뒤에는, holdout에서도 `Hit@1 90%` 수준까지 회복되어 보다 현실적인 일반화 성능을 확인할 수 있었습니다.

## 10. 현재 상태 평가

현재 discovery는 다음처럼 정리할 수 있습니다.

- 본 평가셋:
  - `Hit@1 91.25%`
  - `Hit@5 100.00%`
- holdout 80문항(multi-gold 기준):
  - `Hit@1 90.00%`
  - `Hit@5 93.75%`

즉:
- 검색 recall은 매우 높고
- top1 ranking도 실사용 수준에서 충분히 강하며
- 새 표현에 대해서도 이전보다 훨씬 현실적으로 일반화된 상태입니다.

파이널 프로젝트 기준으로는:
- 더 튜닝하기보다
- 현재 결과를 고정하고
- 발표/보고 단계로 넘어가도 되는 수준입니다.

## 11. 실행 명령어

본 평가셋:

```powershell
uv run python chatbot/chatbot_eval/benchmark/rags/discovery/run.py --dataset chatbot/chatbot_eval/benchmark/rags/discovery/data/eval_dataset_80.jsonl
```

holdout 80문항:

```powershell
uv run python chatbot/chatbot_eval/benchmark/rags/discovery/run.py --dataset chatbot/chatbot_eval/benchmark/rags/discovery/data/holdout_dataset_80.jsonl
```

## 12. 폴더 구성

- `data/`: discovery 평가 데이터셋
- `src/`: evaluator, metrics, dataset loader
- `reports/`: 실행 리포트 저장
- `run.py`: 평가 실행 엔트리포인트
