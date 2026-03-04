"""
model_caller.py

OpenAI 호환 API를 통해 대상 모델(챗봇)을 호출합니다.
각 턴의 query + tools 를 받아 모델 응답을 반환합니다.
"""

import os
import json
import logging
from typing import List, Dict, Optional

from openai import OpenAI


class ModelCaller:
    """OpenAI 호환 API를 통해 챗봇 모델을 호출합니다."""

    def __init__(
        self,
        model: str,
        api_key: str,
        temperature: float = 0.0,
        base_url: Optional[str] = None,
        system_prompt_path: Optional[str] = None,
    ):
        self.model = model
        self.temperature = temperature
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url if base_url else None,
        )
        self.system_prompt = self._load_system_prompt(system_prompt_path)

    def _load_system_prompt(self, path: Optional[str]) -> str:
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        return ""

    def call(self, query: List[Dict], tools: List[Dict]) -> Dict:
        """
        모델을 호출하고 응답을 데이터셋 ground_truth 포맷으로 반환합니다.

        반환 포맷:
          - 텍스트 응답: {"role": "assistant", "content": "..."}
          - 툴 호출:     {"role": "assistant", "content": None,
                          "tool_calls": [{"name": "...", "arguments": "..."}]}
        """
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(query)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=self.temperature,
            )
        except Exception as e:
            logging.error(f"모델 API 호출 실패: {e}")
            raise

        choice = response.choices[0]
        message = choice.message
        result: Dict = {"role": "assistant", "content": message.content}

        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,  # JSON 문자열
                }
                for tc in message.tool_calls
            ]

        return result
