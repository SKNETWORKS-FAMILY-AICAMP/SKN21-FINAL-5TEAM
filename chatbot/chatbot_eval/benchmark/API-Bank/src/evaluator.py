"""
evaluator.py

다이얼로그 데이터셋에 대해 대상 모델을 평가합니다.

턴 타입별 평가 방법:
  - "slot"       : LLM Judge (역질문 적절성 평가)
  - "call"       : Exact Match → 실패 시 LLM Judge
  - "completion" : LLM Judge (툴 결과 전달 적절성 평가)

다이얼로그 pass 조건: 모든 턴이 pass 인 경우
"""

import os
import json
import logging
from typing import List, Dict, Optional

from tqdm import tqdm
from openai import OpenAI

from src.paths import BENCH_ROOT, DATA_DIR, CONFIG_PATH, ENV_PATH


RUBRIC_FILES = {
    "slot": DATA_DIR / "rubric_slot.txt",
    "call": DATA_DIR / "rubric_call.txt",
    "completion": DATA_DIR / "rubric_completion.txt",
}


class DialogEvaluator:
    """다이얼로그 단위로 모델 응답을 평가합니다."""

    def __init__(
        self,
        target_model: str,
        judge_api_key: str,
        output_dir: str,
        only_exact: bool = False,
        debug: bool = False,
    ):
        self.target_model = target_model
        self.output_dir = output_dir
        self.only_exact = only_exact
        self.debug = debug

        self.rubrics = self._load_rubrics()

        # LLM Judge 설정 (openai.cfg 우선)
        judge_model = "gpt-4o-mini"
        resolved_key = judge_api_key
        if CONFIG_PATH.exists():
            try:
                cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                cfg_model = cfg.get("api_version", "")
                cfg_key = cfg.get("api_key", "")
                if cfg_model:
                    judge_model = cfg_model
                if cfg_key and "placeholder" not in cfg_key and "YOUR_OPENAI_KEY" not in cfg_key:
                    resolved_key = cfg_key
            except Exception:
                pass

        self.judge_model = judge_model
        self.judge_client = OpenAI(api_key=resolved_key)

    # ── 루브릭 로드 ─────────────────────────────────────────────────────────

    def _load_rubrics(self) -> Dict[str, Optional[str]]:
        rubrics: Dict[str, Optional[str]] = {}
        for turn_type, path in RUBRIC_FILES.items():
            if path.exists():
                rubrics[turn_type] = path.read_text(encoding="utf-8").strip()
            else:
                rubrics[turn_type] = None
                logging.warning(f"루브릭 파일 없음: {path}")
        return rubrics

    # ── Exact Match ─────────────────────────────────────────────────────────

    def _exact_match_call(self, ground_truth: Dict, prediction: Dict) -> bool:
        """
        "call" 타입 턴의 exact match 를 수행합니다.

        데이터셋 ground_truth 포맷:
          {"role": "assistant", "content": None,
           "tool_calls": [{"name": "...", "arguments": "{ ... }"}]}
        """
        gt_tools = ground_truth.get("tool_calls") or []
        pred_tools = prediction.get("tool_calls") or []

        # ground_truth 가 no_tool_call 인 경우
        if not gt_tools:
            return not pred_tools

        if not pred_tools:
            return False

        gt_tc = gt_tools[0]
        pred_tc = pred_tools[0]

        # 함수명 비교
        if gt_tc.get("name") != pred_tc.get("name"):
            return False

        # 인자 파싱
        try:
            gt_args = json.loads(gt_tc.get("arguments", "{}")) if isinstance(gt_tc.get("arguments"), str) else (gt_tc.get("arguments") or {})
            pred_args = json.loads(pred_tc.get("arguments", "{}")) if isinstance(pred_tc.get("arguments"), str) else (pred_tc.get("arguments") or {})
        except json.JSONDecodeError:
            return False

        # 예측에 ground_truth 에 없는 key 가 있으면 실패 (hallucination)
        for key in pred_args:
            if key not in gt_args:
                return False

        # ground_truth 의 모든 key 가 예측에도 있어야 함
        for key, val in gt_args.items():
            pred_val = pred_args.get(key)
            if isinstance(val, str) and isinstance(pred_val, str):
                if val.replace(" ", "").lower() != pred_val.replace(" ", "").lower():
                    return False
            elif val != pred_val:
                return False

        return True

    # ── LLM Judge ───────────────────────────────────────────────────────────

    def _llm_judge(
        self,
        turn_type: str,
        tools: List[Dict],
        query: List[Dict],
        ground_truth: Dict,
        prediction: Dict,
    ) -> bool:
        """LLM Judge 를 사용해 응답을 평가합니다."""
        rubric = self.rubrics.get(turn_type)
        if not rubric:
            logging.warning(f"루브릭 없음: {turn_type}, fail 처리")
            return False

        tools_json = json.dumps(tools, ensure_ascii=False)
        query_json = json.dumps(query, ensure_ascii=False)
        gt_json = json.dumps(ground_truth, ensure_ascii=False)
        pred_json = json.dumps(prediction, ensure_ascii=False)

        if turn_type == "call":
            prompt = rubric.format(
                tools=tools_json,
                query=query_json,
                ground_truth=gt_json,
                acceptable_arguments=json.dumps({}, ensure_ascii=False),
                response=pred_json,
            )
        else:
            prompt = rubric.format(
                tools=tools_json,
                query=query_json,
                ground_truth=gt_json,
                response=pred_json,
            )

        try:
            response = self.judge_client.chat.completions.create(
                model=self.judge_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            content = response.choices[0].message.content.strip()
            # 마지막 줄에서 pass/fail 판정
            last_line = content.splitlines()[-1].lower().strip().rstrip(".")
            return last_line == "pass"
        except Exception as e:
            logging.error(f"LLM Judge 호출 실패: {e}")
            return False

    # ── 단일 턴 평가 ─────────────────────────────────────────────────────────

    def evaluate_turn(self, turn: Dict, tools: List[Dict], caller,
                       prompt_variables: Optional[Dict[str, str]] = None) -> Dict:
        """단일 턴을 평가하고 결과를 반환합니다.

        Args:
            prompt_variables: dialog별 user_id, user_email 등 시스템 프롬프트 치환 변수
        """
        query = turn["query"]
        ground_truth = turn["ground_truth"]
        turn_type = turn["type_of_output"]

        # 모델 호출 (user row별 prompt_variables 전달)
        try:
            prediction = caller.call(query, tools, prompt_variables=prompt_variables)
        except Exception as e:
            logging.error(f"모델 호출 실패 (turn {turn['turn_num']}): {e}")
            prediction = {"role": "assistant", "content": None}

        # Exact Match (call 타입만)
        exact_pass = False
        if turn_type == "call":
            exact_pass = self._exact_match_call(ground_truth, prediction)

        # LLM Judge
        llm_pass = exact_pass
        if not self.only_exact and not exact_pass:
            llm_pass = self._llm_judge(turn_type, tools, query, ground_truth, prediction)

        result = {
            "serial_num": turn["serial_num"],
            "turn_num": turn["turn_num"],
            "type_of_output": turn_type,
            "query": query,
            "ground_truth": ground_truth,
            "prediction": prediction,
            "exact_pass": exact_pass,
            "pass": llm_pass,
        }

        if self.debug:
            status = "✅" if llm_pass else "❌"
            print(
                f"    {status} Turn {turn['turn_num']} [{turn_type}]"
                + (f" (exact)" if exact_pass else "")
            )

        return result

    # ── 전체 다이얼로그 평가 ──────────────────────────────────────────────────

    def evaluate_dialogs(
        self,
        dialogs: List[Dict],
        caller,
        reset: bool = False,
    ) -> List[Dict]:
        """모든 다이얼로그를 평가하고 결과를 반환합니다."""
        os.makedirs(self.output_dir, exist_ok=True)
        output_path = os.path.join(
            self.output_dir, f"api_bank_{self.target_model}.eval.jsonl"
        )

        # 캐시 확인
        if not reset and os.path.exists(output_path):
            cached: List[Dict] = []
            with open(output_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        cached.append(json.loads(line))
            if len(cached) == len(dialogs):
                print(f"[[캐시된 결과 로드]] {len(cached)}개 다이얼로그 (reset=False)")
                return cached
            print(f"[[캐시 불완전 ({len(cached)}/{len(dialogs)}), 재평가 시작]]")

        all_results: List[Dict] = []
        with open(output_path, "w", encoding="utf-8") as fw:
            for dialog in tqdm(dialogs, desc="다이얼로그 평가"):
                # user row별 정보 추출 (generate 스크립트에서 설정한 user_id, user_email)
                user_id = dialog.get("user_id")
                user_email = dialog.get("user_email")
                prompt_variables: Optional[Dict[str, str]] = {}
                if user_id is not None:
                    prompt_variables["user_id"] = str(user_id)
                if user_email:
                    prompt_variables["user_email"] = user_email
                if not prompt_variables:
                    prompt_variables = None

                if self.debug:
                    print(f"\n▶ Dialog {dialog['dialog_num']}: {dialog.get('dialog_name', '')}"
                          f" (user_id={user_id}, user_email={user_email})")

                tools = dialog["tools"]
                turn_results = [
                    self.evaluate_turn(turn, tools, caller, prompt_variables=prompt_variables)
                    for turn in dialog["turns"]
                ]
                dialog_pass = all(t["pass"] for t in turn_results)

                dialog_result = {
                    "dialog_num": dialog["dialog_num"],
                    "dialog_name": dialog.get("dialog_name", ""),
                    "user_id": user_id,
                    "user_email": user_email,
                    "turns": turn_results,
                    "dialog_pass": dialog_pass,
                }
                all_results.append(dialog_result)
                fw.write(json.dumps(dialog_result, ensure_ascii=False) + "\n")

        return all_results
