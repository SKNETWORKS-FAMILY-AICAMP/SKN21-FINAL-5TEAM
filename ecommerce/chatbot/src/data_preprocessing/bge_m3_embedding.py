from typing import List

import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

MODEL_NAME = "BAAI/bge-m3"

_TOKENIZER = None
_MODEL = None
_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def _load_model():
    global _TOKENIZER, _MODEL
    if _TOKENIZER is not None and _MODEL is not None:
        return _TOKENIZER, _MODEL

    _TOKENIZER = AutoTokenizer.from_pretrained(MODEL_NAME)
    _MODEL = AutoModel.from_pretrained(MODEL_NAME)
    _MODEL.to(_DEVICE)
    _MODEL.eval()
    return _TOKENIZER, _MODEL


def preload_model() -> None:
    """서버 시작 시 BGE-M3 모델을 싱글톤으로 미리 로드합니다."""
    _load_model()


def get_embedding_dim() -> int:
    _, model = _load_model()
    return int(model.config.hidden_size)


def embed_texts(texts: List[str], batch_size: int = 32) -> List[List[float]]:
    tokenizer, model = _load_model()
    vectors: List[List[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=8192,
            return_tensors="pt",
        )
        encoded = {k: v.to(_DEVICE) for k, v in encoded.items()}

        with torch.no_grad():
            outputs = model(**encoded)
            token_embeddings = outputs.last_hidden_state
            attention_mask = encoded["attention_mask"].unsqueeze(-1)

            pooled = (token_embeddings * attention_mask).sum(dim=1) / attention_mask.sum(
                dim=1
            ).clamp(min=1e-9)
            pooled = F.normalize(pooled, p=2, dim=1)

        vectors.extend(pooled.cpu().tolist())

    return vectors
