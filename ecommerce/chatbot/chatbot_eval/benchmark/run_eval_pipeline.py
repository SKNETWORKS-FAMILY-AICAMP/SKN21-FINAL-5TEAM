import os
import json
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# 경로 설정
CUR_DIR = Path(__file__).resolve().parent
BENCH_DIR = CUR_DIR / "FunctionChat-Bench"
RESULTS_DIR = CUR_DIR.parent / "results"
ENV_PATH = CUR_DIR.parents[3] / ".env"

# .env 로드
load_dotenv(ENV_PATH)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def validate_and_normalize_dataset(file_path):
    """JSONL 데이터셋 파일의 유효성을 검사하고 한 줄에 하나의 JSON 객체가 오도록 정규화합니다."""
    if not file_path.exists():
        print(f"⚠️ 데이터셋 파일을 찾을 수 없습니다: {file_path}")
        return False

    print(f"🔍 데이터셋 정규화 체크: {file_path.name}")
    try:
        valid_lines = []
        with open(file_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    # JSON 유효성 검사
                    json.loads(line)
                    valid_lines.append(line)
                except json.JSONDecodeError:
                    print(f"  📍 {i}행에서 JSON 오류 발생, 복구 시도 중...")
                    # 한 줄에 여러 객체가 섞여있는 경우 처리
                    parts = re.split(r'(?={"function_num":)', line)
                    for p in parts:
                        p = p.strip()
                        if not p:
                            continue
                        try:
                            json.loads(p)
                            valid_lines.append(p)
                        except:
                            continue

        # 정규화된 내용으로 파일 덮어쓰기
        with open(file_path, "w", encoding="utf-8") as f:
            for line in valid_lines:
                f.write(line + "\n")

        print(f"✅ 데이터셋 정규화 완료 (총 {len(valid_lines)}개 샘플)")
        return True
    except Exception as e:
        print(f"❌ 데이터셋 검사 중 치명적 오류: {e}")
        return False


def run_single_benchmark(name, cmd):
    """개별 벤치마크를 실행하고 결과를 반환합니다."""
    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")

    # 보안: API 키 마스킹하여 명령어 출력
    safe_cmd: list[str] = [arg if arg != OPENAI_API_KEY else "sk-****" for arg in cmd]
    print(f"  CMD: {' '.join(safe_cmd[i] for i in range(min(6, len(safe_cmd))))} ...")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        cmd, cwd=BENCH_DIR, capture_output=True, text=False, env=env
    )

    stdout_text = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

    if stdout_text:
        for line in stdout_text.strip().splitlines():
            print(f"  | {line}")

    if result.returncode != 0:
        print(f"  ❌ {name} 실패! (exit code: {result.returncode})")
        if stderr_text:
            for line in stderr_text.strip().splitlines()[-10:]:
                print(f"  ⚠ {line}")
        return False

    print(f"  ✅ {name} 완료")
    return True


def run_evaluation(mode=0):
    """
    mode가 1이면 Argument Accuracy만 평가합니다.
    그 외의 값이면 전체 벤치마크를 실행합니다.
    """
    print("🚀 FunctionChat-Bench 평가 파이프라인 시작...")
    print(f"   벤치마크 디렉토리: {BENCH_DIR}")
    print(f"   결과 저장 디렉토리: {RESULTS_DIR}")

    # 데이터셋 경로
    arg_accuracy_dataset = BENCH_DIR / "data" / "my_eval_arg_accuracy_dialog_20_2.jsonl"
    dialog_dataset = BENCH_DIR / "data" / "my_eval_slot_filling_rate_dialogs.jsonl"

    # 0. 데이터셋 검증
    for ds_path in [arg_accuracy_dataset, dialog_dataset]:
        if not validate_and_normalize_dataset(ds_path):
            print(f"❌ 데이터셋 검증 실패: {ds_path.name}")
            return {}

    results = {}

    # 1. Dialog (Argument Accuracy) 평가
    cmd_single = [
        sys.executable,
        "evaluate.py",
        "dialog",
        "--model",
        "gpt-4o-mini",
        "--input_path",
        f"data/{arg_accuracy_dataset.name}",
        "--system_prompt_path",
        "data/system_prompt.txt",
        "--temperature",
        "0.0",
        "--api_key",
        OPENAI_API_KEY,
        "--num_samples",
        "20",
        "--is_batch",
        "False",
        "--reset",
        "True",
    ]
    results["arg_accuracy"] = run_single_benchmark(
        "[1/2] Dialog — Argument Accuracy", cmd_single
    )

    if mode == 1:
        print("\n🔹 인수에 '1'이 전달되어 Slot Filling Rate 벤치마크를 생략합니다.")
    else:
        # 2. Dialog (Slot Filling Rate) 평가
        cmd_dialog = [
            sys.executable,
            "evaluate.py",
            "dialog",
            "--model",
            "gpt-4o-mini",
            "--input_path",
            f"data/{dialog_dataset.name}",
            "--system_prompt_path",
            "data/system_prompt.txt",
            "--temperature",
            "0.0",
            "--api_key",
            OPENAI_API_KEY,
            "--num_samples",
            "11",
            "--is_batch",
            "False",
            "--reset",
            "True",
        ]
        results["dialog"] = run_single_benchmark(
            "[2/2] Dialog — Slot Filling Rate", cmd_dialog
        )

    # 요약
    print(f"\n{'=' * 60}")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"  📋 전체 결과: {passed}/{total} 벤치마크 성공")
    for name, ok in results.items():
        status = "✅ 성공" if ok else "❌ 실패"
        print(f"   • {name}: {status}")
    print(f"{'=' * 60}\n")

    return results


def generate_markdown_report(results):
    """평가 결과를 Markdown 보고서로 생성합니다."""
    # 경로 구조: output/{benchmark_type}/{model_name}/...
    single_score_file = (
        BENCH_DIR
        / "output"
        / "arg_acc"
        / "gpt-4o-mini"
        / "FunctionChat-gpt-4o-mini.eval_score.json"
    )
    dialog_score_file = (
        BENCH_DIR
        / "output"
        / "slot_filling"
        / "gpt-4o-mini"
        / "FunctionChat-gpt-4o-mini.eval_score.json"
    )

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_name = f"eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = RESULTS_DIR / report_name

    # 실행 상태 요약
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    md_content = f"""# 🤖 챗봇 성능 평가 보고서
- **생성 일시**: {timestamp}
- **평가 프레임워크**: FunctionChat-Bench
- **대상 모델**: gpt-4o-mini
- **실행 결과**: {passed}/{total} 벤치마크 성공
 
## 📖 평가 벤치마크 설명
본 평가는 **FunctionChat-Bench** 프레임워크를 기반으로 수행되었습니다.
 
### 1. Argument Accuracy (Dialog)
- **평가 목적**: 챗봇이 멀티턴 대화에서 필요한 인자(Argument)를 얼마나 정확하게 추출하고 올바른 Tool을 호출하는지 측정합니다.
- **핵심 지표**: 필수 인자 추출 정확도, Tool 선택 정확성, enum 값 범위 준수 여부를 검증합니다.
- **데이터셋**: `my_eval_arg_accuracy_dialog_20.jsonl` (20개 다이얼로그)

### 2. Slot Filling Rate (Dialog)
- **평가 목적**: **Slot Filling Rate** — 누락 슬롯을 다중 턴 대화로 채워서 올바른 툴 호출까지 가는 능력을 측정합니다.
- **핵심 지표**: 사용자가 부족한 정보를 주었을 때 챗봇이 역질문(slot filling)을 통해 정보를 수집하고, 최종적으로 올바른 도구를 올바른 인자로 호출하는지 평가합니다.
- **데이터셋**: `my_eval_slot_filling_rate_dialogs.jsonl` (11개 다이얼로그)

"""

    # ── Argument Accuracy (Dialog) 결과 ──
    if not results.get("arg_accuracy"):
        md_content += "## 📊 [Benchmark 1] Argument Accuracy (Dialog)\n- ❌ 평가 실행에 실패했습니다.\n\n"
    elif single_score_file.exists():
        with open(single_score_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        sc = data.get("dialog_score", {})
        call_rate = sc.get("call pass rate", 0) * 100
        md_content += f"""## 📊 [Benchmark 1] Argument Accuracy (Dialog)
| 지표 | 결과 |
| :--- | :--- |
| **전체 테스트 케이스** | {sc.get("total_cnt", 0)}개 |
| **통과 수 (Pass)** | {sc.get("total_pass_cnt", 0)}개 |
| **Call 정답률** | {call_rate:.1f}% |
| **Micro 평균** | {sc.get("avg(micro)", 0) * 100:.1f}% |

"""
    else:
        md_content += "## 📊 [Benchmark 1] Argument Accuracy (Dialog)\n- 결과 파일을 찾을 수 없습니다.\n\n"

    # ── Dialog 결과 ──
    if not results.get("dialog"):
        md_content += "## 📊 [Benchmark 2] Slot Filling Rate (Dialog)\n- ❌ 평가 실행에 실패했습니다.\n\n"
    elif dialog_score_file.exists():
        with open(dialog_score_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        ds = data.get("dialog_score", {})

        slot_rate = ds.get("slot pass rate", 0) * 100
        call_rate = ds.get("call pass rate", 0) * 100
        comp_rate = ds.get("completion pass rate", 0) * 100

        md_content += f"""## 📊 [Benchmark 2] Slot Filling Rate (Dialog)
| 지표 | 결과 |
| :--- | :--- |
| **전체 테스트 케이스** | {ds.get("total_cnt", 0)}개 |
| **통과 수 (Pass)** | {ds.get("total_pass_cnt", 0)}개 |
| **Micro 평균** | {ds.get("avg(micro)", 0) * 100:.1f}% |

### 턴 유형별 상세 결과
| 턴 유형 | 통과 수 | 정답률 | 설명 |
| :--- | :--- | :--- | :--- |
| **Slot (역질문)** | {ds.get("slot pass cnt", 0)}개 | {slot_rate:.1f}% | 누락 슬롯을 역질문으로 수집하는 능력 |
| **Call (툴 호출)** | {ds.get("call pass cnt", 0)}개 | {call_rate:.1f}% | 올바른 툴을 올바른 인자로 호출하는 능력 |
| **Completion (결과 전달)** | {ds.get("completion pass cnt", 0)}개 | {comp_rate:.1f}% | 툴 실행 결과를 자연스럽게 안내하는 능력 |

"""
    else:
        md_content += "## 📊 [Benchmark 2] Slot Filling Rate (Dialog)\n- 결과 파일을 찾을 수 없습니다.\n\n"

    md_content += """---
*본 보고서는 `run_eval_pipeline.py`에 의해 자동으로 생성되었습니다.*
"""

    # 폴더 생성 및 저장
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"📖 보고서가 저장되었습니다: {report_path}")
    return report_path


if __name__ == "__main__":
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        sys.exit(1)

    eval_mode = 0
    if len(sys.argv) > 1 and sys.argv[1] == "1":
        eval_mode = 1

    results = run_evaluation(mode=eval_mode)
    if results:
        generate_markdown_report(results)
