"""
상품 크롤링 스크립트
올리브영 상품 페이지에서 카테고리별 상품 정보를 크롤링합니다.
상품 상세페이지에서 상품정보 제공고시와 첫 번째 리뷰를 product_info에 저장합니다.

사용법: python product_crawling.py

사전 설치:
  pip install playwright playwright-stealth
  playwright install chromium
"""

import re
import sys
import os
import time
import random
import uuid
import json
import boto3
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
import urllib.request

# backend 디렉토리를 path에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from env_bootstrap import ensure_backend_env_loaded

ensure_backend_env_loaded()

import oracledb
from models import get_connection

from playwright.sync_api import sync_playwright, Page
from playwright_stealth import Stealth
from html.parser import HTMLParser


# ===== Cloudflare R2 설정 =====

R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_BUCKET = os.getenv("R2_BUCKET")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL")
FAST_SEED = os.getenv("BILYEO_FAST_SEED", "0").lower() not in {"0", "false", "no"}
CRAWL_EXPORT_DIR = os.getenv("BILYEO_CRAWL_EXPORT_DIR", "crawl_exports")
IMAGE_SAVE_DIR = os.getenv(
    "BILYEO_IMAGE_SAVE_DIR",
    os.path.join(os.path.dirname(__file__), "downloaded_images"),
)

# ===== R2 무료 한도 (월별) =====
CLASS_A_LIMIT = 1_000_000  # Class A (쓰기: PutObject, ListObjects 등)
CLASS_B_LIMIT = 10_000_000  # Class B (읽기: GetObject 등)
STORAGE_LIMIT_GB = 10  # 저장 용량 10GB

# 사용량 파일 경로
USAGE_FILE = os.path.join(os.path.dirname(__file__), "image_usage.json")


def _resolve_crawl_export_dir(export_dir: str | os.PathLike[str] | None = None) -> Path:
    raw = str(export_dir or CRAWL_EXPORT_DIR or "").strip()
    if not raw:
        raw = "crawl_exports"
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def export_crawled_products(
    products: list[dict],
    *,
    export_dir: str | os.PathLike[str] | None = None,
    captured_at: datetime | None = None,
) -> dict[str, str | int]:
    export_root = _resolve_crawl_export_dir(export_dir)
    export_root.mkdir(parents=True, exist_ok=True)

    timestamp = captured_at or datetime.now()
    payload = {
        "site": "bilyeo",
        "captured_at": timestamp.isoformat(),
        "product_count": len(products),
        "fast_seed": FAST_SEED,
        "products": products,
    }

    latest_path = export_root / "latest-products.json"
    snapshot_path = export_root / f"products-{timestamp.strftime('%Y%m%d-%H%M%S')}.json"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    latest_path.write_text(serialized, encoding="utf-8")
    snapshot_path.write_text(serialized, encoding="utf-8")

    return {
        "latest_path": str(latest_path),
        "snapshot_path": str(snapshot_path),
        "product_count": len(products),
    }


def _load_usage() -> dict:
    """image_usage.json에서 누적 사용량을 로드합니다. 월이 바뀌면 base 기본값으로 초기화합니다."""
    current_month = datetime.now().strftime("%Y-%m")
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        base = data.get("base", {"class_a": 0, "class_b": 0, "storage_bytes": 0})
        current = data.get("current", {})
        # 월이 바뀌면 base 기본값으로 초기화
        if current.get("month") != current_month:
            data["current"] = {
                "month": current_month,
                "class_a": base["class_a"],
                "class_b": base["class_b"],
                "storage_bytes": base["storage_bytes"],
            }
            _save_usage(data)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        data = {
            "base": {"class_a": 0, "class_b": 0, "storage_bytes": 0},
            "current": {
                "month": current_month,
                "class_a": 0,
                "class_b": 0,
                "storage_bytes": 0,
            },
        }
        _save_usage(data)
        return data


def _save_usage(data: dict):
    """image_usage.json에 사용량을 저장합니다."""
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def _check_class_a_limit(operation_count: int = 1) -> bool:
    """Class A 한도를 초과하는지 확인합니다."""
    usage = _load_usage()
    current = usage["current"]
    if current["class_a"] + operation_count > CLASS_A_LIMIT:
        print(
            f"  [R2 제한] Class A 한도 초과! ({current['class_a']:,}/{CLASS_A_LIMIT:,})"
        )
        return False
    return True


def _check_class_b_limit(operation_count: int = 1) -> bool:
    """Class B 한도를 초과하는지 확인합니다."""
    usage = _load_usage()
    current = usage["current"]
    if current["class_b"] + operation_count > CLASS_B_LIMIT:
        print(
            f"  [R2 제한] Class B 한도 초과! ({current['class_b']:,}/{CLASS_B_LIMIT:,})"
        )
        return False
    return True


def _increment_class_a(count: int = 1):
    usage = _load_usage()
    usage["current"]["class_a"] += count
    _save_usage(usage)


def _increment_class_b(count: int = 1):
    usage = _load_usage()
    usage["current"]["class_b"] += count
    _save_usage(usage)


def get_r2_client():
    """Cloudflare R2 S3 클라이언트를 생성합니다."""
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _check_storage_limit(file_size: int) -> bool:
    """저장 용량 한도를 초과하는지 확인합니다."""
    usage = _load_usage()
    current = usage["current"]
    limit_bytes = STORAGE_LIMIT_GB * 1024 * 1024 * 1024
    if current["storage_bytes"] + file_size > limit_bytes:
        used_gb = current["storage_bytes"] / (1024 * 1024 * 1024)
        print(
            f"  [R2 제한] 저장 용량 한도 초과! ({used_gb:.2f} GB/{STORAGE_LIMIT_GB} GB)"
        )
        return False
    return True


def _increment_storage(file_size: int):
    usage = _load_usage()
    usage["current"]["storage_bytes"] += file_size
    _save_usage(usage)


def upload_image_to_r2(image_url: str, filename: str) -> bool:
    """이미지를 다운로드하여 R2에 업로드합니다. (Class A 1회 소모)"""
    import urllib.request

    if not _check_class_a_limit():
        return False
    try:
        req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        content = resp.read()

        file_size = len(content)
        if not _check_storage_limit(file_size):
            return False

        r2 = get_r2_client()
        r2.put_object(
            Bucket=R2_BUCKET,
            Key=f"images/{filename}",
            Body=content,
            ContentType="image/jpeg",
        )
        _increment_class_a()
        _increment_storage(file_size)
        return True
    except Exception as e:
        print(f"  [R2 업로드] 에러: {e}")
        return False


def check_r2_storage_usage():
    """R2 버킷의 업로드/다운로드량을 확인합니다. (Class A: ListObjects 소모)"""
    if not _check_class_a_limit():
        return 0, 0

    r2 = get_r2_client()

    # 버킷 내 객체 목록 조회
    total_size = 0
    total_count = 0
    page_count = 0
    paginator = r2.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix="images/"):
        page_count += 1
        for obj in page.get("Contents", []):
            total_size += obj["Size"]
            total_count += 1

    _increment_class_a(page_count)  # ListObjects 페이지 수만큼 Class A 소모

    size_mb = total_size / (1024 * 1024)

    usage = _load_usage()
    current = usage["current"]
    used_gb = current["storage_bytes"] / (1024 * 1024 * 1024)

    print(f"\n===== R2 스토리지 사용량 =====")
    print(f"  버킷 파일 수: {total_count}개")
    print(f"  버킷 용량: {size_mb:.2f} MB")
    print(f"  버킷: {R2_BUCKET}")
    print(f"--- {current['month']} 월별 누적 ---")
    print(f"  Class A (쓰기): {current['class_a']:,} / {CLASS_A_LIMIT:,}")
    print(f"  Class B (읽기): {current['class_b']:,} / {CLASS_B_LIMIT:,}")
    print(
        f"  누적 용량: {used_gb:.2f} GB / {STORAGE_LIMIT_GB} GB ({used_gb / STORAGE_LIMIT_GB * 100:.1f}%)"
    )
    print(f"==============================")
    return total_count, total_size


def download_image(image_url: str, filename: str) -> bool:
    """이미지를 다운로드하여 로컬에 저장합니다."""
    os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)
    filepath = os.path.join(IMAGE_SAVE_DIR, filename)
    if os.path.exists(filepath):
        return True
    try:
        req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        with open(filepath, "wb") as f:
            f.write(resp.read())
        return True
    except Exception as e:
        print(f"  [이미지] 다운로드 에러: {e}")
    return False


def make_image_filename(image_url: str) -> str:
    """UUID로 고유한 파일명을 생성합니다."""
    # URL에서 확장자 추출
    ext = ".jpg"
    for candidate in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
        if candidate in image_url.lower():
            ext = candidate
            break
    return f"{uuid.uuid4()}{ext}"


def normalize_image_url(image_url: str) -> str:
    """상품 이미지 URL을 절대 URL로 정규화합니다."""
    if not image_url:
        return ""
    if image_url.startswith("//"):
        return f"https:{image_url}"
    return urljoin("https://www.oliveyoung.co.kr", image_url)


# ===== HTTP 세션 =====


def create_browser_page(playwright_instance):
    """Playwright 브라우저와 stealth 페이지를 생성합니다."""
    browser = playwright_instance.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        locale="ko-KR",
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)
    return browser, context, page


def fetch_html(page: "Page", url: str) -> str:
    """Playwright으로 HTML을 가져옵니다."""
    try:
        response = page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)  # JS 렌더링 대기
        html = page.content()
        status = response.status if response else 0
        if len(html) > 1000:
            return html
        print(f"  [fetch] 응답 코드: {status}, 길이: {len(html)}")
    except Exception as e:
        print(f"  [fetch] 요청 실패: {type(e).__name__}: {e}")
    return ""


class ProductHTMLParser(HTMLParser):
    """올리브영 상품 리스트 HTML을 파싱합니다."""

    def __init__(self):
        super().__init__()
        self.products = []
        self._current = {}
        self._in_flag = False
        self._capture = None  # "name", "brand", "price"
        self._text_buf = ""

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        cls = attr.get("class", "")
        if tag == "li" and attr.get("criteo-goods"):
            raw = attr.get("criteo-goods", "").strip()
            # goodsNo 형식: 영문자 1자 + 숫자 12자 (총 13자), 뒤에 옵션 suffix 제거
            m = re.match(r"([A-Za-z][0-9]{12})", raw)
            goods_no = m.group(1) if m else raw
            detail_url = (
                f"https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo={goods_no}"
                if goods_no
                else ""
            )
            self._in_flag = True
            self._current = {
                "name": "",
                "brand": "",
                "price": 0,
                "description": "",
                "image_url": "",
                "stock": 100,
                "goods_no": goods_no,
                "detail_url": detail_url,
            }
        if not self._in_flag:
            return
        if "tx_name" in cls or "prd_name" in cls:
            self._capture = "name"
            self._text_buf = ""
        elif "tx_brand" in cls or "prd_brand" in cls:
            self._capture = "brand"
            self._text_buf = ""
        elif "tx_num" in cls:
            self._capture = "price"
            self._text_buf = ""
        if tag == "img" and self._in_flag:
            src = attr.get("src", "")
            if src and not self._current.get("image_url"):
                self._current["image_url"] = normalize_image_url(src)

    def handle_data(self, data):
        if self._capture:
            self._text_buf += data.strip()

    def handle_endtag(self, tag):
        if self._capture and self._text_buf:
            if self._capture == "price":
                price_text = self._text_buf.replace(",", "")
                self._current["price"] = int(price_text) if price_text.isdigit() else 0
            else:
                self._current[self._capture] = self._text_buf
            self._capture = None
            self._text_buf = ""
        if tag == "li" and self._in_flag:
            if self._current.get("name"):
                self.products.append(self._current)
            self._current = {}
            self._in_flag = False


# ===== 디버그 로그 =====
_debug_logs = []

# ===== 상품정보 제공고시 필드 매핑 =====

PRODUCT_INFO_FIELD_MAP = {
    "내용물의 용량 또는 중량": "volume_weight",
    "제품 주요 사양": "main_spec",
    "사용기한": "expiry",
    "사용방법": "usage_method",
    "화장품제조업자": "manufacturer",
    "제조국": "country_of_origin",
    "화장품법에 따라 기재해야 하는 모든 성분": "ingredients",
    "기능성 화장품": "functional_cosmetic",
    "사용할 때의 주의사항": "precautions",
    "품질보증기준": "quality_standard",
    "소비자상담": "consumer_hotline",
}


def extract_standard_code_from_html(html: str) -> str:
    """상세페이지 HTML에서 standardCode(바코드)를 추출합니다.
    \"standardCode\":\"...\" (이스케이프) 및 "standardCode":"..." 두 형태 모두 처리합니다."""
    match = re.search(r'\\?"standardCode\\?"\s*:\s*\\?"([^"\\]+)', html)
    if match:
        return match.group(1)
    return ""


def extract_goods_option_info_list(page: "Page", goods_number: str) -> list:
    """상세페이지에서 goodsOptionInfoList를 추출합니다."""
    html = page.content()

    # 방법 1: JS DOM에서 옵션 select 요소 탐색 (standardCode, optionName)
    try:
        result = page.evaluate("""
            () => {
                // select 옵션에서 standardCode / optionName 추출
                const opts = document.querySelectorAll('select option');
                const list = [];
                opts.forEach(opt => {
                    const sc = opt.getAttribute('data-standard-code')
                             || opt.getAttribute('data-standardcode')
                             || opt.getAttribute('standardcode');
                    const name = opt.textContent.trim();
                    if (sc && name) {
                        list.push({ standardCode: sc, optionName: name });
                    }
                });
                if (list.length > 0) return list;
                return null;
            }
        """)
        if result and len(result) > 0:
            return result
    except Exception as e:
        print(f"  [옵션 추출] JS DOM 탐색 에러: {e}")

    # 방법 2: HTML script 태그에서 {standardCode, optionName} 배열 regex 추출
    try:
        # goodsOptionInfoList 변수 할당 패턴
        match = re.search(
            r"goodsOptionInfoList\s*[:=]\s*(\[[^\]]*standardCode[^\]]*\])",
            html,
            re.DOTALL,
        )
        if match:
            # JS 객체 리터럴(키에 따옴표 없음)을 JSON으로 변환
            raw = match.group(1)
            raw_json = re.sub(r"(\w+)\s*:", r'"\1":', raw)  # 키에 따옴표 추가
            raw_json = re.sub(r",\s*}", "}", raw_json)  # trailing comma 제거
            parsed = json.loads(raw_json)
            if parsed:
                return parsed
    except Exception:
        pass

    # 방법 2-B: 이스케이프된 JSON의 options 배열 파싱 (Next.js stringified JSON 대응)
    # HTML 내 데이터가 \"options\":[{\"standardCode\":\"...\",\"optionName\":\"...\"}] 형태인 경우
    try:
        match = re.search(
            r'\\"options\\":\s*(\[(?:[^\[\]]|\[(?:[^\[\]])*\])*\])', html, re.DOTALL
        )
        if match:
            raw = match.group(1).replace('\\"', '"')
            parsed = json.loads(raw)
            result = [
                {"standardCode": o["standardCode"], "optionName": o["optionName"]}
                for o in parsed
                if o.get("standardCode") and o.get("optionName")
            ]
            if result:
                return result
    except Exception:
        pass

    # 방법 3: standardCode + optionName 쌍을 HTML 전체에서 수집
    # 일반 형태("key":"value")와 이스케이프 형태(\"key\":\"value\") 모두 처리
    try:
        # 이스케이프 형태: \"standardCode\":\"12345678\",\"optionName\":\"이름\"
        pairs = re.findall(
            r'\\"standardCode\\":\\"([0-9]{8,14})\\"[^}]{0,300}?\\"optionName\\":\\"([^"\\]+)',
            html,
        )
        if not pairs:
            # 일반 형태
            pairs = re.findall(
                r'"standardCode"\s*:\s*"([0-9]{8,14})"[^}]{0,300}?"optionName"\s*:\s*"([^"]+)"',
                html,
            )
        if pairs:
            return [
                {"standardCode": sc, "optionName": name.strip()} for sc, name in pairs
            ]
    except Exception:
        pass

    # Fallback: standardCode만으로 최소 항목 구성
    standard_code = extract_standard_code_from_html(html)
    if standard_code:
        print(f"  [옵션 추출] fallback standardCode={standard_code}")
        return [{"standardCode": standard_code}]
    print(f"  [옵션 추출] standardCode 미발견, goodsNo={goods_number}")
    return []


def _call_article_api(page: "Page", goods_number: str, option_list: list) -> dict:
    """제공고시 API를 한 번 호출하고 결과를 파싱합니다."""
    result = page.evaluate(
        """
        async ([goodsNumber, goodsOptionInfoList]) => {
            const resp = await fetch('https://www.oliveyoung.co.kr/goods/api/v1/article', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    goodsNumber: goodsNumber,
                    liquorFlag: false,
                    goodsOptionInfoList: goodsOptionInfoList
                })
            });
            let data = null;
            try { data = await resp.json(); } catch(e) {}
            return { status: resp.status, data: data };
        }
    """,
        [goods_number, option_list],
    )
    if result["status"] != 200:
        _debug_logs.append(
            f"  [제공고시] 응답 에러 코드: {result['status']}, options: {option_list}, body: {str(result['data'])[:300]}"
        )
    if result["status"] == 200 and result["data"]:
        article_list = result["data"].get("data", {}).get("articleInfoList", [])
        info = {}
        for item in article_list:
            title = item.get("title", "")
            content = item.get("content", "")
            # 공백 정규화 후 비교 (API 응답 title의 공백 불일치 대응)
            title_normalized = "".join(title.split())
            for key, field in PRODUCT_INFO_FIELD_MAP.items():
                key_normalized = "".join(key.split())
                if key_normalized in title_normalized:
                    info[field] = content
                    break
        if info:
            return info
        if article_list:
            _debug_logs.append(
                f"  [제공고시] articleInfoList 존재하나 매핑 실패. titles: {[item.get('title', '') for item in article_list[:5]]}"
            )
    return {}


def fetch_product_article_api(
    page: "Page", goods_number: str, goods_option_info_list: list
) -> dict:
    """브라우저 컨텍스트에서 fetch()로 제공고시 API를 호출합니다.
    첫 시도 실패 시 빈 옵션 리스트로 재시도합니다."""
    # 시도할 옵션 리스트 후보
    candidates = [goods_option_info_list]
    if goods_option_info_list:
        candidates.append([])  # 실패 시 빈 리스트로 재시도

    for option_list in candidates:
        try:
            info = _call_article_api(page, goods_number, option_list)
            if info:
                return info
        except Exception as e:
            _debug_logs.append(f"  [제공고시 API] 에러: {e}")
    return {}


def fetch_first_review_api(page: "Page", goods_number: str) -> str:
    """브라우저 컨텍스트에서 fetch()로 리뷰 API를 호출합니다."""
    try:
        result = page.evaluate(
            """
            async (goodsNumber) => {
                const resp = await fetch('https://m.oliveyoung.co.kr/review/api/v2/reviews', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        goodsNumber: goodsNumber,
                        page: 0,
                        size: 1,
                        sortType: 'USEFUL_SCORE_DESC',
                        reviewType: 'ALL'
                    })
                });
                if (!resp.ok) return { status: resp.status, data: null };
                const data = await resp.json();
                return { status: resp.status, data: data };
            }
        """,
            goods_number,
        )
        if result["status"] == 200 and result["data"]:
            reviews = result["data"].get("data") or []
            if reviews:
                return reviews[0].get("content", "")
        else:
            print(f"  [리뷰 API] 응답 코드: {result['status']}")
    except Exception as e:
        print(f"  [리뷰 API] 에러: {e}")
    return ""


def fetch_product_detail_info(page: "Page", goods_no: str) -> dict:
    """상품 상세페이지 방문 후 제공고시 API와 리뷰 API를 호출합니다."""
    result = {}

    if not goods_no:
        return result

    detail_url = (
        f"https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo={goods_no}"
    )

    # 상세페이지 방문 (쿠키/Referer 확보)
    try:
        page.goto(detail_url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(random.uniform(2, 3))
    except Exception as e:
        print(f"  [상세페이지] 로드 실패: {e}")
        return result

    # 상품 옵션 리스트 추출 후 제공고시 API 호출
    goods_option_info_list = extract_goods_option_info_list(page, goods_no)
    article_info = fetch_product_article_api(page, goods_no, goods_option_info_list)
    result.update(article_info)
    time.sleep(1)

    # 리뷰 API 호출
    review = fetch_first_review_api(page, goods_no)
    if review:
        result["review"] = review

    return result


# ===== DB 저장 =====


def upsert_product(cursor, product: dict) -> int | None:
    """상품을 삽입하거나 기존 product_id를 반환합니다."""
    cursor.execute(
        "SELECT product_id FROM products WHERE name = :name AND brand = :brand",
        {"name": product["name"], "brand": product["brand"]},
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute(
        """
        INSERT INTO products (name, brand, price, description, image_url, category, stock)
        VALUES (:name, :brand, :price, :description, :image_url, :category, :stock)
    """,
        {
            "name": product["name"],
            "brand": product["brand"],
            "price": product["price"],
            "description": product.get("description", ""),
            "image_url": product.get("image_url", ""),
            "category": product.get("category", ""),
            "stock": product.get("stock", 100),
        },
    )

    cursor.execute(
        "SELECT product_id FROM products WHERE name = :name AND brand = :brand",
        {"name": product["name"], "brand": product["brand"]},
    )
    row = cursor.fetchone()
    return row[0] if row else None


def upsert_product_info(cursor, product_id: int, info: dict) -> bool:
    """product_info를 삽입하거나, 이미 존재하면 업데이트합니다."""
    cursor.execute(
        "SELECT info_id FROM product_info WHERE product_id = :pid",
        {"pid": product_id},
    )
    existing = cursor.fetchone()

    # CLOB 컬럼 타입 힌트 설정 (긴 문자열 바인딩 오류 방지)
    cursor.setinputsizes(
        usage_method=oracledb.DB_TYPE_CLOB,
        manufacturer=oracledb.DB_TYPE_CLOB,
        ingredients=oracledb.DB_TYPE_CLOB,
        precautions=oracledb.DB_TYPE_CLOB,
        review=oracledb.DB_TYPE_CLOB,
    )

    params = {
        "product_id": product_id,
        "volume_weight": info.get("volume_weight", "") or None,
        "main_spec": info.get("main_spec", "") or None,
        "expiry": info.get("expiry", "") or None,
        "usage_method": info.get("usage_method", "") or None,
        "manufacturer": info.get("manufacturer", "") or None,
        "country_of_origin": info.get("country_of_origin", "") or None,
        "ingredients": info.get("ingredients", "") or None,
        "functional_cosmetic": info.get("functional_cosmetic", "") or None,
        "precautions": info.get("precautions", "") or None,
        "quality_standard": info.get("quality_standard", "") or None,
        "consumer_hotline": info.get("consumer_hotline", "") or None,
        "review": info.get("review", "") or None,
    }

    if existing:
        cursor.execute(
            """
            UPDATE product_info SET
                volume_weight = :volume_weight,
                main_spec = :main_spec,
                expiry = :expiry,
                usage_method = :usage_method,
                manufacturer = :manufacturer,
                country_of_origin = :country_of_origin,
                ingredients = :ingredients,
                functional_cosmetic = :functional_cosmetic,
                precautions = :precautions,
                quality_standard = :quality_standard,
                consumer_hotline = :consumer_hotline,
                review = :review
            WHERE product_id = :product_id
        """,
            params,
        )
    else:
        cursor.execute(
            """
            INSERT INTO product_info (
                product_id, volume_weight, main_spec, expiry, usage_method,
                manufacturer, country_of_origin, ingredients, functional_cosmetic,
                precautions, quality_standard, consumer_hotline, review
            ) VALUES (
                :product_id, :volume_weight, :main_spec, :expiry, :usage_method,
                :manufacturer, :country_of_origin, :ingredients, :functional_cosmetic,
                :precautions, :quality_standard, :consumer_hotline, :review
            )
        """,
            params,
        )
    return True


# ===== 올리브영 상품 크롤링 =====

# 스킨케어 서브카테고리 (왼쪽 사이드바 7개)
SUBCATEGORIES = [
    "스킨/토너",
    "에센스/세럼/앰플",
    "크림",
    "로션",
    "미스트/오일",
    "스킨케어세트",
    "스킨케어 디바이스",
]

MAX_PRODUCTS_PER_CATEGORY = 20  # 카테고리당 최대 수집 상품 수

# 서브카테고리별 URL
BASE_CATEGORY_URL = "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do"

SUBCATEGORY_URLS = {
    "스킨/토너": f"{BASE_CATEGORY_URL}?dispCatNo=100000100010013",
    "에센스/세럼/앰플": f"{BASE_CATEGORY_URL}?dispCatNo=100000100010014",
    "크림": f"{BASE_CATEGORY_URL}?dispCatNo=100000100010015",
    "로션": f"{BASE_CATEGORY_URL}?dispCatNo=100000100010016",
    "미스트/오일": f"{BASE_CATEGORY_URL}?dispCatNo=100000100010010",
    "스킨케어세트": f"{BASE_CATEGORY_URL}?dispCatNo=100000100010017",
    "스킨케어 디바이스": f"{BASE_CATEGORY_URL}?dispCatNo=100000100010018",
}


def parse_products_from_html(html: str, max_count: int = 20) -> list[dict]:
    """HTML 문자열에서 상품 정보를 파싱합니다."""
    parser = ProductHTMLParser()
    parser.feed(html)
    return parser.products[:max_count]


def crawl_oliveyoung() -> list[dict]:
    """올리브영 스킨케어 서브카테고리별 상위 20개 상품을 크롤링합니다."""
    print("\n=== 올리브영 스킨케어 상품 크롤링 시작 ===")

    all_products = []

    with sync_playwright() as pw:
        browser, context, page = create_browser_page(pw)
        try:
            # 1단계: 메인 페이지 접속으로 쿠키 획득
            print("\n[1단계] 올리브영 메인 페이지 접속 (쿠키 획득)...")
            page.goto(
                "https://www.oliveyoung.co.kr",
                timeout=30000,
                wait_until="domcontentloaded",
            )
            print("  메인 페이지 로드 완료")
            time.sleep(random.uniform(3, 5))

            # 1-2단계: 스킨케어 카테고리 페이지 방문 (Referer 확보)
            print("\n[1-2단계] 스킨케어 카테고리 페이지 접속...")
            skincare_url = "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100010001"
            page.goto(skincare_url, timeout=30000, wait_until="domcontentloaded")
            print("  스킨케어 카테고리 로드 완료")
            time.sleep(random.uniform(3, 5))

            # 2단계: 각 서브카테고리 크롤링
            for subcategory, url in SUBCATEGORY_URLS.items():
                print(f"\n--- 서브카테고리: {subcategory} ---")

                collected = []
                page_idx = 1

                while len(collected) < MAX_PRODUCTS_PER_CATEGORY:
                    paged_url = f"{url}&pageIdx={page_idx}&rowsPerPage=24"
                    html = fetch_html(page, paged_url)
                    if not html:
                        print(f"  페이지 {page_idx}: HTML 가져오기 실패, 건너뜁니다.")
                        break

                    products = parse_products_from_html(html)
                    if not products:
                        print(f"  페이지 {page_idx}: 상품 없음, 종료")
                        break

                    collected.extend(products)
                    print(
                        f"  페이지 {page_idx}: {len(products)}건 파싱 (누적 {len(collected)}건)"
                    )
                    page_idx += 1
                    time.sleep(random.uniform(4, 8))

                collected = collected[:MAX_PRODUCTS_PER_CATEGORY]
                for product in collected:
                    product["category"] = subcategory
                all_products.extend(collected)
                print(f"  최종 수집: {len(collected)}건")

            if FAST_SEED:
                print(
                    "\n[3단계] 빠른 시드 모드: 상세페이지/리뷰/R2 업로드를 건너뜁니다."
                )
                print(f"\n올리브영 스킨케어 상품 수집 완료: 총 {len(all_products)}건")
                return all_products

            # 3단계: 각 상품 상세페이지에서 상품정보 제공고시 + 첫 번째 리뷰 수집
            print(
                f"\n[3단계] 상품 상세페이지 크롤링 시작 (총 {len(all_products)}건)..."
            )
            for i, product in enumerate(all_products):
                goods_no = product.get("goods_no", "")
                name_short = product.get("name", "")[:25]
                if not goods_no:
                    print(
                        f"  [{i + 1}/{len(all_products)}] {name_short}: goodsNo 없음, 건너뜁니다."
                    )
                    product["product_info"] = {}
                    continue

                print(
                    f"  [{i + 1}/{len(all_products)}] {name_short}: 상세페이지 크롤링... (goodsNo={goods_no})"
                )
                info = fetch_product_detail_info(page, goods_no)
                product["product_info"] = info

                field_count = len([v for v in info.values() if v])
                review_status = "리뷰 있음" if info.get("review") else "리뷰 없음"
                print(f"    → 제공고시 {field_count}개 필드, {review_status}")
                time.sleep(random.uniform(2, 5))

        finally:
            context.close()
            browser.close()

    # 4단계: 이미지를 R2에 업로드 및 URL 변환
    print(f"\n[4단계] R2 이미지 업로드 시작...")
    print(f"  버킷: {R2_BUCKET}")
    print(f"  퍼블릭 URL: {R2_PUBLIC_URL}")

    upload_count = 0
    for product in all_products:
        original_url = product.get("image_url", "")
        if not original_url:
            continue
        filename = make_image_filename(original_url)
        if upload_image_to_r2(original_url, filename):
            product["image_url"] = f"{R2_PUBLIC_URL}/images/{filename}"
            upload_count += 1
        time.sleep(0.3)

    print(f"[R2 업로드] 완료: {upload_count}건")

    # R2 스토리지 사용량 확인
    check_r2_storage_usage()

    print(f"\n올리브영 스킨케어 상품 수집 완료: 총 {len(all_products)}건")
    return all_products


# ===== 메인 =====


def main():
    all_products = crawl_oliveyoung()
    export_result = export_crawled_products(all_products)

    print("\n=== 크롤링 결과 파일 저장 완료 ===")
    print(f"  latest: {export_result['latest_path']}")
    print(f"  snapshot: {export_result['snapshot_path']}")
    print(f"  상품 수: {export_result['product_count']}건")

    if not all_products:
        print("\n크롤링된 상품이 없습니다.")
        return export_result

    conn = get_connection()
    cursor = conn.cursor()
    inserted_products = 0
    inserted_infos = 0

    try:
        for product in all_products:
            product_id = upsert_product(cursor, product)
            if product_id is None:
                print(f"  [DB] product_id 획득 실패: {product.get('name', '')[:30]}")
                continue
            inserted_products += 1

            info = product.get("product_info", {})
            if info:
                try:
                    if upsert_product_info(cursor, product_id, info):
                        inserted_infos += 1
                except Exception as e:
                    _debug_logs.append(
                        f"  [DB] product_info 저장 실패 (product_id={product_id}): {e}"
                    )

        conn.commit()
    finally:
        cursor.close()
        conn.close()

    print(
        f"\n=== DB 저장 완료: 상품 {inserted_products}건, 상품정보 {inserted_infos}건 (총 {len(all_products)}건 수집) ==="
    )

    if _debug_logs:
        print(f"\n===== 디버그 로그 ({len(_debug_logs)}건) =====")
        for log in _debug_logs:
            print(log)
        print("=" * 40)

    return {
        **export_result,
        "inserted_products": inserted_products,
        "inserted_infos": inserted_infos,
    }


if __name__ == "__main__":
    main()
