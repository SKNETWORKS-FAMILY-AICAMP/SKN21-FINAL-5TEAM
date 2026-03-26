# ONMO

`onmo`는 온보딩 시연 영상을 찍기 위한 독립형 데모 대시보드입니다.
브라우저에서 온보딩 실행을 시작하고, 단계별 진행 상황과 최종 검증 결과를 한 화면에서 보여줍니다.

## 실행

```bash
uv run python -m onmo.app
```

실행 후 `http://127.0.0.1:8899`로 접속하면 됩니다.

## 화면 구성

상단에는 대시보드의 쓰임을 바로 이해할 수 있도록 좌우 설명 카드가 있습니다.

- 왼쪽: 온보딩 실행 입력값, 빠른 프리셋, 최근 실행 이력을 다룹니다.
- 오른쪽: 단계 타임라인, 분석/계획/컴파일 요약, 검증 카드, 최종 프리뷰를 보여줍니다.

## 무엇을 보여주나

- 브라우저에서 `chatbot.scripts.run_onboarding_generation` 실행
- 생성된 `run_root` 감시
- `analysis -> planning -> compile -> apply -> export -> validation` 시각화
- validation 증명 카드와 선택형 preview iframe 표시

## 참고

- 기본 generated/runtime 루트는 `generated-v2`, `runtime-v2`입니다.
- preview iframe은 최종 시연용 화면입니다.
- 실제 대상 프론트엔드와 챗봇 서버는 별도로 실행되어 있어야 합니다.
