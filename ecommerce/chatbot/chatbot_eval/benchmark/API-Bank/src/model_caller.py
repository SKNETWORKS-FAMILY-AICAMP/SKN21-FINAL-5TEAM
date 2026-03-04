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

    def _normalize_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        데이터셋 포맷의 messages를 OpenAI API 포맷으로 변환합니다.

        데이터셋 tool_calls: [{"name": ..., "arguments": ...}]
        OpenAI API 요구:    [{"id": ..., "type": "function", "function": {"name": ..., "arguments": ...}}]
        """
        normalized = []
        tool_call_id_map: Dict[str, str] = {}

        for i, msg in enumerate(messages):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                new_tool_calls = []
                for j, tc in enumerate(msg["tool_calls"]):
                    tc_id = f"call_{i}_{j}"
                    tool_call_id_map[tc.get("name", "")] = tc_id
                    new_tool_calls.append({
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    })
                normalized.append({
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": new_tool_calls,
                })
            elif msg.get("role") == "tool":
                tool_name = msg.get("name", "")
                tc_id = tool_call_id_map.get(tool_name, f"call_{tool_name}")
                normalized.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": msg.get("content", ""),
                })
            else:
                normalized.append(msg)

        return normalized

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
        messages = self._normalize_messages(messages)

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
