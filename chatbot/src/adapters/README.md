# Adapter Layer Architecture

다중 쇼핑몰 사이트(Ecommerce, Food, Bilyeo)의 상이한 API 인터페이스를 통일된 도메인 모델로 매핑하는 추상화 계층입니다.

## 1. 구조 개요

- `schema.py`: 전체 어댑터에서 공통으로 사용하는 Pydantic 데이터 모델 (주문, 상품, 배송 등).
- `base.py`: 어댑터 인터페이스 정의(`BaseEcommerceSupportAdapter`) 및 어댑터 관리 레지스트리.
- `setup.py`: 환경 변수를 기반으로 각 사이트 어댑터를 초기화하고 레지스트리에 등록.
- `site_*/`: 각 사이트별 특화 구현 (Client, Auth, Mapper, Adapter).

## 2. 통합 Site ID 매핑

모든 내부 로직과 API 요청에서는 아래의 통일된 `site_id`를 사용해야 합니다.

| Site ID | 모듈 경로 | 연동 서비스 | 비고 |
|---|---|---|---|
| `site-a` | `site_a/` | Food | `:8002` |
| `site-b` | `site_b/` | Bilyeo | `:5000` |
| `site-c` | `site_c/` | Ecommerce | `:8000` |

## 3. 핵심 컴포넌트

### 3-1. Adapter Registry
`AdapterRegistry` 클래스는 등록된 어댑터를 `site_id`로 조회할 수 있게 해줍니다.
```python
from chatbot.src.adapters.setup import get_adapter
adapter = get_adapter("site-a")
```

### 3-2. Pydantic Mappers
각 사이트의 원시 JSON 응답을 `schema.py`의 공통 모델로 변환합니다. 변환 로직은 각 사이트 모듈의 `mappers.py`에 격리되어 있습니다.

### 3-3. Auth Handler
각 사이트마다 다른 인증 방식(Cookie, Bearer Token 등)을 `AuthenticatedContext` 기반으로 처리합니다.

## 4. 새로운 사이트 추가 방법

1. `chatbot/src/adapters/` 아래에 새로운 폴더(예: `site_d`) 생성.
2. `schema.py`를 참조하여 필요한 데이터 모델 확인.
3. `BaseEcommerceSupportAdapter`를 상속받은 클래스 구현.
4. `setup.py`에 초기화 로직 추가.
