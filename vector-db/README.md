# Company-X 벡터 검색 파트 (PostgreSQL + pgvector)

2026 오픈소스 개발자대회 지정과제 — MCP 기반 지능형 AI 검색 시스템의
**벡터 데이터베이스 파트**: 문서 임베딩·저장·의미 검색.

## 구성

> 모노레포 구조: `docker-compose.yml`(공용 인프라)과 `os_dataset/`(공용 데이터셋)은
> **레포 루트**에 있고, 이 파트의 코드는 전부 `vector-db/` 아래에 있다.

```
<repo-root>/
├── docker-compose.yml          # 공용: PostgreSQL 16 + pgvector
├── os_dataset/                 # 공용: 대회 제공 데이터셋 (git 미포함, 직접 배치)
└── vector-db/
    ├── initdb/                 # DB 초기화 (확장 → 데이터셋 DDL/데이터 → 벡터 셋업)
    │   ├── 00-extensions.sql   #   vector, pg_trgm
    │   └── 03-vector-setup.sql #   1024차원 조정, HNSW 인덱스, 검색 SQL 함수
    ├── pipeline/
    │   ├── config.py           # DSN·모델·청킹 파라미터 (환경변수로 재정의 가능)
    │   ├── chunking.py         # Markdown 청킹 (+ 통계 출력 CLI)
    │   ├── embedding.py        # Ollama /api/embed 클라이언트 (배치·재시도)
    │   ├── load.py             # 적재 파이프라인 (멱등: TRUNCATE 후 재적재)
    │   ├── search.py           # 벡터/하이브리드 검색 API + CLI
    │   ├── evaluate.py         # 10문항 자체 평가 → docs/evaluation.md 생성
    │   ├── router_prototype.py # (선택) 임베딩 유사도 기반 도구 라우터
    │   └── mcp_server.py       # vector_search MCP 서버 (FastMCP, stdio)
    └── docs/
        ├── vector-search-contract.md  # MCP 도구 계약 (팀 인터페이스)
        ├── design.md                  # 설계 근거
        └── evaluation.md              # 평가 결과 (evaluate.py가 생성)
```

Claude Code용 MCP 등록 파일(`.mcp.json`)은 레포 루트에 있다.

## 사전 요구사항

- Docker (Desktop)
- Ollama — 임베딩 모델: `ollama pull bge-m3`
- Python 3.11+ — `pip install -r requirements.txt`
- **대회 제공 데이터셋**: 라이선스(대회 참가 목적 한정) 때문에 저장소에 포함하지 않음.
  `companyx-dataset-v1.0.zip`을 압축 해제해 **레포 루트**에 `os_dataset/` 이름으로 배치할 것:

  ```
  <repo-root>/
  └── os_dataset/
      ├── README.md
      ├── sql/            # 01-schema.sql, 02-data.sql, erd.md
      ├── documents/      # DOC-001.md ~ DOC-040.md, index.json
      ├── graph/          # nodes.json, edges.json, schema.md
      └── questions.json
  ```

## 실행 순서

```bash
# 1. DB 기동 — 레포 루트에서 실행 (초기화 스크립트가 스키마·데이터셋 적재까지 자동 수행)
docker compose up -d --wait

# 2. 적재 확인 (8개 테이블 행 수)
docker exec companyx-db psql -U companyx -d companyx -c \
  "SELECT 'employees' t, count(*) FROM employees UNION ALL SELECT 'sales', count(*) FROM sales;"

# 3. 문서 청킹 → 임베딩 → document_chunks 적재 (재실행 안전)
cd vector-db/pipeline
python load.py          # Windows: py -3.12 load.py (PYTHONUTF8=1 권장)

# 4. 검색 테스트
python search.py "SSL 인증서 관련 장애가 있었어?" --mode hybrid
python search.py "백업 정책 알려줘" --doc-type 기술문서 --top-k 3

# 5. 자체 평가 (10문항, 벡터 vs 하이브리드 → docs/evaluation.md)
python evaluate.py

# 6. (선택) 라우터 프로토타입 정확도 측정 (30문항)
python router_prototype.py
```

## MCP 서버 (vector_search 도구)

`pipeline/mcp_server.py`는 계약(docs/vector-search-contract.md)대로 `vector_search`
도구 하나를 노출하는 최소 MCP 서버다(stdio, FastMCP). 사전 요구사항 추가:
`pip install mcp`, DB 컨테이너와 Ollama 실행 상태.

- **Claude Code**: 레포 루트에 `.mcp.json`이 있어 루트에서 열면 자동 인식됨
- **Claude Desktop**: `claude_desktop_config.json`의 `mcpServers`에 `.mcp.json`과
  동일한 항목(`command: py`, `args: ["-3.12", "<절대경로>/vector-db/pipeline/mcp_server.py"]`)을 추가
- 수동 실행 테스트: 레포 루트에서 `py -3.12 vector-db/pipeline/mcp_server.py` (stdio라 대화형 출력은 없음)

Windows PowerShell에서 한글 출력이 깨지면: `$env:PYTHONUTF8 = "1"` 설정 후 실행.

## 핵심 설계 요약 (상세: [docs/design.md](docs/design.md))

- **임베딩**: Ollama `bge-m3` 1024차원 — 한국어 retrieval 성능 기준 선정.
  원본 스키마의 `vector(768)`은 초기화 스크립트에서 ALTER (데이터셋 파일 무수정)
- **청킹**: 헤딩 분할 → 400토큰 병합 → 500토큰 초과 시 overlap 50토큰 재분할
- **인덱스**: HNSW(cosine) — 멱등 재적재 흐름과 호환(증분 구축) + 높은 recall
- **하이브리드 검색**: 벡터 + pg_trgm 키워드(한국어에 tsvector 형태소 분석이 없어
  trigram 채택)를 RRF(k=60)로 병합 — SSL·제품명 등 정확 키워드 질의 보완
- **MCP 계약**: [docs/vector-search-contract.md](docs/vector-search-contract.md) —
  소형 LLM(4B~7B) 컨텍스트를 고려해 top_k ≤ 10, 청크 ≤ 500토큰 강제
