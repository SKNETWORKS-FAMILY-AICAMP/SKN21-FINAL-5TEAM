import os
import sys
import json
import subprocess
import re
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# LangSmith 추적 여부는 하단 if __name__ == "__main__": 에서 args.trace 값에 따라 동적으로 결정됩니다.

# 경로 설정
CUR_DIR = Path(__file__).resolve().parent
BENCH_DIR = CUR_DIR
RESULTS_DIR = CUR_DIR.parent / "result" / "toolcall_acc"
ENV_PATH = CUR_DIR.parents[3] / ".env"

# .env 로드
if not ENV_PATH.exists():
    # Fallback: 한 단계 더 상위 확인 (모듈 위치에 따른 유연성)
    ENV_PATH = CUR_DIR.parents[4] / ".env"

load_dotenv(ENV_PATH)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
arg_accuracy_dataset = None


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


def count_lines(path):
    if not path.exists(): return 0
    with open(path, 'r', encoding='utf-8') as f:
        return sum(1 for _ in f)


def run_evaluation(mode=1, model="inhouse", trace_count=0, internal_model="gpt-4o-mini", reset=True, use_guardrail=True):
    """Argument Accuracy 평가를 실행합니다."""
    print("🚀 FunctionChat-Bench 평가 파이프라인 시작 (Argument Accuracy)...")
    print(f"   벤치마크 디렉토리: {BENCH_DIR}")
    print(f"   결과 저장 디렉토리: {RESULTS_DIR}")
    global  arg_accuracy_dataset
    # 데이터셋 경로 선택
    if mode == 1:
        arg_accuracy_dataset = BENCH_DIR / "data" / "my_eval_arg_accuracy_dialogs.jsonl"
    elif mode == 2:
        arg_accuracy_dataset = BENCH_DIR / "data" / "my_eval_arg_accuracy_dialogs2.jsonl"
    elif mode == 3:
        arg_accuracy_dataset = BENCH_DIR / "data" / "my_eval_arg_accuracy_dialogs3.jsonl"
    elif mode == 4:
        arg_accuracy_dataset = BENCH_DIR / "data" / "my_eval_arg_accuracy_dialogs4.jsonl"
    elif mode == 50:
        arg_accuracy_dataset = BENCH_DIR / "data" / "50" / "data" / "my_eval_arg_accuracy_dialogs50.jsonl"
    else:
        arg_accuracy_dataset = BENCH_DIR / "data" / "my_eval_arg_accuracy_dialogs.jsonl"

    arg_acc_count = count_lines(arg_accuracy_dataset)

    # 0. 데이터셋 검증
    if not validate_and_normalize_dataset(arg_accuracy_dataset):
        print(f"❌ 데이터셋 검증 실패: {arg_accuracy_dataset.name}")
        return {}

    results = {}

    # 1. Dialog (Argument Accuracy) 평가
    cmd_single = [
        sys.executable,
        "evaluate.py",
        "dialog",
        "--model",
        model,
    ]

    # 모든 모델은 로컬 어댑터(localhost:8081)를 거치도록 설정 (In-house 엔진 테스트 목적)
    cmd_single.extend([
        "--served_model_name", internal_model,
        "--base_url", "http://localhost:8081/v1",
        "--api_key", "inhouse"
    ])

    cmd_single.extend([
        "--input_path",
        str(arg_accuracy_dataset.relative_to(BENCH_DIR)),
        "--temperature",
        "0.0",
        "--trace_count",
        str(trace_count),
        "--is_batch",
        "False",
        "--reset",
        str(reset),
        "--only_exact",
        "False",
        "--use_guardrail" if use_guardrail else ""
    ])
    # 빈 문자열 제거
    cmd_single = [arg for arg in cmd_single if arg]

    results["arg_accuracy"] = run_single_benchmark(
        "Dialog — Argument Accuracy", cmd_single
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


def generate_markdown_report(results, model="gpt-4o-mini", trace_count=1, use_guardrail=False, elapsed_time=None):
    """평가 결과를 Markdown 보고서로 생성합니다."""
    global arg_accuracy_dataset
    # 경로 구조: output/arg_acc/{model_name}/...
    single_score_file = (
        BENCH_DIR
        / "output"
        / "arg_acc"
        / model
        / f"FunctionChat-{model}.eval_score.json"
    )
    eval_report_tsv = (
        BENCH_DIR
        / "output"
        / "arg_acc"
        / model
        / f"FunctionChat-Dialog.{model}.eval_report.tsv"
    )

    # 데이터셋 경로 및 카운트
    arg_acc_count = count_lines(arg_accuracy_dataset)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_name = f"eval_report_arg_acc_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = RESULTS_DIR / report_name

    # 실행 상태 요약
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    md_content = f"""# 🤖 챗봇 성능 평가 보고서 (Argument Accuracy)
- **생성 일시**: {timestamp}
- **평가 프레임워크**: FunctionChat-Bench
- **대상 모델**: {model}
- **LangSmith 트레이스 수**: {trace_count}개
- **가드레일 활성화**: {"✅ ON" if use_guardrail else "❌ OFF"}
- **소요 시간**: {f"{elapsed_time:.2f}초" if elapsed_time is not None else "측정 불가"}
- **실행 결과**: {passed}/{total} 벤치마크 성공
 
## 📖 평가 벤치마크 설명
본 평가는 **FunctionChat-Bench** 프레임워크를 기반으로 수행되었습니다.
 
### 1. Argument Accuracy (Dialog)
- **평가 목적**: 챗봇이 멀티턴 대화에서 필요한 인자(Argument)를 얼마나 정확하게 추출하고 올바른 Tool을 호출하는지 측정합니다.
- **핵심 지표**: 필수 인자 추출 정확도, Tool 선택 정확성, enum 값 범위 준수 여부를 검증합니다.
- **데이터셋**: `{arg_accuracy_dataset}` (총 {arg_acc_count}개 전체 평가)

"""

    # ── Argument Accuracy (Dialog) 결과 요약 ──
    if not results.get("arg_accuracy"):
        md_content += "## 📊 Argument Accuracy (Dialog)\n- ❌ 평가 실행에 실패했습니다.\n\n"
    elif single_score_file.exists():
        try:
            with open(single_score_file, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if data and "dialog_score" in data:
                sc = data.get("dialog_score", {})
                call_rate = sc.get("call pass rate", 0) * 100
                md_content += f"""## 📊 Argument Accuracy (Dialog) 요약
| 지표 | 결과 |
| :--- | :--- |
| **전체 테스트 케이스** | {sc.get("total_cnt", 0)}개 |
| **통과 수 (Pass)** | {sc.get("total_pass_cnt", 0)}개 |
| **Call 정답률** | {call_rate:.1f}% |
| **Micro 평균** | {sc.get("avg(micro)", 0) * 100:.1f}% |

"""
            else:
                md_content += "## 📊 Argument Accuracy (Dialog)\n- ❌ 결과 데이터 형식이 올바르지 않습니다.\n\n"
        except Exception as e:
            md_content += f"## 📊 Argument Accuracy (Dialog)\n- ❌ 결과 파일 로드 실패: {e}\n\n"
    else:
        md_content += "## 📊 Argument Accuracy (Dialog)\n- 결과 파일을 찾을 수 없습니다.\n\n"

    # ── 사용자 쿼리 목록 추출 ──
    query_summary = "## 💬 수신된 사용자 쿼리 목록\n| 번호 | 사용자 질의 (Query) |\n| :--- | :--- |\n"
    
    # ── 상세 실행 로그 (Tool Calls 포함) ──
    if eval_report_tsv.exists():
        md_content += "## 📝 상세 실행 로그 (Tool Calls)\n"
        md_content += "| 번호 | 결과 | 질의 | 기대되는 도구 (Expected) | 호출된 도구 (Model) | 분류 로직 |\n"
        md_content += "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
        
        try:
            with open(eval_report_tsv, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if len(lines) > 1:
                    header = lines[0].strip().split('\t')
                    # 헤더 인덱스 찾기
                    try:
                        idx_num = header.index("#serial_num")
                        idx_pass = header.index("is_pass")
                        idx_query = header.index("query")
                        idx_output = header.index("model_output")
                        idx_ground_truth = header.index("ground_truth")
                    except ValueError:
                        idx_num, idx_pass, idx_query, idx_output, idx_ground_truth = 0, 1, 7, 5, 3 # Fallback

                    for line in lines[1:]:
                        parts = line.strip().split('\t')
                        if len(parts) <= max(idx_num, idx_pass, idx_query, idx_output, idx_ground_truth):
                            continue
                        
                        num = parts[idx_num]
                        is_pass = "✅ PASS" if parts[idx_pass].lower() == "pass" else "❌ FAIL"
                        
                        # Query 추출 (마지막 유저 메시지)
                        try:
                            query_json = json.loads(parts[idx_query])
                            query_text = query_json[-1]["content"] if isinstance(query_json, list) else str(query_json)
                        except:
                            query_text = parts[idx_query][:30] + "..."
                        
                        # Expected (Ground Truth) 추출
                        exp_name = "-"
                        exp_args = "-"
                        try:
                            gt_json = json.loads(parts[idx_ground_truth])
                            gt_tcs = gt_json.get("tool_calls")
                            if gt_tcs and isinstance(gt_tcs, list) and len(gt_tcs) > 0:
                                tc = gt_tcs[0]
                                if "function" in tc:
                                    fn = tc["function"]
                                    exp_name = f"`{fn.get('name', '-')}`"
                                    exp_args = f"`{json.dumps(fn.get('arguments', {}), ensure_ascii=False)}`"
                        except:
                            pass

                        # Model Output 추출
                        tool_name = "-"
                        tool_args = "-"
                        cls_source = "Rule" # 기본값
                        try:
                            output_json = json.loads(parts[idx_output])
                            
                            # Case 1: OpenAI Response 스타일 (choices 포함)
                            choices = output_json.get("choices", [])
                            if choices and isinstance(choices, list):
                                msg = choices[0].get("message", {})
                            else:
                                # Case 2: 직계 메시지 객체 스타일 (evaluation_adapter가 직접 반환한 경우)
                                msg = output_json
                            
                            cls_source = msg.get("classification_source", "Rule")
                            tcs = msg.get("tool_calls")
                            if tcs and isinstance(tcs, list) and len(tcs) > 0:
                                tc = tcs[0]
                                if "function" in tc:
                                    fn = tc["function"]
                                    tool_name = f"`{fn.get('name', '-')}`"
                        except:
                            pass
                            
                        md_content += f"| {num} | {is_pass} | {query_text} | {exp_name} | {tool_name} | `{cls_source}` |\n"
                        query_summary += f"| {num} | {query_text} |\n"
            md_content += "\n"
            md_content += query_summary + "\n"
        except Exception as e:
            md_content += f"\n> 상세 로그 로드 중 오류 발생: {e}\n\n"

    md_content += """---
*본 보고서는 `run_evaluate.py`에 의해 자동으로 생성되었습니다.*
"""

    # 폴더 생성 및 저장
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"📖 보고서가 저장되었습니다: {report_path}")
    return report_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MOYEO Chatbot Evaluation Pipeline (In-house Only)")
    parser.add_argument("--mode", type=int, default=1, help="Evaluation mode (1, 2, 3, 4, 50)")
    parser.add_argument("--llm", "--internal_model", dest="internal_model", type=str, default="gpt-4o-mini", 
                        help="LLM model used inside the chatbot (e.g. gpt-4o-mini, qwen3/qwen3-0.6b)")
    parser.add_argument("--trace", type=int, default=0, help="LangSmith trace count (default: 0)")
    parser.add_argument("--reset", type=str, default="True", help="Reset previous results (True/False, default: True)")
    parser.add_argument("--guardrail", type=str, default="True", help="Use guardrail model (True/False, default: True)")
    
    args = parser.parse_args()
    
    # trace 인자값이 0이면 LangChain 추적을 완전히 끕니다.
    if args.trace <= 0:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        print("🚫 LangSmith Trace disabled (trace=0)")
    else:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        print(f"📡 LangSmith Trace enabled (tracing first {args.trace} samples)")

    reset_bool = args.reset.lower() == "true"
    guardrail_bool = args.guardrail.lower() == "true"

    # 항상 inhouse 모드로 실행되므로 실제 모델명은 internal_model이 됨
    actual_model_name = args.internal_model
    
    # 편의 기능: qwen만 입력하면 정식 모델명으로 변환
    if actual_model_name.lower() in ["qwen", "qwen3"]:
        actual_model_name = "qwen3:0.6b"
        args.internal_model = actual_model_name # 내부 호출 인자도 업데이트
    
    # 파일 시스템 안전을 위해 슬래시 및 콜론 치환 (윈도우 호환성)
    safe_model_name = actual_model_name.replace('/', '_').replace('\\', '_').replace(':', '_')

    dataset_name = f"my_eval_arg_accuracy_dialogs{str(args.mode) if args.mode > 1 else ''}.jsonl"
    print(f"📊 챗봇 내부 평가 시작: Mode={args.mode}, Dataset={dataset_name}, Target LLM={actual_model_name}, Reset={reset_bool}, TraceCount={args.trace}")

    # 모델 인자는 파일 경로용(safe_model_name), internal_model은 엔진 호출용(actual_model_name)으로 구분
    start_time = time.time()
    results = run_evaluation(args.mode, safe_model_name, args.trace, actual_model_name, reset_bool, guardrail_bool)
    end_time = time.time()
    elapsed_time = end_time - start_time

    if results:
        generate_markdown_report(results, safe_model_name, args.trace, guardrail_bool, elapsed_time)
