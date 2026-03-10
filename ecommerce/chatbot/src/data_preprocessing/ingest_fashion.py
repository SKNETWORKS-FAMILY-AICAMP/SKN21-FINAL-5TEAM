"""Deprecated script.

기존 `fashion_products`(BGE-M3 hybrid) 적재는 사용 중지되었습니다.
현재는 `ingest_clip_images.py`를 사용해 `fashion_clip_images` 컬렉션을 구축합니다.
"""


def ingest_fashion() -> None:
    raise RuntimeError(
        "ingest_fashion.py is deprecated. Use ingest_clip_images.py instead."
    )


if __name__ == "__main__":
    ingest_fashion()
