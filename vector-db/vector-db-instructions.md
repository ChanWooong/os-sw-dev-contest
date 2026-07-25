# 벡터 데이터베이스 파트 구현 지시서

> 2026 오픈소스 개발자대회 지정과제 — MCP 기반 지능형 AI 검색 시스템
> 담당 범위: 벡터 데이터베이스 (PostgreSQL + pgvector, 문서 임베딩·저장·의미 검색)
> 평가 기준: **MCP 파이프라인 설계 품질** — 단순 구현이 아니라 설계 근거와 인터페이스 품질이 중요함

---

## 0. 컨텍스트

- 전체 시스템은 4개 컴포넌트로 구성: ① 벡터 DB(이 파트), ② MCP 서버(벡터 검색·NL2SQL·지식 그래프 3종 도구), ③ 규칙 기반 도구 자동 선택 라우터, ④ Ollama 소형 LLM 에이전트 연동
- 최종 소비자는 **Gemma 3 4B ~ Qwen 2.5 KO 7B급 소형 LLM**임. 컨텍스트가 작으므로 검색 결과는 짧고 구조화되어야 함
- 데이터셋: `companyx-dataset-v1.0.zip` (가상 기업 Company-X 운영 데이터)
  - SQL: 8개 테이블, 약 800행 (DDL + INSERT) — NL2SQL용
  - **Markdown 40건: 장애보고·기술문서·회의록·제안서 — 이 파트가 다룰 데이터**
  - JSON: 지식 그래프(133노드, 354관계), 예시 질문 30개(`questions.json`, 도구별 10개)
  - `document_chunks` 테이블이 **빈 상태로** 스키마에 포함되어 있음 → 임베딩·적재는 직접 구현
- 데이터는 한국어. 임베딩 모델은 Ollama로 실행하며 한국어 성능을 반드시 고려할 것

## 1. 인프라: Docker로 PostgreSQL + pgvector 구성

- `pgvector/pgvector:pg16` 이미지 기반 `docker-compose.yml` 작성
  - DB명/계정: `companyx`, 포트 5432, named volume으로 데이터 영속화
  - 초기화 스크립트(`docker-entrypoint-initdb.d/`)에서 `CREATE EXTENSION IF NOT EXISTS vector;` 및 데이터셋 DDL 자동 실행
- 데이터셋 zip 압축 해제 후 **README.md를 먼저 읽고** 테이블 스키마·ERD·`document_chunks` 구조(특히 vector 컬럼 차원)를 파악한 뒤 진행할 것
- SQL 파일(DDL + INSERT) 적재 후 8개 테이블 행 수 검증 쿼리 작성

## 2. 청킹(Chunking) 파이프라인

- 대상: Markdown 40건
- 전략:
  1. Markdown 헤딩(`##`, `###`) 단위 1차 분할
  2. 긴 섹션은 300~500 토큰 수준으로 재분할, 청크 간 overlap 약 50 토큰
  3. 각 청크에 메타데이터 저장: 문서 ID, 문서 유형(장애보고/기술문서/회의록/제안서), 문서 제목, 청크 순서, 원본 파일 경로
- 소형 LLM 컨텍스트를 고려해 청크가 지나치게 길어지지 않도록 할 것
- 청킹 결과 통계(문서별 청크 수, 평균 길이) 출력 스크립트 포함

## 3. 임베딩 및 적재 (Ollama)

- 임베딩 모델: 한국어 성능 기준으로 `bge-m3`(1024차원)를 1순위로 검토. `document_chunks`의 vector 차원과 불일치 시:
  - 스키마 수정이 허용되면 모델 차원에 맞춰 DDL 조정
  - 불가하면 해당 차원에 맞는 다국어 모델로 대체하고 선택 근거를 문서화
- 적재 파이프라인(Python) 구현: Markdown 로드 → 청킹 → Ollama `/api/embed` 호출(배치 처리) → `document_chunks` INSERT
- 멱등성 보장: 재실행 시 중복 적재 방지 (TRUNCATE 후 재적재 또는 upsert)
- 실패한 청크 재시도 로직과 적재 결과 로그 포함

## 4. 인덱스 및 검색 쿼리

- 인덱스: `hnsw (embedding vector_cosine_ops)` 생성. IVFFlat 대비 HNSW 선택 근거를 주석/문서로 남길 것
- 기본 벡터 검색: 코사인 거리 기반 top-k, 유사도 점수(`1 - distance`) 반환
- **하이브리드 검색 구현 (설계 차별화 포인트)**:
  - PostgreSQL full-text search(tsvector) 또는 `pg_trgm` 기반 키워드 검색을 벡터 검색과 결합
  - RRF(Reciprocal Rank Fusion)로 두 결과 병합
  - 목적: 시스템명·에러코드 같은 정확한 키워드 질의에 대한 보완
- 검색 로직은 SQL 함수 또는 단일 Python 함수로 캡슐화하여 MCP 서버 담당자가 바로 감쌀 수 있게 할 것

## 5. MCP 도구 계약(contract) 정의 — 팀 인터페이스

`vector_search` MCP 도구의 입출력 스키마를 이 파트에서 설계해 팀에 제안한다. 다음 형태의 명세 문서(`docs/vector-search-contract.md`)를 작성할 것:

- 입력:
  - `query` (string, 필수)
  - `top_k` (int, 기본 5, 최대 10)
  - `doc_type` (enum: 장애보고 | 기술문서 | 회의록 | 제안서, 선택 — 메타데이터 필터)
- 출력 (JSON 배열):
  - `content` (청크 본문), `doc_title`, `doc_type`, `similarity` (0~1), `source_path`, `chunk_index`
- 도구 description 초안 포함: 라우터/LLM이 "언제 이 도구를 써야 하는지" 판단할 수 있도록 용도·적합 질문 유형을 명확히 기술

## 6. 라우터 기여 (선택 구현, 여유 시)

- 규칙 기반 라우터를 보완하는 **임베딩 유사도 기반 질문 분류** 프로토타입:
  - 도구별 대표 예시 질문을 임베딩해 두고, 입력 질문과의 유사도로 벡터 검색 / NL2SQL / 지식 그래프 라우팅
  - `questions.json` 30문항으로 라우팅 정확도를 측정해 수치로 보고

## 7. 검증 및 평가

- `questions.json`의 벡터 검색용 10문항으로 자체 평가 스크립트 작성:
  - 각 질문에 대해 top-k 검색 결과 출력
  - 관련 문서가 top-3 / top-5 안에 포함되는지 적중률 집계
  - 순수 벡터 검색 vs 하이브리드 검색 성능 비교표 생성
- 평가 결과를 `docs/evaluation.md`에 정리

## 8. 문서화 (평가 대비 필수)

`docs/design.md`에 다음 설계 근거를 정리:

- 청킹 전략과 파라미터 선택 이유
- 임베딩 모델 선택 근거 (한국어 성능, 차원, 속도 비교)
- HNSW 인덱스 선택 근거
- 하이브리드 검색 구조도 (mermaid 다이어그램)
- 소형 LLM 제약을 고려한 응답 설계 결정 사항
- MCP 파이프라인 전체에서 이 파트가 차지하는 위치 다이어그램

## 9. 산출물 체크리스트

- [ ] `docker-compose.yml` + 초기화 스크립트
- [ ] 청킹·임베딩·적재 파이프라인 (Python, 재실행 안전)
- [ ] 벡터 검색 + 하이브리드 검색 함수 (SQL 함수 또는 Python 모듈)
- [ ] `docs/vector-search-contract.md` (MCP 도구 계약)
- [ ] 평가 스크립트 + `docs/evaluation.md` (10문항 적중률, 벡터 vs 하이브리드 비교)
- [ ] `docs/design.md` (설계 근거 문서)
- [ ] `README.md` (실행 방법: docker compose up → 적재 → 검색 테스트 순서)

## 10. 작업 순서

1. 데이터셋 압축 해제 → README/스키마/ERD 확인 → `document_chunks` 차원 확정
2. Docker 인프라 구성 및 데이터셋 적재·검증
3. 청킹 파이프라인 → 임베딩 적재 → 기본 벡터 검색
4. 인덱스 + 하이브리드 검색
5. MCP 도구 계약 문서 → 평가 스크립트 → 설계 문서
6. (여유 시) 라우터 프로토타입