# 뭘 만들었는지 쉽게 정리 (작업 요약)

> 2026-07-24 작업. `vector-db-instructions.md` 지시서 기반으로 벡터 DB 파트를 전부 구현하고,
> 실제로 끝까지 실행해서 검증까지 마친 상태.

## 한 줄 요약

**"한국어 사내 문서 40건을 AI가 의미로 검색할 수 있게 만드는 시스템"** 을 만들었다.
질문을 던지면 (예: "SSL 인증서 관련 장애 있었어?") 관련 문서 조각을 유사도 순으로 돌려준다.

## 전체 흐름 (딱 3단계)

```
① 준비:  문서 40건을 잘라서(청킹) → 숫자 벡터로 변환(임베딩) → DB에 저장
② 검색:  질문도 벡터로 변환 → DB에서 가장 "의미가 가까운" 조각 찾기
③ 전달:  MCP 서버가 이 검색을 도구로 감싸서 소형 LLM(Gemma 3 4B급)에게 제공
```

## 만든 것들

| 파일 | 하는 일 | 쉽게 말하면 |
|------|---------|-------------|
| `docker-compose.yml` + `initdb/` | PostgreSQL + pgvector DB 자동 구축 | `docker compose up` 한 방이면 DB 완성 |
| `pipeline/chunking.py` | 문서를 검색하기 좋은 크기로 자르기 | 너무 길면 자르고, 너무 짧으면 합침 (300~500토큰) |
| `pipeline/embedding.py` | Ollama bge-m3로 텍스트→벡터 변환 | 문장의 "의미"를 1024개 숫자로 표현 |
| `pipeline/load.py` | 위 둘을 묶어 DB에 적재 | 몇 번을 다시 돌려도 안전(멱등) |
| `pipeline/search.py` | 검색 기능 (벡터 / 하이브리드) | MCP 서버 담당자는 이것만 감싸면 됨 |
| `pipeline/evaluate.py` | 예시 질문 10개로 자체 채점 | 결과는 `evaluation.md`에 자동 저장 |
| `pipeline/router_prototype.py` | (보너스) 질문→도구 자동 분류 실험 | 76% 정확도 |
| `pipeline/mcp_server.py` + `.mcp.json` | (추가) vector_search MCP 서버 최소 구현 | AI가 실제 "도구"로 호출 가능 |
| `docs/vector-search-contract.md` | 팀에 제안하는 MCP 도구 명세서 | 입력·출력 형식 약속 |
| `docs/design.md` | "왜 이렇게 만들었나" 설계 근거 | 평가 대비 핵심 문서 |

## 핵심 결정 3가지 (면접/발표에서 물어볼 만한 것)

1. **임베딩 모델을 bge-m3(1024차원)로 바꾼 이유**
   데이터셋 기본 스키마는 768차원(nomic-embed-text 기준)이었지만, 데이터가 전부
   한국어라서 한국어 성능이 검증된 bge-m3를 골랐다. 원본 데이터셋 파일은 건드리지 않고
   DB 초기화 때 `ALTER TABLE`로 차원만 조정했다.

2. **하이브리드 검색을 만든 이유 (차별화 포인트)**
   벡터 검색은 "의미"는 잘 찾지만 "SSL", "Kubernetes" 같은 정확한 키워드에 약할 수 있다.
   그래서 키워드 검색(pg_trgm)을 추가하고 두 결과를 RRF라는 순위 융합 공식으로 합쳤다.
   한국어는 PostgreSQL 기본 전문검색(tsvector)이 형태소 분석을 못 해서 trigram 방식을 썼다.

3. **소형 LLM을 배려한 설계**
   최종 소비자가 4B~7B급 작은 모델이라 컨텍스트가 좁다. 그래서 청크 최대 500토큰,
   검색 결과 최대 10개(기본 5개)로 상한을 계약과 DB 함수 양쪽에서 강제했다.

## 실행 결과 (실제로 돌려서 확인함)

- DB 구축: 8개 테이블 818행 적재 확인 (departments 6, employees 45, clients 30,
  products 12, contracts 65, projects 40, sales 500, support_tickets 120)
- 문서 적재: 40문서 → 40청크 (평균 220토큰) — 문서가 짧아 대부분 1문서=1청크
- **자체 평가: 벡터·하이브리드 모두 top-3/top-5 적중률 10/10 (100%)**
  예: "SSL 인증서 관련 장애?" → 실제 SSL 장애 보고서 3건(DOC-002/005/006)이 정확히 상위 3위
- 라우터 프로토타입: 30문항 중 23개 정답 (nl2sql 8/10, vector 6/10, graph 9/10)
- MCP 서버: 실제 MCP 클라이언트로 접속해 도구 목록 조회 → 검색 호출 → doc_type 필터 →
  잘못된 top_k 거부까지 전부 동작 확인 (E2E 테스트 통과)

## 직접 돌려보려면

```bash
docker compose up -d --wait      # 1) DB 띄우기
cd pipeline
py -3.12 load.py                 # 2) 문서 적재 (Ollama에 bge-m3 필요)
py -3.12 search.py "백업 정책 알려줘"   # 3) 검색!
```

자세한 순서는 프로젝트 루트의 `README.md` 참고.
