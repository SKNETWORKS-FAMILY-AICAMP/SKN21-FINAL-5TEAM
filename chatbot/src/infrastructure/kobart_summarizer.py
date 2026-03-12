"""
KoBART 로컬 요약 모델 싱글톤.

모델: EbanLee/kobart-summary-v3
  - 한국어 뉴스/대화 seq2seq 요약 모델 (123M 파라미터)
  - 입력 최대 1026 토큰 (안전하게 900자로 제한)
  - MPS(Apple Silicon) / CUDA / CPU 자동 선택

싱글톤 패턴:
  - 서버 프로세스 내 최초 호출 시 1회만 로드 (~2초, 캐시 히트 기준)
  - 이후 호출은 메모리에서 즉시 재사용
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── 싱글톤 상태 ────────────────────────────────────────────
_lock = threading.Lock()
_tokenizer: Any = None
_model: Any = None
_device: str = "cpu"

# KoBART 입력 최대 길이 (토큰 초과 방지용 문자 수 제한)
_MAX_INPUT_CHARS = 900


def _get_device() -> str:
    """가속기 우선순위: MPS > CUDA > CPU"""
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _load_model() -> None:
    """kobart 모델을 로컬 캐시(~/.cache/huggingface)에서 로드."""
    global _tokenizer, _model, _device

    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

    model_id = "EbanLee/kobart-summary-v3"
    logger.info("[KoBART] 모델 로드 시작: %s", model_id)

    _tokenizer = AutoTokenizer.from_pretrained(model_id)
    _model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
    _device = _get_device()
    _model = _model.to(_device)
    _model.eval()

    logger.info("[KoBART] 모델 로드 완료 (device=%s, params=%s)", _device,
                f"{sum(p.numel() for p in _model.parameters()):,}")


def _ensure_loaded() -> None:
    """스레드 안전한 지연 초기화."""
    global _tokenizer, _model
    if _model is None:
        with _lock:
            if _model is None:
                _load_model()


def preload_model() -> None:
    """서버 시작 시 KoBART 모델을 싱글톤으로 미리 로드합니다."""
    _ensure_loaded()


def summarize_conversation(text: str) -> Optional[str]:
    """
    대화 텍스트를 kobart로 요약합니다.

    Args:
        text: 요약할 대화 텍스트 (사용자/상담원 발화 포함)

    Returns:
        요약 문자열. 빈 입력이거나 오류 시 None.
    """
    if not text or not text.strip():
        return None

    try:
        _ensure_loaded()

        import torch

        # 입력 길이 제한 (토큰 초과 방지)
        truncated = text.strip()[:_MAX_INPUT_CHARS]

        inputs = _tokenizer(
            truncated,
            return_tensors="pt",
            max_length=1024,
            truncation=True,
        ).to(_device)

        with torch.no_grad():
            output_ids = _model.generate(
                **inputs,
                max_new_tokens=128,
                num_beams=4,
                early_stopping=True,
                no_repeat_ngram_size=3,
            )

        summary = _tokenizer.decode(output_ids[0], skip_special_tokens=True).strip()
        logger.debug("[KoBART] 요약 완료: %d자 → %d자", len(truncated), len(summary))
        return summary if summary else None

    except Exception as e:
        logger.warning("[KoBART] 요약 실패 (무시하고 계속): %s", e)
        return None
