#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pandas",
# ]
# ///
"""
패션 데이터셋에서 옷 종류별로 균등하게 샘플링하는 스크립트
- styles.csv를 읽어서 각 articleType별로 일정한 비율을 유지하며 1000개를 샘플링합니다
- 이미지 파일의 존재 여부를 확인하고, 샘플링된 데이터를 새로운 폴더에 복사합니다
"""

import pandas as pd
import os
import shutil
from pathlib import Path
from typing import Tuple

# 경로 설정
BASE_DIR = Path("/Users/junseok/Projects/SKN21-FINAL-5TEAM/data")
RAW_DIR = BASE_DIR / "raw" / "fashion-dataset"
STYLES_CSV = RAW_DIR / "styles.csv"
IMAGES_DIR = RAW_DIR / "images"

# 출력 경로
OUTPUT_DIR = BASE_DIR / "processed" / "fashion-1000-balanced"
OUTPUT_IMAGES_DIR = OUTPUT_DIR / "images"
OUTPUT_CSV = OUTPUT_DIR / "sampled_styles.csv"

# 샘플링할 총 개수
TOTAL_SAMPLES = 1000


def load_and_validate_data() -> pd.DataFrame:
    """
    CSV를 로드하고 이미지 파일이 실제로 존재하는 데이터만 필터링
    """
    print(f"📂 Loading data from {STYLES_CSV}...")
    
    # CSV 읽기 (잘못된 라인은 건너뛰기)
    try:
        df = pd.read_csv(STYLES_CSV, on_bad_lines='skip', engine='python')
    except Exception as e:
        print(f"❌ Error loading CSV with python engine: {e}")
        print(f"🔄 Trying with error_bad_lines=False...")
        df = pd.read_csv(STYLES_CSV, encoding='utf-8', quotechar='"', escapechar='\\')
    
    print(f"✅ Total records in CSV: {len(df)}")
    
    # 이미지 파일 존재 여부 확인
    print(f"🔍 Checking image files existence...")
    df['image_path'] = df['id'].apply(lambda x: IMAGES_DIR / f"{x}.jpg")
    df['image_exists'] = df['image_path'].apply(lambda x: x.exists())
    
    # 이미지가 존재하는 것만 필터링
    df_valid = df[df['image_exists']].copy()
    print(f"✅ Valid records with images: {len(df_valid)}")
    print(f"❌ Missing images: {len(df) - len(df_valid)}")
    
    return df_valid


def analyze_article_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    articleType별 데이터 분포 분석
    """
    print(f"\n📊 Analyzing articleType distribution...")
    article_counts = df['articleType'].value_counts()
    print(f"✅ Number of unique article types: {len(article_counts)}")
    print(f"\nTop 10 article types:")
    print(article_counts.head(10))
    
    return article_counts


def balanced_sampling(df: pd.DataFrame, total_samples: int) -> pd.DataFrame:
    """
    각 옷 종류별로 균등하게 샘플링
    
    전략:
    1. 각 articleType별로 동일한 개수를 샘플링 (비율 유지)
    2. 만약 어떤 articleType의 데이터가 부족하면, 가능한 만큼만 샘플링
    3. 부족한 만큼은 다른 articleType에서 추가 샘플링
    """
    article_counts = df['articleType'].value_counts()
    n_types = len(article_counts)
    
    # 각 타입당 기본 샘플 개수
    samples_per_type = total_samples // n_types
    print(f"\n🎯 Sampling strategy:")
    print(f"   - Total article types: {n_types}")
    print(f"   - Base samples per type: {samples_per_type}")
    
    sampled_dfs = []
    remaining_samples = total_samples
    
    # 첫 번째 패스: 각 타입에서 균등하게 샘플링
    for article_type in article_counts.index:
        type_df = df[df['articleType'] == article_type]
        available = len(type_df)
        
        # 샘플링할 개수 결정 (가용 데이터와 비교)
        n_samples = min(samples_per_type, available, remaining_samples)
        
        if n_samples > 0:
            sampled = type_df.sample(n=n_samples, random_state=42)
            sampled_dfs.append(sampled)
            remaining_samples -= n_samples
            
    # 결합
    result_df = pd.concat(sampled_dfs, ignore_index=True)
    
    # 두 번째 패스: 부족한 샘플을 추가로 채우기
    if remaining_samples > 0:
        print(f"⚠️  Need {remaining_samples} more samples to reach {total_samples}")
        
        # 이미 샘플링된 데이터를 제외한 나머지에서 무작위 샘플링
        remaining_df = df[~df['id'].isin(result_df['id'])]
        
        if len(remaining_df) >= remaining_samples:
            extra_samples = remaining_df.sample(n=remaining_samples, random_state=42)
            result_df = pd.concat([result_df, extra_samples], ignore_index=True)
        else:
            print(f"⚠️  Only {len(remaining_df)} samples available, using all")
            result_df = pd.concat([result_df, remaining_df], ignore_index=True)
    
    return result_df


def copy_sampled_data(df: pd.DataFrame, output_dir: Path, output_images_dir: Path):
    """
    샘플링된 데이터의 이미지를 새 폴더로 복사
    """
    # 출력 디렉토리 생성
    output_dir.mkdir(parents=True, exist_ok=True)
    output_images_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n📁 Copying sampled images to {output_images_dir}...")
    
    for idx, row in df.iterrows():
        src_path = row['image_path']
        dst_path = output_images_dir / f"{row['id']}.jpg"
        
        if src_path.exists():
            shutil.copy2(src_path, dst_path)
        
        if (idx + 1) % 100 == 0:
            print(f"   Copied {idx + 1}/{len(df)} images...")
    
    print(f"✅ All {len(df)} images copied successfully!")


def save_sampled_csv(df: pd.DataFrame, output_csv: Path):
    """
    샘플링된 데이터를 CSV로 저장
    """
    # image_path와 image_exists 컬럼 제거 (메타데이터이므로)
    df_to_save = df.drop(columns=['image_path', 'image_exists'], errors='ignore')
    
    print(f"\n💾 Saving sampled data to {output_csv}...")
    df_to_save.to_csv(output_csv, index=False)
    print(f"✅ CSV saved successfully!")


def print_final_statistics(df: pd.DataFrame):
    """
    최종 샘플링 결과 통계 출력
    """
    print(f"\n" + "="*60)
    print(f"📊 FINAL SAMPLING STATISTICS")
    print(f"="*60)
    print(f"Total sampled records: {len(df)}\n")
    
    article_dist = df['articleType'].value_counts()
    print(f"Distribution by articleType:")
    print(f"-" * 60)
    for article_type, count in article_dist.items():
        percentage = (count / len(df)) * 100
        print(f"  {article_type:30s}: {count:4d} ({percentage:5.2f}%)")
    
    print(f"\n" + "="*60)
    print(f"✅ Sampling completed successfully!")
    print(f"="*60)


def main():
    """
    메인 실행 함수
    """
    print("🚀 Starting balanced fashion dataset sampling...\n")
    
    # 1. 데이터 로드 및 검증
    df_valid = load_and_validate_data()
    
    # 2. articleType 분포 분석
    analyze_article_types(df_valid)
    
    # 3. 균등 샘플링
    sampled_df = balanced_sampling(df_valid, TOTAL_SAMPLES)
    
    # 4. 이미지 복사
    copy_sampled_data(sampled_df, OUTPUT_DIR, OUTPUT_IMAGES_DIR)
    
    # 5. CSV 저장
    save_sampled_csv(sampled_df, OUTPUT_CSV)
    
    # 6. 최종 통계 출력
    print_final_statistics(sampled_df)
    
    print(f"\n📁 Output directory: {OUTPUT_DIR}")
    print(f"   - Images: {OUTPUT_IMAGES_DIR}")
    print(f"   - CSV: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
