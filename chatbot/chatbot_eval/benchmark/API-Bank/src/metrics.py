"""
metrics.py

평가 결과에서 API-Bank 핵심 지표를 계산하고 보고서를 저장합니다.

지표 정의:
  - Slot Filling Rate (SFR)      : "slot" 턴 정답률
  - API Call Accuracy (ACA)      : "call" 턴 정답률
  - Response Completion Rate (RCR): "completion" 턴 정답률
  - Task Completion Rate (TCR)   : 다이얼로그 단위 완료율 (모든 턴 pass)
  - Overall Score                : SFR, ACA, RCR 산술 평균
"""

import json
import os
from datetime import datetime
from typing import Dict, List


def compute_metrics(results: List[Dict]) -> Dict:
    """평가 결과 리스트에서 지표를 계산합니다."""
    slot_pass = slot_total = 0
    call_pass = call_total = 0
    completion_pass = completion_total = 0
    dialog_pass_count = 0

    for dialog in results:
        for turn in dialog.get("turns", []):
            t = turn.get("type_of_output", "")
            p = bool(turn.get("pass", False))
            if t == "slot":
                slot_total += 1
                slot_pass += int(p)
            elif t == "call":
                call_total += 1
                call_pass += int(p)
            elif t == "completion":
                completion_total += 1
                completion_pass += int(p)
        dialog_pass_count += int(bool(dialog.get("dialog_pass", False)))

    def safe_div(a: int, b: int) -> float:
        return a / b if b > 0 else 0.0

    sfr = safe_div(slot_pass, slot_total)
    aca = safe_div(call_pass, call_total)
    rcr = safe_div(completion_pass, completion_total)
    tcr = safe_div(dialog_pass_count, len(results))

    # Overall: SFR·ACA·RCR 의 산술 평균 (모두 0 인 경우 제외)
    component_values = [v for v in [sfr, aca, rcr] if True]
    overall = sum(component_values) / len(component_values) if component_values else 0.0

    return {
        "slot_filling_rate": sfr,
        "slot_pass": slot_pass,
        "slot_total": slot_total,
        "api_call_accuracy": aca,
        "call_pass": call_pass,
        "call_total": call_total,
        "response_completion_rate": rcr,
        "completion_pass": completion_pass,
        "completion_total": completion_total,
        "task_completion_rate": tcr,
        "dialog_pass": dialog_pass_count,
        "dialog_total": len(results),
        "overall_score": overall,
    }


def compute_metrics_per_user(results: List[Dict]) -> Dict[str, Dict]:
    """user_email 기준으로 그룹핑하여 사용자별 지표를 계산합니다.

    generate 스크립트에서 각 dialog에 user_id, user_email을 설정하므로
    평가 결과에서도 user row별로 지표를 산출합니다.

    Returns:
        {user_email: {metrics_dict}, ...}
    """
    # user_email 기준으로 결과 그룹핑
    grouped: Dict[str, List[Dict]] = {}
    for dialog in results:
        email = dialog.get("user_email", "unknown")
        if email not in grouped:
            grouped[email] = []
        grouped[email].append(dialog)

    # 사용자별 지표 계산
    per_user: Dict[str, Dict] = {}
    for email, user_results in grouped.items():
        user_metrics = compute_metrics(user_results)
        user_metrics["user_email"] = email
        user_metrics["user_id"] = user_results[0].get("user_id")
        per_user[email] = user_metrics

    return per_user


def save_report(
    metrics: Dict,
    results: List[Dict],
    model: str,
    output_dir: str,
) -> str:
    """평가 결과를 JSON 및 Markdown 보고서로 저장합니다."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── JSON 점수 파일 ──────────────────────────────────────────────────────
    score_path = os.path.join(output_dir, f"api_bank_{model}.eval_score.json")
    with open(score_path, "w", encoding="utf-8") as f:
        json.dump(
            {"model": model, "timestamp": timestamp, "metrics": metrics},
            f,
            ensure_ascii=False,
            indent=2,
        )

    # ── Markdown 보고서 ─────────────────────────────────────────────────────
    md_path = os.path.join(output_dir, f"api_bank_{model}.report.md")

    # 다이얼로그별 결과 테이블 행
    dialog_rows = ""
    for d in results:
        status = "✅ 통과" if d["dialog_pass"] else "❌ 실패"
        turn_count = len(d.get("turns", []))
        pass_count = sum(1 for t in d.get("turns", []) if t.get("pass"))
        user_email = d.get("user_email", "")
        dialog_rows += (
            f"| {d['dialog_num']} | {d['dialog_name']} | {user_email} | {status} "
            f"| {pass_count}/{turn_count} 턴 |\n"
        )

    # 사용자별 지표
    per_user = compute_metrics_per_user(results)
    user_rows = ""
    for email, um in per_user.items():
        user_rows += (
            f"| {email} | {um['dialog_pass']}/{um['dialog_total']} "
            f"| {um['api_call_accuracy'] * 100:.1f}% "
            f"| {um['response_completion_rate'] * 100:.1f}% "
            f"| {um['task_completion_rate'] * 100:.1f}% "
            f"| {um['overall_score'] * 100:.1f}% |\n"
        )

    md_content = f"""# 🤖 API-Bank 벤치마크 평가 보고서

- **생성 일시**: {timestamp}
- **평가 모델**: {model}
- **총 다이얼로그**: {metrics['dialog_total']}개
- **사용자 수**: {len(per_user)}명

---

## 📊 핵심 지표

| 지표 | 통과 | 전체 | 정답률 |
|:---|:---:|:---:|:---:|
| **Slot Filling Rate** (역질문 수집 능력) | {metrics['slot_pass']} | {metrics['slot_total']} | {metrics['slot_filling_rate'] * 100:.1f}% |
| **API Call Accuracy** (올바른 API 호출 능력) | {metrics['call_pass']} | {metrics['call_total']} | {metrics['api_call_accuracy'] * 100:.1f}% |
| **Response Completion Rate** (결과 전달 능력) | {metrics['completion_pass']} | {metrics['completion_total']} | {metrics['response_completion_rate'] * 100:.1f}% |
| **Task Completion Rate** (태스크 완료율) | {metrics['dialog_pass']} | {metrics['dialog_total']} | {metrics['task_completion_rate'] * 100:.1f}% |
| **Overall Score** | — | — | **{metrics['overall_score'] * 100:.1f}%** |

---

## 👤 사용자별 지표

| 사용자 | 다이얼로그 통과 | API Call | Completion | TCR | Overall |
|:---|:---:|:---:|:---:|:---:|:---:|
{user_rows}
---

## 📋 다이얼로그별 결과

| # | 다이얼로그 | 사용자 | 결과 | 턴 통과 |
|:---:|:---|:---|:---:|:---:|
{dialog_rows}
---

## 📖 지표 설명

- **Slot Filling Rate**: 필요 슬롯이 부족할 때 챗봇이 올바른 역질문으로 정보를 수집하는 능력
- **API Call Accuracy**: 충분한 정보가 주어졌을 때 올바른 API를 올바른 인자로 호출하는 능력
- **Response Completion Rate**: API 실행 결과를 자연스러운 한국어로 사용자에게 전달하는 능력
- **Task Completion Rate**: 하나의 다이얼로그에서 모든 턴이 pass 된 비율 (엔드-투-엔드 완료)

---

*본 보고서는 API-Bank 벤치마크에 의해 자동으로 생성되었습니다.*
"""

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return md_path
