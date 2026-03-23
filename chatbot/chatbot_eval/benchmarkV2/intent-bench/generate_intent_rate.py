"""
Supervisor 라우팅 평가 데이터셋 생성기.

supervisor_eval_dataset_info.json의 템플릿을 기반으로
LLM 변형을 생성하여 supervisor_eval_dataset.jsonl로 저장합니다.

출력 JSONL 각 샘플:
  {"input": "...", "expected_node": "order_intent_router", "difficulty": "easy"}
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


def _extract_string_list(parsed, count: int) -> list[str]:
    """LLM JSON 응답에서 문자열 리스트를 추출."""
    # {"variations": ["a", "b", ...]} — dict 안에 list value
    if isinstance(parsed, dict):
        for val in parsed.values():
            if isinstance(val, list):
                strings = [s.strip() for s in val if isinstance(s, str) and s.strip()]
                if strings:
                    return strings[:count]
        # {"1": "a", "2": "b", ...} — flat dict with string values
        strings = [v.strip() for v in parsed.values() if isinstance(v, str) and v.strip()]
        if strings:
            return strings[:count]
    # ["a", "b", ...] — raw list
    if isinstance(parsed, list):
        strings = [s.strip() for s in parsed if isinstance(s, str) and s.strip()]
        if strings:
            return strings[:count]
    return []


def generate_variations(
    client: OpenAI,
    templates: list[str],
    description: str,
    count: int,
    model: str,
    temperature: float,
    max_retries: int = 3,
) -> list[str]:
    """템플릿 리스트를 한 번에 전달하고 count개의 변형을 생성. 실패 시 원본 반환."""
    templates_text = "\n".join(f'{i + 1}. "{t}"' for i, t in enumerate(templates))

    prompt = f"""다음은 '{description}' 의도를 가진 사용자 발화 예시 {len(templates)}개입니다:

{templates_text}

위 예시들과 같은 의도를 유지하면서 자연스러운 한국어 변형 문장을 {count}개 생성해주세요.

규칙:
- 원본과 같은 의도를 유지해야 합니다.
- 존댓말, 반말, 구어체 등 다양한 말투를 섞어주세요.
- URL이 포함된 문장이면 URL도 유지해주세요.
- 반드시 아래 JSON 형식으로만 응답하세요.

출력 형식: {{"variations": ["문장1", "문장2", ..., "문장{count}"]}}"""

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                print(f"    [경고] 빈 응답 (시도 {attempt + 1}/{max_retries})")
                continue

            parsed = json.loads(content)
            results = _extract_string_list(parsed, count)
            if len(results) >= count:
                return results[:count]

            print(f"    [경고] {count}개 요청했으나 {len(results)}개만 파싱됨 (시도 {attempt + 1}/{max_retries}): {content[:100]}")
        except Exception as e:
            print(f"    [경고] 변형 생성 실패 (시도 {attempt + 1}/{max_retries}): {e}")

    print(f"    [폴백] 원본 템플릿 사용")
    return templates[:count]


# ── 메인 데이터셋 생성 ─────────────────────────────────────


def _collect_template_groups(
    info: dict, image_urls: list[str],
) -> list[dict]:
    """supervisor_eval_dataset_info.json에서 모든 템플릿 그룹을 수집.

    Returns:
        [{"node_name", "label", "description", "difficulty", "templates"}]
    """
    groups = []
    for node_name, node_data in info["routing_targets"].items():
        if "sub_routes" in node_data:
            for sub_route, sub_data in node_data["sub_routes"].items():
                desc = sub_data["description"]
                templates = sub_data.get("templates", {})
                for difficulty in ("easy", "hard"):
                    raw_list = templates.get(difficulty, [])
                    filled = [fill_image_url(t, image_urls) for t in raw_list]
                    if filled:
                        groups.append({
                            "node_name": node_name,
                            "label": f"{node_name} → {sub_route}",
                            "description": desc,
                            "difficulty": difficulty,
                            "templates": filled,
                        })
        else:
            desc = node_data["description"]
            templates = node_data.get("templates", {})
            for difficulty in ("easy", "hard"):
                raw_list = templates.get(difficulty, [])
                filled = [fill_image_url(t, image_urls) for t in raw_list]
                if filled:
                    groups.append({
                        "node_name": node_name,
                        "label": node_name,
                        "description": desc,
                        "difficulty": difficulty,
                        "templates": filled,
                    })
    return groups


def build_dataset(
    info_path: Path = INFO_PATH,
    output_path: Path = OUTPUT_PATH,
    model_override: str | None = None,
) -> int:
    """supervisor_eval_dataset_info.json → supervisor_eval_dataset.jsonl 생성.

    각 세부사항의 난이도별 템플릿 10개를 한 번에 LLM에 전달하여
    변형 10개를 받아옵니다. (14그룹 × 10개 = 총 140개)
    """
    with open(info_path, encoding="utf-8") as f:
        info = json.load(f)

    config = info["generation_config"]
    variations_count = config["variations_per_template"]
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

    # 템플릿 그룹 수집
    groups = _collect_template_groups(info, image_urls)
    total_templates = sum(len(g["templates"]) for g in groups)

    print("=== Supervisor 라우팅 평가 데이터셋 생성 ===")
    print(f"총 {len(groups)}개 그룹, {total_templates}개 템플릿\n")

    for group in groups:
        node_name = group["node_name"]
        label = group["label"]
        difficulty = group["difficulty"]
        description = group["description"]
        templates = group["templates"]

        print(f"[{label}] {difficulty} 템플릿 {len(templates)}개 → 변형 {variations_count}개 생성 중...")

        variations = generate_variations(
            client, templates, description,
            variations_count, llm_model, temperature,
        )

        for var in variations:
            samples.append({
                "input": var,
                "expected_node": node_name,
                "difficulty": difficulty,
            })

        print(f"  -> 완료 ({len(variations)}개 생성)\n")

    # JSONL 저장
    with open(output_path, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    # 통계 출력
    print(f"\n=== 완료: {len(samples)}개 샘플 → {output_path} ===")

    node_dist: Counter = Counter()
    diff_dist: Counter = Counter()
    node_diff_dist: Counter = Counter()
    for s in samples:
        node_dist[s["expected_node"]] += 1
        diff_dist[s["difficulty"]] += 1
        node_diff_dist[f"{s['expected_node']}_{s['difficulty']}"] += 1

    print("\n  [라우팅 노드 분포]")
    for node, count in sorted(node_dist.items()):
        print(f"    {node}: {count}")
    print("\n  [난이도 분포]")
    for diff, count in sorted(diff_dist.items()):
        print(f"    {diff}: {count}")
    print("\n  [노드×난이도 분포]")
    for key, count in sorted(node_diff_dist.items()):
        print(f"    {key}: {count}")

    return len(samples)


# ── CLI ────────────────────────────────────────────────────
# 실행 명령어:
#   python generate_intent_rate.py
#   python generate_intent_rate.py --model gpt-4o
#   python generate_intent_rate.py --info <info.json 경로> --output <output.jsonl 경로>

def main():
    parser = argparse.ArgumentParser(description="Supervisor 라우팅 평가 데이터셋 생성")
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
        model_override=args.model,
    )


if __name__ == "__main__":
    main()
