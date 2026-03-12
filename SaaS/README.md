# SaaS Adapter Layer

이 디렉토리는 3개 커머스 사이트(`food`, `bilyeo`, `ecommerce`)를 공통 챗봇 툴 인터페이스로 연결하기 위한 Adapter 계층입니다.

## 디렉토리 구조

```text
SaaS/
├─ docs/
└─ src/
   ├─ domain/
   │  ├─ ecommerce.ts        # 공통 타입/인터페이스(EcommerceSupportAdapter)
   │  └─ errors.ts           # AdapterError
   │
   ├─ adapters/
   │  ├─ base/
   │  │  ├─ BaseEcommerceSupportAdapter.ts   # 공통 추상 베이스
   │  │  └─ AdapterRegistry.ts               # siteId -> adapter registry
   │  │
   │  ├─ site-a/
   │  │  ├─ SiteAAdapter.ts
   │  │  ├─ auth.ts
   │  │  ├─ client.ts
   │  │  └─ mappers.ts
   │  │
   │  ├─ site-b/
   │  │  ├─ SiteBAdapter.ts
   │  │  ├─ auth.ts
   │  │  ├─ client.ts
   │  │  └─ mappers.ts
   │  │
   │  ├─ site-c/
   │  │  ├─ SiteCAdapter.ts
   │  │  ├─ auth.ts
   │  │  ├─ client.ts
   │  │  └─ mappers.ts
   │  │
   │  └─ createRegistry.ts   # 최종 매핑/등록
   │
   └─ tools/
      └─ executeTool.ts      # 챗봇 toolName 라우팅
```

## 현재 site 매핑(재배치 완료 상태)

`createRegistry.ts` 기준:

- `site-a` -> **ecommerce** 구현 (`SiteCAdapter` 사용)
- `site-b` -> **food** 구현 (`SiteAAdapter` 사용)
- `site-c` -> **bilyeo** 구현 (`SiteBAdapter` 사용)

## 파일 역할 요약

- `auth.ts`: 사이트별 인증 헤더/쿠키 조립, 컨텍스트 검증
- `client.ts`: 사이트 실제 API 엔드포인트 호출
- `mappers.ts`: 사이트 응답 포맷 -> 공통 도메인 포맷 변환
- `Site*Adapter.ts`: 공통 인터페이스 구현 + 사이트별 비즈니스 제약 처리

## 엔트리 포인트

- Registry 생성: `src/adapters/createRegistry.ts`
- Tool 실행: `src/tools/executeTool.ts`

필요 시 다음 단계로 각 사이트별 미지원 기능(`NOT_SUPPORTED`)을 실제 API 확장에 맞춰 점진적으로 채우면 됩니다.
