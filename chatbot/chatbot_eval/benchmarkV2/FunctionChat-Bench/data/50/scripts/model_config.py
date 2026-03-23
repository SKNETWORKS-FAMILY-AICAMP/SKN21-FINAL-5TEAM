# data/50/scripts/model_config.py
import os
from dotenv import load_dotenv
from pathlib import Path

# 프로젝트 루트 로드 (상위 data/ 폴더의 paths.py 활용 가능성 대비)
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent.parent.parent # SKN21-FINAL-5TEAM 루트

# 전역적으로 사용할 기본 모델 (검증, 출력 생성 등)
DEFAULT_MODEL = "gpt-5"

# 다변화(diversify) 전용 모델 (더 높은 창의성이나 품질이 필요한 경우)
DIVERSIFY_MODEL = "gpt-4o-mini"
