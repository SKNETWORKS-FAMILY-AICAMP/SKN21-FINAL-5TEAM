# KOLD 가드레일 벤치마크 결과 리포트

## 1. 평가 요약
- **전체 데이터 샘플 수**: 40429
- **평가된 샘플 수**: 500
- **오류 발생 수**: 0

## 2. 성능 지표 (Performance Metrics)
| 지표 (Metric) | 값 (Value) |
| :--- | :--- |
| **정확도 (Accuracy)** | 0.5000 |
| **정밀도 (Precision, 차단 기준)** | 1.0000 |
| **재현율 (Recall, 차단 기준)** | 0.0234 |
| **F1-Score (차단 기준)** | 0.0458 |
| **미탐율 (False Negative Rate, FNR)** | 0.9766 |
| **오탐율 (False Positive Rate, FPR)** | 0.0000 |

## 3. 혼동 행렬 (Confusion Matrix)
| | 예측 통과 (ALLOW, 0) | 예측 차단 (BLOCK, 1) |
| :--- | :---: | :---: |
| **실제 통과 (ALLOW, 0)** | 정탐(TN): 244 | 오탐(FP): 0 |
| **실제 차단 (BLOCK, 1)** | 미탐(FN): 250 | 정탐(TP): 6 |

## 4. 분석 상세 파일
- 미탐 사례 (False Negatives): [kold_false_negatives.csv](./kold_false_negatives.csv)
- 오탐 사례 (False Positives): [kold_false_positives.csv](./kold_false_positives.csv)

---
*생성 시간: 2026-03-06 14:49:45*
