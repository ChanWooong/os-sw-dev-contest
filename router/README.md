# ③ 라우터 파트 (작업 예정)

사용자 질문을 보고 3종 MCP 도구(vector_search / nl2sql / knowledge_graph) 중
어디로 보낼지 결정하는 **규칙 기반** 라우터.

## 범위

- 키워드·패턴 규칙으로 도구 선택 (예: 매출/집계/개수 → nl2sql, 장애/문서/방법 → vector_search,
  담당/관계/소속 → knowledge_graph)
- `os_dataset/questions.json` 30문항(도구별 10문항)으로 라우팅 정확도 측정·보고

## 시작점

- **임베딩 유사도 기반 분류 프로토타입**이 이미 있음:
  [`../vector-db/pipeline/router_prototype.py`](../vector-db/pipeline/router_prototype.py)
  — 30문항 76% (nl2sql 8/10, vector_search 6/10, knowledge_graph 9/10).
  규칙으로 판단이 안 되는 질문의 **폴백**으로 결합하는 것을 제안함.
- 각 도구의 용도·적합 질문 유형은 `vector-db/docs/vector-search-contract.md`의
  도구 description 초안 참고.
