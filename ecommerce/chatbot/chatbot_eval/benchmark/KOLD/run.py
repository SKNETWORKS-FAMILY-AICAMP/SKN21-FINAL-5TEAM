import sys
from pathlib import Path
from datasets import load_dataset
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, confusion_matrix
import pandas as pd

# 프로젝트 루트 및 현재 디렉토리 설정
current_dir = Path(__file__).resolve().parent
PROJECT_ROOT = current_dir.parent.parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ecommerce.chatbot.src.graph.nodes.guardrail import guardrail_node, load_guardrail_model
from langchain_core.messages import HumanMessage

# --------------------------------------------------
# 1. 데이터 로드
# --------------------------------------------------
ds = load_dataset("json", data_files=str(current_dir / "data" / "kold_v1.json"))

# 보통 test가 있으면 test 사용, 없으면 validation 또는 train 일부 사용
if "test" in ds:
    data = ds["test"]
elif "validation" in ds:
    data = ds["validation"]
else:
    data = ds["train"]

print("columns:", data.column_names)
print("sample:", data[0])

# --------------------------------------------------
# 2. 컬럼명 설정
# --------------------------------------------------
TEXT_COL = "comment"          # KOLD v1 기준 'comment'
LABEL_COL = "OFF"              # KOLD v1 기준 'OFF' (Offensive 여부)

# 모델 로드
load_guardrail_model()

# --------------------------------------------------
# 3. KOLD 라벨 -> guardrail용 이진 라벨 변환
# y_true: 1 = BLOCK, 0 = ALLOW (챗봇 입장에서 차단 여부)
# --------------------------------------------------
def map_to_binary_label(value):
    """
    KOLD의 실제 라벨 형태에 맞게 수정하는 함수.
    y_true: 1 = Offensive (BLOCK), 0 = Non-offensive (ALLOW)
    """
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return 1 if value == 1 else 0
    if isinstance(value, str):
        v = value.strip().lower()
        offensive_values = {"offensive", "off", "hate", "abusive", "toxic", "1", "yes", "true"}
        neutral_values = {"neutral", "none", "non-offensive", "0", "no", "false"}
        if v in offensive_values: return 1
        if v in neutral_values: return 0
    return 0 # 기본값 안내

# --------------------------------------------------
# 4. 실제 프로젝트 Guardrail 함수 적용
# True -> BLOCK (1), False -> ALLOW (0)
# --------------------------------------------------
def simple_guardrail(text: str) -> tuple[bool, str, float]:
    """
    실제 guardrail_node를 호출하여 차단 여부, 라벨, 스코어를 반환합니다.
    """
    state = {
        "messages": [HumanMessage(content=text)]
    }
    
    # 실제 노드 실행
    result = guardrail_node(state)
    is_blocked = not result.get("guardrail_passed", True)
    
    # 로깅을 위해 모델 접근 (결과값만 가져옴)
    from ecommerce.chatbot.src.graph.nodes.guardrail import _GUARDRAIL_PIPELINE
    label, score = "unknown", 0.0
    if _GUARDRAIL_PIPELINE:
        res = _GUARDRAIL_PIPELINE(text)
        top = res[0][0] if isinstance(res[0], list) else res[0]
        label = top["label"].lower()
        score = top["score"]
        
    return is_blocked, label, score


# --------------------------------------------------
# 5. 평가 실행
# --------------------------------------------------
rows = []
errors = 0

for item in list(data)[:500]:
    try:
        text = item[TEXT_COL]
        raw_label = item[LABEL_COL]

        y_true = map_to_binary_label(raw_label)      # 1=BLOCK, 0=ALLOW
        is_blocked, pred_label, pred_score = simple_guardrail(text)
        y_pred = 1 if is_blocked else 0

        rows.append({
            "text": text,
            "raw_label": raw_label,
            "y_true": y_true,
            "y_pred": y_pred,
            "pred_label": pred_label,
            "pred_score": pred_score,
            "correct": int(y_true == y_pred),
        })
    except Exception as e:
        errors += 1
        if errors < 5:  # 처음 5개 에러만 출력
            print(f"Error processing item: {e}")
        rows.append({
            "text": item.get(TEXT_COL, ""),
            "raw_label": item.get(LABEL_COL, None),
            "y_true": None,
            "y_pred": None,
            "correct": None,
            "error": str(e),
        })

df = pd.DataFrame(rows)

eval_df = df.dropna(subset=["y_true", "y_pred"]).copy()
eval_df["y_true"] = eval_df["y_true"].astype(int)
eval_df["y_pred"] = eval_df["y_pred"].astype(int)

# --------------------------------------------------
# 6. 지표 계산
# --------------------------------------------------
acc = accuracy_score(eval_df["y_true"], eval_df["y_pred"])
precision, recall, f1, _ = precision_recall_fscore_support(
    eval_df["y_true"], eval_df["y_pred"], average="binary", pos_label=1
)

tn, fp, fn, tp = confusion_matrix(eval_df["y_true"], eval_df["y_pred"], labels=[0, 1]).ravel()

false_negative_rate = fn / (fn + tp) if (fn + tp) > 0 else 0.0
false_positive_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0


# --------------------------------------------------
# 7. 실패 사례 및 결과 리포트 저장
# --------------------------------------------------
# --------------------------------------------------
# 7. 실패 사례 및 결과 리포트 저장
# --------------------------------------------------
false_negatives = eval_df[(eval_df["y_true"] == 1) & (eval_df["y_pred"] == 0)].copy()
false_positives = eval_df[(eval_df["y_true"] == 0) & (eval_df["y_pred"] == 1)].copy()

# 절대 경로로 변환하여 확실하게 저장 (JSONL 형식)
fn_path = (current_dir / "kold_false_negatives.jsonl").absolute()
fp_path = (current_dir / "kold_false_positives.jsonl").absolute()
result_md_path = (current_dir / "result.md").absolute()

try:
    # JSONL 형식으로 저장 (각 행이 독립된 JSON 객체)
    false_negatives.to_json(str(fn_path), orient='records', lines=True, force_ascii=False)
    false_positives.to_json(str(fp_path), orient='records', lines=True, force_ascii=False)

    # 마크다운 리포트 생성
    report_content = f"""# KOLD 가드레일 벤치마크 결과 리포트

## 1. 평가 요약
- **전체 데이터 샘플 수**: {len(data)}
- **평가된 샘플 수**: {len(eval_df)}
- **오류 발생 수**: {errors}

## 2. 성능 지표 (Performance Metrics)
| 지표 (Metric) | 값 (Value) |
| :--- | :--- |
| **정확도 (Accuracy)** | {acc:.4f} |
| **정밀도 (Precision, 차단 기준)** | {precision:.4f} |
| **재현율 (Recall, 차단 기준)** | {recall:.4f} |
| **F1-Score (차단 기준)** | {f1:.4f} |
| **미탐율 (False Negative Rate, FNR)** | {false_negative_rate:.4f} |
| **오탐율 (False Positive Rate, FPR)** | {false_positive_rate:.4f} |

## 3. 혼동 행렬 (Confusion Matrix)
| | 예측 통과 (ALLOW, 0) | 예측 차단 (BLOCK, 1) |
| :--- | :---: | :---: |
| **실제 통과 (ALLOW, 0)** | 정탐(TN): {tn} | 오탐(FP): {fp} |
| **실제 차단 (BLOCK, 1)** | 미탐(FN): {fn} | 정탐(TP): {tp} |

## 4. 분석 상세 파일
- 미탐 사례 (False Negatives): [kold_false_negatives.jsonl](./kold_false_negatives.jsonl)
- 오탐 사례 (False Positives): [kold_false_positives.jsonl](./kold_false_positives.jsonl)

---
*생성 시간: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""

    with open(str(result_md_path), "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"\n===== Guardrail Benchmark Result =====")
    print(f"total samples        : {len(data)}")
    print(f"evaluated samples    : {len(eval_df)}")
    print(f"errors               : {errors}")
    print(f"accuracy             : {acc:.4f}")
    print(f"precision (BLOCK)    : {precision:.4f}")
    print(f"recall (BLOCK)       : {recall:.4f}")
    print(f"f1 (BLOCK)           : {f1:.4f}")
    print(f"false_negative_rate  : {false_negative_rate:.4f}")
    print(f"false_positive_rate  : {false_positive_rate:.4f}")
    print(f"TP={tp}, FP={fp}, TN={tn}, FN={fn}")

    print(f"\n[성공] 데이터 저장 완료:")
    print(f"- 리포트: {result_md_path}")
    print(f"- 미탐 사례: {fn_path} ({len(false_negatives)}건 저장)")
    print(f"- 오탐 사례: {fp_path} ({len(false_positives)}건 저장)")

except Exception as e:
    print(f"\n[오류] 파일 저장 중 에러 발생: {e}")
