"""
user_simulator.py

LLM 기반 사용자 시뮬레이터 모듈.
주어진 태스크 지시사항에 따라 챗봇과 대화를 수행하는 가상 사용자를 구현합니다.
"""

import json
from pathlib import Path
from openai import OpenAI

TASK_DONE_TOKEN = "TASK_DONE"
TASK_FAILED_TOKEN = "TASK_FAILED"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SIMULATOR_PROMPT_PATH = DATA_DIR / "user_simulator_prompt.txt"


class UserSimulator:
    """
    LLM 기반 사용자 시뮬레이터.
    tau-bench 방식으로 실제 사용자 역할을 수행하며 챗봇과 대화합니다.
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", temperature: float = 0.7):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.system_prompt_template = self._load_prompt_template()
        self.history: list[dict] = []
        self.task: dict = {}
        self.turn_count: int = 0
        self.is_done: bool = False
        self.is_failed: bool = False

    def _load_prompt_template(self) -> str:
        """유저 시뮬레이터 시스템 프롬프트 템플릿을 로드합니다."""
        with open(SIMULATOR_PROMPT_PATH, encoding="utf-8") as f:
            return f.read()

    def reset(self, task: dict) -> None:
        """새 태스크로 시뮬레이터를 초기화합니다."""
        self.task = task
        self.history = []
        self.turn_count = 0
        self.is_done = False
        self.is_failed = False

    def _build_system_prompt(self) -> str:
        """현재 태스크 기반 시스템 프롬프트를 생성합니다."""
        return self.system_prompt_template.format(
            task_instruction=self.task.get("instruction", ""),
            initial_db_state=json.dumps(
                self.task.get("initial_db_state", {}), ensure_ascii=False, indent=2
            )
        )

    def respond(self, chatbot_message: str) -> str:
        """
        챗봇 메시지에 대한 사용자 응답을 생성합니다.

        Parameters:
            chatbot_message: 챗봇의 마지막 발화

        Returns:
            사용자 시뮬레이터의 응답 문자열
        """
        self.turn_count += 1
        self.history.append({"role": "assistant", "content": chatbot_message})

        messages = [
            {"role": "system", "content": self._build_system_prompt()}
        ] + self.history

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=512
        )

        user_reply = response.choices[0].message.content.strip()
        self.history.append({"role": "user", "content": user_reply})

        if TASK_DONE_TOKEN in user_reply:
            self.is_done = True
        if TASK_FAILED_TOKEN in user_reply:
            self.is_failed = True

        return user_reply

    def get_initial_message(self) -> str:
        """태스크를 시작하는 첫 번째 사용자 발화를 생성합니다."""
        self.turn_count += 1

        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {
                "role": "user",
                "content": (
                    "대화를 시작하세요. 태스크 지시사항에 따라 첫 번째 발화를 생성하세요. "
                    "처음 발화는 짧고 자연스럽게 시작하세요."
                )
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=256
        )

        first_utterance = response.choices[0].message.content.strip()
        self.history.append({"role": "user", "content": first_utterance})
        return first_utterance
