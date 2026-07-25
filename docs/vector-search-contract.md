# `vector_search` MCP 도구 계약 (팀 인터페이스 제안)

> 벡터 DB 파트에서 제안하는 MCP 도구 입출력 명세.
> MCP 서버 담당자는 `pipeline/search.py`의 `hybrid_search()`(권장) 또는
> `vector_search()`를 이 스키마 그대로 감싸면 된다.
> DB 레벨 함수(`initdb/03-vector-setup.sql`의 `vector_search`/`hybrid_search`)의
> 반환 컬럼도 아래 출력 스키마와 1:1 대응한다.

## 도구 이름

`vector_search`

## 도구 description 초안 (라우터/LLM 노출용)

> 사내 비정형 문서(장애보고서, 기술문서, 회의록, 제안서 총 40건)를 의미 기반으로
> 검색합니다. "장애 원인", "설치 방법", "회의에서 논의된 내용", "제안서 요약"처럼
> **문서의 서술 내용**을 묻는 질문에 사용하세요.
> 매출·계약 수·직원 목록 같은 **수치 집계/정형 데이터 질의는 `nl2sql`**,
> "누가 어떤 제품을 담당하나" 같은 **개체 간 관계 탐색은 `knowledge_graph`**를
> 사용하세요. 결과는 관련도 순으로 정렬된 문서 발췌(청크)입니다.

적합한 질문 예: "최근 서버 장애 원인은?", "Product-C1 설치 방법", "백업 정책이 어떻게 되지?"
부적합한 질문 예: "3분기 총 매출은?"(→ nl2sql), "Client-A가 쓰는 제품 목록"(→ knowledge_graph)

## 입력 스키마

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|------|------|:---:|:---:|------|
| `query` | string | ✅ | — | 자연어 검색 질의 (한국어) |
| `top_k` | int | | 5 | 반환할 청크 수. 1~10 (10 초과 값은 10으로 절삭) |
| `doc_type` | enum | | null | 문서 유형 필터: `장애보고` \| `기술문서` \| `회의록` \| `제안서` |

```json
{
  "type": "object",
  "properties": {
    "query": { "type": "string", "description": "자연어 검색 질의" },
    "top_k": { "type": "integer", "default": 5, "minimum": 1, "maximum": 10 },
    "doc_type": {
      "type": "string",
      "enum": ["장애보고", "기술문서", "회의록", "제안서"],
      "description": "문서 유형 필터 (생략 시 전체 검색)"
    }
  },
  "required": ["query"]
}
```

## 출력 스키마 (JSON 배열, 관련도 내림차순)

| 필드 | 타입 | 설명 |
|------|------|------|
| `content` | string | 청크 본문 (문서 제목 헤더 포함, 300~500토큰 이내) |
| `doc_title` | string | 원본 문서 제목 |
| `doc_type` | string | 문서 유형 (`장애보고` 등 위 enum) |
| `similarity` | float | 코사인 유사도 0~1 (높을수록 관련) |
| `source_path` | string | 데이터셋 기준 원본 경로 (예: `documents/DOC-001.md`) |
| `chunk_index` | int | 문서 내 청크 순서 (0부터) |

```json
[
  {
    "content": "# [장애보고] Client-A Product-C1 서비스 장애 (2025-12-27)\n\n## 장애 내용\n...",
    "doc_title": "[장애보고] Client-A Product-C1 서비스 장애 (2025-12-27)",
    "doc_type": "장애보고",
    "similarity": 0.7231,
    "source_path": "documents/DOC-001.md",
    "chunk_index": 0
  }
]
```

## 설계 결정 사항 (소형 LLM 소비자 고려)

- **`top_k` 기본 5, 최대 10**: Gemma 3 4B급 컨텍스트에서 검색 결과가 프롬프트를
  잠식하지 않도록 상한을 도구 계약 수준에서 강제한다 (DB 함수에서도 `LEAST(top_k, 10)`로 이중 방어).
- **청크 자체가 300~500토큰 이하**: top-5 반환 시에도 결과 전체가 약 2천 토큰 이내.
- **`similarity`는 항상 코사인 유사도**: 내부적으로 하이브리드(RRF) 정렬을 쓰더라도
  점수 필드는 해석 가능한 0~1 값을 유지한다. LLM이 임계값 판단에 쓸 수 있다.
- **오류 규약**: `top_k` 범위 초과·잘못된 `doc_type`은 결과 대신 명시적 오류를 반환
  (Python 레벨에서 `ValueError`). 빈 결과는 오류가 아니라 `[]`.

## 구현 매핑

| 계층 | 위치 | 비고 |
|------|------|------|
| SQL 함수 | `initdb/03-vector-setup.sql` — `hybrid_search(query_text, query_embedding, top_k, filter_doc_type)` | 임베딩은 호출자가 전달 |
| Python | `pipeline/search.py` — `hybrid_search(query, top_k, doc_type)` | 질의 임베딩(Ollama) 포함, MCP 서버는 이걸 감싸면 됨 |
| MCP 서버 (참조 구현) | `pipeline/mcp_server.py` — FastMCP, stdio | 이 계약을 그대로 노출하는 최소 구현. MCP 서버 파트 통합 전 검증·데모용 |
