# LLM-First Insertion Hints Design

## Goal
LLM이 `patch-proposal.json`에 수정 대상뿐 아니라 삽입 위치 힌트까지 제안하고, deterministic patch draft가 그 힌트를 우선 사용하게 만든다.

## Chosen Approach
- 유지:
  - `codebase-map.json`
  - deterministic patch application / simulation / evaluation
- 추가:
  - 후보 파일 일부 내용 샘플을 LLM proposal 입력에 포함
  - target마다 `insertion_hint` 추가
  - patch writer는 `insertion_hint`가 있으면 우선 적용
  - 실패 시 기존 deterministic 삽입 로직 fallback

## Hint Shape
- `anchor_text`: 문자열 anchor
- `position`: `after` | `before` | `append`
- `notes`: 선택 이유

## Scope
- Python view/urlconf
- React App/component

## Validation
- anchor_text는 source snippet에 실제 존재해야 함
- 없으면 fallback

## Testing
- hint 기반 views 삽입
- hint 기반 urls 삽입
- hint 기반 React mount 삽입
- invalid hint fallback
