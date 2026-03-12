# SaaS 프로젝트 구조 분석

SaaS 디렉토리는 **Clean Architecture (Ports and Adapters)** 패턴을 따르고 있으며, 통합된 인터페이스를 통해 여러 이커머스 플랫폼을 지원할 수 있도록 설계되었습니다.

## 🏗 아키텍처 개요

시스템은 크게 세 개의 계층으로 나뉩니다:
1. **Domain (도메인)**: 핵심 비즈니스 로직 및 인터페이스 정의 (시스템 전반의 규약).
2. **Adapters (어댑터)**: 특정 외부 플랫폼을 위한 구체적인 구현체 (세부 구현 사항).
3. **Tools (툴)**: AI 에이전트와 같은 상위 애플리케이션이 도메인 로직과 상호작용하기 위한 인터페이스.

---

## 📂 디렉토리 및 파일 역할

### 1. 도메인 계층 (`src/domain/`)
특정 플랫폼에 의존하지 않고 시스템이 "무엇"을 하는지 정의합니다.

| 파일 | 역할 | 설명 |
| :--- | :--- | :--- |
| [ecommerce.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/domain/ecommerce.ts) | **Ports & Entities** | 핵심 데이터 모델(`Product`, `Order`, `User`)과 [EcommerceSupportAdapter](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/domain/ecommerce.ts#L188) 인터페이스를 정의합니다. |
| [errors.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/domain/errors.ts) | **Error Handling** | 모든 어댑터에서 일관된 에러 보고를 위해 `AdapterError`와 같은 사용자 정의 에러 타입을 정의합니다. |

### 2. 어댑터 계층 (`src/adapters/`)
외부 이커머스 플랫폼(Site-A, Site-B 등)에 연동하는 "방법"을 처리합니다.

| 파일/디렉토리 | 역할 | 설명 |
| :--- | :--- | :--- |
| `base/` | **Common Logic** | 공통 유틸리티를 제공하는 [BaseEcommerceSupportAdapter](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/adapters/base/BaseEcommerceSupportAdapter.ts)와 어댑터를 관리하는 [AdapterRegistry](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/adapters/base/AdapterRegistry.ts)가 포함되어 있습니다. |
| `site-a/`, `site-b/` 등 | **Pluggable Adapters** | 플랫폼별 특화 로직입니다. 각 디렉토리에는 `Adapter`, `Client`, `Mappers` 등이 포함되어 있습니다 (예: [SiteAAdapter.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/adapters/site-a/SiteAAdapter.ts)). |
| [createRegistry.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/adapters/createRegistry.ts) | **Bootstrap** | 사용 가능한 모든 어댑터를 초기화하고 레지스트리에 등록하는 팩토리 함수입니다. |

### 3. 툴 계층 (`src/tools/`)
도메인 로직과 AI 에이전트 또는 UI 사이를 연결합니다.

| 파일 | 역할 | 설명 |
| :--- | :--- | :--- |
| [executeTool.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/tools/executeTool.ts) | **Tool Executor** | 컨텍스트의 `siteId`에 따라 적절한 어댑터의 기능을 호출합니다. |

---

## 🔄 상호작용 흐름

1. **입력**: `toolName`과 사이트 컨텍스트([AuthenticatedContext](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/domain/ecommerce.ts#L10))가 포함된 요청을 받습니다.
2. **레지스트리 조회**: [executeTool.ts](file:///Users/junseok/Projects/SKN21-FINAL-5TEAM/SaaS/src/tools/executeTool.ts)가 레지스트리에서 해당 사이트의 어댑터를 찾습니다.
3. **어댑터 호출**: 특정 어댑터(예: `SiteAAdapter`)가 실행됩니다.
4. **외부 API**: 어댑터 내부의 클라이언트가 실제 이커머스 API를 호출합니다.
5. **매핑**: API 응답을 표준 도메인 모델로 변환합니다.
6. **출력**: 표준화된 결과를 반환합니다.

---

## 💡 주요 디자인 패턴
- **표준화된 인터페이스**: 모든 사이트가 동일한 규약으로 동작합니다.
- **데이터 매핑**: 외부 변화로부터 핵심 로직을 격리합니다.
- **의존성 역전**: 구체적인 구현이 아닌 추상화된 인터페이스에 의존합니다.
