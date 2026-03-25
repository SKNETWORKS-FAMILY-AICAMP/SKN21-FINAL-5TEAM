"""Kurly FAQ crawler.

This module crawls the public Kurly FAQ API and can optionally export
the crawled data to JSON or SQLite.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

FAQ_API_URL = "https://api.kurly.com/member/proxy/member-board/v1/faq/posts/shop"
FAQ_PAGE_URL = "https://www.kurly.com/board/faq"
DEFAULT_PAGE_SIZE = 15
DEFAULT_TIMEOUT = 30

class HTMLTextExtractor(HTMLParser):
    """Convert FAQ HTML fragments into readable plain text."""

    BLOCK_TAGS = {"p", "div", "ul", "ol", "li", "br"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "li"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data:
            self._parts.append(data)

    def get_text(self) -> str:
        merged = unescape("".join(self._parts))
        merged = merged.replace("\xa0", " ")
        merged = re.sub(r"\n{3,}", "\n\n", merged)
        return "\n".join(line.rstrip() for line in merged.splitlines() if line.strip()).strip()


@dataclass(slots=True)
class KurlyFaq:
    no: int
    category: str
    question: str
    answer: str
    question_html: str
    answer_html: str
    source_url: str
    crawled_at: str


def html_to_text(html: str) -> str:
    extractor = HTMLTextExtractor()
    extractor.feed(html or "")
    extractor.close()
    return extractor.get_text()


def fetch_faq_page(page: int, size: int = DEFAULT_PAGE_SIZE, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    url = f"{FAQ_API_URL}?page={page}&size={size}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Referer": FAQ_PAGE_URL,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Kurly FAQ request failed with HTTP {exc.code}: {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Kurly FAQ request failed: {exc.reason}") from exc

    if not payload.get("success"):
        raise RuntimeError(f"Kurly FAQ API returned an unsuccessful response: {payload}")

    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError(f"Kurly FAQ API returned an unexpected payload: {payload}")

    return data


def normalize_faq(item: dict, crawled_at: str) -> KurlyFaq:
    question_html = (item.get("question") or "").strip()
    answer_html = (item.get("answer") or "").strip()

    return KurlyFaq(
        no=int(item["no"]),
        category=str(item.get("category") or "").strip(),
        question=html_to_text(question_html),
        answer=html_to_text(answer_html),
        question_html=question_html,
        answer_html=answer_html,
        source_url=FAQ_PAGE_URL,
        crawled_at=crawled_at,
    )


def crawl_all_faqs(page_size: int = DEFAULT_PAGE_SIZE, timeout: int = DEFAULT_TIMEOUT) -> list[KurlyFaq]:
    crawled_at = datetime.now(timezone.utc).isoformat()
    page = 0
    seen_numbers: set[int] = set()
    faqs: list[KurlyFaq] = []

    while True:
        items = fetch_faq_page(page=page, size=page_size, timeout=timeout)
        if not items:
            break

        page_faqs = [normalize_faq(item, crawled_at) for item in items]
        new_faqs = [faq for faq in page_faqs if faq.no not in seen_numbers]
        if not new_faqs:
            break

        faqs.extend(new_faqs)
        seen_numbers.update(faq.no for faq in new_faqs)

        if len(items) < page_size:
            break
        page += 1

    return sorted(faqs, key=lambda faq: faq.no, reverse=True)


def serialize_faqs(faqs: Iterable[KurlyFaq]) -> list[dict]:
    return [asdict(faq) for faq in faqs]


def save_to_json(faqs: Iterable[KurlyFaq], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(serialize_faqs(faqs), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl Kurly FAQ data.")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help="FAQ API page size.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout in seconds.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("crawling/kurly_faq.json"),
        help="Path to save the crawled FAQ JSON file.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    faqs = crawl_all_faqs(page_size=args.page_size, timeout=args.timeout)
    save_to_json(faqs, args.output)

    print(f"Crawled {len(faqs)} Kurly FAQ items.")
    print(f"Saved JSON to: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
