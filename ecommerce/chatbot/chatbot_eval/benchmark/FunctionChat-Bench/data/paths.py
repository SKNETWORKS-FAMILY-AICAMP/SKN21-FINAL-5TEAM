from pathlib import Path

def find_project_root(current_path: Path, marker: str = ".env") -> Path:
    """현재 경로에서 위로 올라가며 marker 파일이 있는 디렉토리를 찾아 프로젝트 루트로 반환합니다."""
    for parent in [current_path] + list(current_path.parents):
        if (parent / marker).exists():
            return parent
    # 만약 찾지 못하면 기본적으로 3단계 위를 반환 (Fallback)
    return current_path.parents[3]

# data/ 폴더 루트 (data/paths.py 기준)
DATA_DIR = Path(__file__).resolve().parent

# 동적으로 프로젝트 전체 루트 탐색
PROJECT_ROOT = find_project_root(DATA_DIR)

# 원시 데이터 디렉터리 (PROJECT_ROOT 기준으로 절대 경로 명시)
RAW_DIR = PROJECT_ROOT / "ecommerce" / "chatbot" / "data" / "raw"

# 각 소스 경로
FAQ_PATH    = RAW_DIR / "musinsa_faq" / "musinsa_faq_20260203_162139_final.json"
TERMS_PATH  = RAW_DIR / "ecommerce_standard" / "ecommerce_standard_preprocessed.json"
FASHION_CSV = RAW_DIR / "AI_Hub" / "패션_validation.csv"
CLOTHES_CSV = RAW_DIR / "AI_Hub" / "의류_validation.csv"
TOOLS_PATH  = DATA_DIR / "tools.json"
