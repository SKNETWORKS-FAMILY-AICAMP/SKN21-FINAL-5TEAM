from pathlib import Path


def find_project_root(current_path: Path, marker: str = ".env") -> Path:
    """현재 경로에서 위로 올라가며 marker 파일이 있는 디렉토리를 프로젝트 루트로 반환합니다."""
    for parent in [current_path] + list(current_path.parents):
        if (parent / marker).exists():
            return parent
    return current_path.parents[4]


# API-Bank 루트 (src/paths.py 기준 두 단계 위)
BENCH_ROOT = Path(__file__).resolve().parent.parent  # API-Bank/

# 프로젝트 전체 루트 (.env 기준)
PROJECT_ROOT = find_project_root(BENCH_ROOT)

# 하위 디렉터리
DATA_DIR = BENCH_ROOT / "data"
OUTPUT_DIR = BENCH_ROOT.parent / "result" / "API-Bank"
CONFIG_PATH = BENCH_ROOT / "openai.cfg"
ENV_PATH = PROJECT_ROOT / ".env"
