# Policy RAG Dataset Notes

권장 필드 예시

- `id`: 케이스 식별자
- `user_query`: 사용자 질문
- `expected_query`: 기대하는 검색용 질의
- `expected_doc_ids`: 정답 문서 ID 목록
- `must_include`: 답변에 반드시 포함되어야 하는 사실
- `must_not_include`: 답변에 포함되면 안 되는 추정/환각

처음 버전은 30건 내외의 단문 정책 질의부터 시작하는 것이 좋습니다.
