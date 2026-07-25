-- ============================================================
-- 벡터 검색 셋업: 차원 조정 + 인덱스 + 검색 함수
-- 데이터셋 스키마(01-schema.sql) 적용 이후 실행됨
-- ============================================================

-- [차원 조정] 데이터셋 원본은 vector(768)이나, 임베딩 모델로 한국어 성능이
-- 검증된 bge-m3(1024차원)를 채택하여 컬럼 차원을 맞춘다. (근거: docs/design.md)
ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1024);

-- [인덱스] HNSW 채택. IVFFlat은 적재된 데이터로 사전 학습(리스트 클러스터링)이
-- 필요해 빈 테이블에 만들 수 없고, 재적재 시 재학습이 필요하다. HNSW는 삽입 시
-- 그래프가 증분 구축되어 "스키마 초기화 → 이후 적재" 흐름과 맞고, 소규모 데이터에서도
-- 재현율(recall)이 IVFFlat보다 안정적이다. (근거: docs/design.md)
CREATE INDEX IF NOT EXISTS idx_doc_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

-- 키워드 축(pg_trgm)용 GIN 인덱스
CREATE INDEX IF NOT EXISTS idx_doc_chunks_content_trgm
    ON document_chunks USING gin (content gin_trgm_ops);

-- 메타데이터 필터(doc_type)용 인덱스
CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc_type
    ON document_chunks ((metadata->>'doc_type'));

-- ============================================================
-- 검색 함수: MCP 서버 담당자는 이 두 함수만 감싸면 된다.
-- 반환 컬럼은 docs/vector-search-contract.md 의 출력 스키마와 1:1 대응.
-- ============================================================

-- 1) 순수 벡터 검색 (코사인 유사도)
CREATE OR REPLACE FUNCTION vector_search(
    query_embedding vector(1024),
    top_k           int  DEFAULT 5,
    filter_doc_type text DEFAULT NULL   -- '장애보고'|'기술문서'|'회의록'|'제안서'
)
RETURNS TABLE (
    content     text,
    doc_title   text,
    doc_type    text,
    similarity  float,
    source_path text,
    chunk_index int
)
LANGUAGE sql STABLE AS $$
    SELECT c.content,
           c.metadata->>'doc_title',
           c.metadata->>'doc_type',
           1 - (c.embedding <=> query_embedding),
           c.metadata->>'source_path',
           c.chunk_index
    FROM document_chunks c
    WHERE filter_doc_type IS NULL OR c.metadata->>'doc_type' = filter_doc_type
    ORDER BY c.embedding <=> query_embedding
    LIMIT LEAST(top_k, 10);
$$;

-- 2) 하이브리드 검색: 벡터(코사인) + 키워드(pg_trgm word_similarity)를
--    RRF(Reciprocal Rank Fusion)로 병합. 시스템명·에러코드 등 정확 키워드
--    질의에서 벡터 검색의 의미 뭉개짐을 보완한다.
--    similarity 컬럼은 해석 가능성을 위해 코사인 유사도(0~1)를 그대로 반환하고,
--    정렬은 RRF 점수로 한다.
CREATE OR REPLACE FUNCTION hybrid_search(
    query_text      text,
    query_embedding vector(1024),
    top_k           int  DEFAULT 5,
    filter_doc_type text DEFAULT NULL,
    rrf_k           int  DEFAULT 60,     -- RRF 표준 상수
    candidate_pool  int  DEFAULT 30      -- 축별 후보 수 (top_k보다 넉넉히)
)
RETURNS TABLE (
    content     text,
    doc_title   text,
    doc_type    text,
    similarity  float,
    source_path text,
    chunk_index int,
    rrf_score   float
)
LANGUAGE sql STABLE AS $$
    WITH vec AS (
        SELECT c.id,
               ROW_NUMBER() OVER (ORDER BY c.embedding <=> query_embedding) AS rank
        FROM document_chunks c
        WHERE filter_doc_type IS NULL OR c.metadata->>'doc_type' = filter_doc_type
        ORDER BY c.embedding <=> query_embedding
        LIMIT candidate_pool
    ),
    kw AS (
        SELECT c.id,
               ROW_NUMBER() OVER (
                   ORDER BY word_similarity(lower(query_text), lower(c.content)) DESC
               ) AS rank
        FROM document_chunks c
        WHERE (filter_doc_type IS NULL OR c.metadata->>'doc_type' = filter_doc_type)
          AND word_similarity(lower(query_text), lower(c.content)) > 0.1
        ORDER BY word_similarity(lower(query_text), lower(c.content)) DESC
        LIMIT candidate_pool
    ),
    fused AS (
        SELECT COALESCE(v.id, k.id) AS id,
               COALESCE(1.0 / (rrf_k + v.rank), 0)
             + COALESCE(1.0 / (rrf_k + k.rank), 0) AS score
        FROM vec v
        FULL OUTER JOIN kw k ON v.id = k.id
    )
    SELECT c.content,
           c.metadata->>'doc_title',
           c.metadata->>'doc_type',
           1 - (c.embedding <=> query_embedding),
           c.metadata->>'source_path',
           c.chunk_index,
           f.score::float
    FROM fused f
    JOIN document_chunks c ON c.id = f.id
    ORDER BY f.score DESC
    LIMIT LEAST(top_k, 10);
$$;
