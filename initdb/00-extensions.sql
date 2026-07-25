-- 확장 설치.
-- vector: 임베딩 저장/검색 (데이터셋 스키마에도 있으나 순서 보장을 위해 선행 설치)
-- pg_trgm: 하이브리드 검색의 키워드 축.
--   한국어는 PostgreSQL 기본 tsvector 설정(english/simple)으로 형태소 분석이 되지 않아
--   조사가 붙은 단어를 매칭하지 못한다. trigram은 언어 무관 부분 문자열 매칭이므로
--   "SSL", "Kubernetes", 제품명 같은 정확 키워드 질의 보완에 적합하다.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
