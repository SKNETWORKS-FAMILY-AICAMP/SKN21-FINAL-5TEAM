"""
Supervisor 라우팅 평가 데이터셋 생성기.

supervisor_eval_dataset_info.json의 템플릿을 기반으로
LLM 변형을 생성하여 supervisor_eval_dataset.jsonl로 저장합니다.

출력 JSONL 각 샘플:
  {"input": "...", "expected_node": "order_intent_router"}
"""

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# ── 경로 설정 ──────────────────────────────────────────────

BENCH_DIR = Path(__file__).resolve().parent
INFO_PATH = BENCH_DIR / "supervisor_eval_dataset_info.json"
OUTPUT_PATH = BENCH_DIR / "supervisor_eval_dataset.jsonl"


def _find_project_root(start: Path, marker: str = ".env") -> Path:
    """상위 디렉토리를 탐색하며 .env가 있는 프로젝트 루트를 반환."""
    for parent in [start] + list(start.parents):
        if (parent / marker).exists():
            return parent
    return start.parents[4]


# .env 로드
_PROJECT_ROOT = _find_project_root(BENCH_DIR)
load_dotenv(_PROJECT_ROOT / ".env")


# ── DB에서 이미지 URL 조회 (ORM) ──────────────────────────

sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy.sql.expression import func
from ecommerce.backend.app.database import SessionLocal
from ecommerce.backend.app.router.products.models import ProductImage  # noqa: E402

import ecommerce.backend.app.router.users.models  # noqa: F401
import ecommerce.backend.app.router.carts.models  # noqa: F401
import ecommerce.backend.app.router.orders.models  # noqa: F401
import ecommerce.backend.app.router.shipping.models  # noqa: F401
import ecommerce.backend.app.router.points.models  # noqa: F401
import ecommerce.backend.app.router.reviews.models  # noqa: F401
import ecommerce.backend.app.router.user_history.models  # noqa: F401
import ecommerce.backend.app.router.payments.models  # noqa: F401


def fetch_image_urls(limit: int = 50) -> list[str]:
    """productimages 테이블에서 image_url 목록을 ORM으로 조회."""
    db = SessionLocal()
    try:
        rows = (
            db.query(ProductImage.image_url)
            .order_by(func.rand())
            .limit(limit)
            .all()
        )
        return [row[0] for row in rows]
    except Exception as e:
        print(f"[경고] DB에서 이미지 URL 조회 실패: {e}")
        return []
    finally:
        db.close()


def fill_image_url(template: str, image_urls: list[str]) -> str:
    """템플릿의 {image_url} 플레이스홀더를 실제 이미지 URL로 치환."""
    if "{image_url}" in template and image_urls:
        return template.replace("{image_url}", random.choice(image_urls))
    return template


# ── LLM 변형 생성 ─────────────────────────────────────────


def _parse_llm_list(content: str, count: int) -> list[str]:
    """LLM JSON 응답을 파싱하여 문자열 리스트 반환."""
    parsed = json.loads(content)
    if isinstance(parsed, list):
        return parsed[:count]
    if isinstance(parsed, dict):
        for val in parsed.values():
            if isinstance(val, list):
                return val[:count]
    return []


def generate_variations(
    client: OpenAI,
    template: str,
    description: str,
    count: int,
    model: str,
    temperature: float,
) -> list[str]:
    """단일 라우팅 대상 템플릿의 LLM 변형 생성."""
    prompt = f"""다음은 '{description}' 라우팅 대상의 사용자 발화 예시입니다:
"{template}"

이 문장과 같은 의도를 가진 자연스러운 한국어 변형 문장을 {count}개 생성해주세요.

규칙:
- 원본과 같은 의도를 유지해야 합니다.
- 존댓말, 반말, 구어체 등 다양한 말투를 섞어주세요.
- URL이 포함된 문장이면 URL도 다른 예시 URL로 변형해주세요.
- JSON 배열 형식으로만 응답하세요.

예시 출력: ["변형1", "변형2", "변형3"]"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return _parse_llm_list(response.choices[0].message.content, count)
    except Exception as e:
        print(f"  [경고] 변형 생성 실패 ({template[:30]}...): {e}")
        return []


# ── 메인 데이터셋 생성 ─────────────────────────────────────


def build_dataset(
    info_path: Path = INFO_PATH,
    output_path: Path = OUTPUT_PATH,
    variations_override: int | None = None,
    model_override: str | None = None,
) -> int:
    """supervisor_eval_dataset_info.json → supervisor_eval_dataset.jsonl 생성."""
    with open(info_path, encoding="utf-8") as f:
        info = json.load(f)

    config = info["generation_config"]
    variations_count = variations_override or config["variations_per_template"]
    llm_model = model_override or config["llm_model"]
    temperature = config["temperature"]

    client = OpenAI()
    samples: list[dict] = []

    # DB에서 이미지 URL 조회
    image_urls = fetch_image_urls()
    if image_urls:
        print(f"DB에서 이미지 URL {len(image_urls)}개 조회 완료")
    else:
        print("[경고] DB에서 이미지 URL을 가져오지 못했습니다.")

    # 1) 단일 라우팅 대상 데이터셋
    print("=== Supervisor 라우팅 평가 데이터셋 생성 ===")
    for node_name, node_data in info["routing_targets"].items():
        if "sub_routes" in node_data:
            for sub_route, sub_data in node_data["sub_routes"].items():
                description = sub_data["description"]
                templates = sub_data["templates"]
                print(f"\n[{node_name} → {sub_route}] 템플릿 {len(templates)}개 처리 중...")

                for raw_template in templates:
                    template = fill_image_url(raw_template, image_urls)

                    samples.append({
                        "input": template,
                        "expected_node": node_name,
                    })

                    variations = generate_variations(
                        client, template, description,
                        variations_count, llm_model, temperature,
                    )
                    for var in variations:
                        if isinstance(var, str) and var.strip():
                            samples.append({
                                "input": var.strip(),
                                "expected_node": node_name,
                            })

                print(f"  -> {node_name}/{sub_route}: 현재 총 {len(samples)}개")
        else:
            description = node_data["description"]
            templates = node_data["templates"]
            print(f"\n[{node_name}] 템플릿 {len(templates)}개 처리 중...")

            for raw_template in templates:
                template = fill_image_url(raw_template, image_urls)

                samples.append({
                    "input": template,
                    "expected_node": node_name,
                })

                variations = generate_variations(
                    client, template, description,
                    variations_count, llm_model, temperature,
                )
                for var in variations:
                    if isinstance(var, str) and var.strip():
                        samples.append({
                            "input": var.strip(),
                            "expected_node": node_name,
                        })

            print(f"  -> {node_name}: 현재 총 {len(samples)}개")

    # 2) JSONL 저장
    with open(output_path, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    # 통계 출력
    print(f"\n=== 완료: {len(samples)}개 샘플 → {output_path} ===")

    node_dist: Counter = Counter()
    for s in samples:
        node_dist[s["expected_node"]] += 1
    print("\n  [라우팅 노드 분포]")
    for node, count in sorted(node_dist.items()):
        print(f"    {node}: {count}")

    return len(samples)


# ── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Supervisor 라우팅 평가 데이터셋 생성")
    parser.add_argument(
        "--variations", type=int, default=None,
        help="템플릿당 변형 수 (기본: info JSON의 설정값)",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="변형 생성에 사용할 LLM 모델 (기본: info JSON의 설정값)",
    )
    parser.add_argument(
        "--info", type=str, default=None,
        help="supervisor_eval_dataset_info.json 경로",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="출력 JSONL 경로",
    )
    args = parser.parse_args()

    info_path = Path(args.info) if args.info else INFO_PATH
    output_path = Path(args.output) if args.output else OUTPUT_PATH

    if not info_path.exists():
        print(f"[오류] {info_path} 파일을 찾을 수 없습니다.")
        sys.exit(1)

    build_dataset(
        info_path=info_path,
        output_path=output_path,
        variations_override=args.variations,
        model_override=args.model,
    )


if __name__ == "__main__":
    main()
