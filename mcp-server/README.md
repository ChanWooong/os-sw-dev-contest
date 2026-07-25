# ② MCP 서버 파트 (작업 예정)

소형 LLM 에이전트에게 3종 도구를 노출하는 MCP 서버.

## 범위

| 도구 | 데이터 소스 | 비고 |
|------|-------------|------|
| `vector_search` | `document_chunks` (벡터 DB 파트) | **계약 확정됨** → [`../vector-db/docs/vector-search-contract.md`](../vector-db/docs/vector-search-contract.md) |
| `nl2sql` | 정형 8개 테이블 (`os_dataset/sql/`) | 자연어 → SQL 생성·실행. 스키마는 `os_dataset/sql/erd.md` 참고 |
| `knowledge_graph` | `os_dataset/graph/` (133노드, 354관계) | 개체 간 관계 탐색. 스키마는 `graph/schema.md` 참고 |

## 시작점

- `vector_search`는 **감쌀 함수가 이미 준비되어 있음**:
  `vector-db/pipeline/search.py`의 `hybrid_search(query, top_k, doc_type)` 호출 → 그대로 반환.
  FastMCP 기반 단일 도구 참조 구현이 `vector-db/pipeline/mcp_server.py`에 있으니
  3종 도구 서버를 만들 때 골격으로 사용 가능.
- DB 접속 정보: `host=localhost port=5432 dbname=companyx user=companyx password=companyx`
  (레포 루트 `docker compose up -d` 후 사용 가능, `COMPANYX_DSN` 환경변수로 재정의)
- 소형 LLM 소비자 제약(결과 총량 상한 등)은 계약 문서의 "설계 결정 사항" 섹션 참고.

## 평가

`os_dataset/questions.json`의 도구별 10문항으로 각 도구를 검증할 것.
vector_search 10문항의 정답 문서 매핑은 `vector-db/pipeline/evaluate.py`에 있음.
