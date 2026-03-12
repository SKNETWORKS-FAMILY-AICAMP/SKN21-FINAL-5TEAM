"""
agent.py

이커머스 챗봇 에이전트 래퍼 모듈.
OpenAI tool-calling 방식으로 챗봇 에이전트를 실행하고, 도구 호출 결과를 환경에 반영합니다.
"""

import json
from openai import OpenAI
from pathlib import Path
from .environment import TaskEnvironment

TOOLS_PATH = Path(__file__).resolve().parent.parent / "data" / "tools.json"
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "FunctionChat-Bench" / "data" / "system_prompt.txt"


def _load_tools() -> list[dict]:
    """tools.json에서 도구 정의를 로드합니다."""
    with open(TOOLS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_system_prompt() -> str:
    """챗봇 시스템 프롬프트를 로드합니다."""
    if SYSTEM_PROMPT_PATH.exists():
        with open(SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
            return f.read().strip()
    return "당신은 이커머스 쇼핑몰의 친절한 AI 어시스턴트입니다."


class ChatbotAgent:
    """
    이커머스 챗봇 에이전트.
    OpenAI tool-calling API를 사용하여 사용자 발화에 응답하고 도구를 호출합니다.
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", temperature: float = 0.0):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.tools = _load_tools()
        self.system_prompt = _load_system_prompt()
        self.history: list[dict] = []

    def reset(self) -> None:
        """에이전트 대화 이력을 초기화합니다."""
        self.history = []

    def respond(self, user_message: str, env: TaskEnvironment) -> str:
        """
        사용자 메시지에 대한 챗봇 응답을 생성합니다.
        도구 호출이 필요한 경우 환경에 적용하고 결과를 반영합니다.

        Parameters:
            user_message: 사용자 발화
            env: 현재 태스크 환경

        Returns:
            챗봇의 최종 텍스트 응답
        """
        self.history.append({"role": "user", "content": user_message})

        messages = [{"role": "system", "content": self.system_prompt}] + self.history

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=self.tools,
            tool_choice="auto",
            temperature=self.temperature,
        )

        assistant_msg = response.choices[0].message

        # 도구 호출 처리 (최대 5회 연속 호출 허용)
        max_tool_rounds = 5
        for _ in range(max_tool_rounds):
            if not assistant_msg.tool_calls:
                break

            # tool_calls 메시지를 이력에 추가
            self.history.append({
                "role": "assistant",
                "content": assistant_msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in assistant_msg.tool_calls
                ]
            })

            # 각 도구 호출을 환경에 적용
            for tool_call in assistant_msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                tool_result = env.apply_tool_call(tool_name, tool_args)

                self.history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": json.dumps(tool_result, ensure_ascii=False)
                })

            # 도구 결과를 반영하여 재응답
            messages = [{"role": "system", "content": self.system_prompt}] + self.history
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
                temperature=self.temperature,
            )
            assistant_msg = response.choices[0].message

        # 최종 텍스트 응답 저장
        final_content = assistant_msg.content or ""
        self.history.append({"role": "assistant", "content": final_content})
        return final_content

    def get_trajectory(self) -> list[dict]:
        """현재 대화 이력(trajectory)을 반환합니다."""
        return list(self.history)
