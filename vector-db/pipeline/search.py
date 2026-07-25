"""검색 API — MCP 서버 담당자가 이 모듈의 vector_search / hybrid_search 를
그대로 감싸면 된다. 입출력은 docs/vector-search-contract.md 와 1:1 대응.

CLI:
    py -3.12 search.py "질문" [--top-k 5] [--doc-type 장애보고] [--mode vector|hybrid]
"""
from __future__ import annotations

import argparse
import json

import psycopg

from config import DB_DSN
from embedding import embed_query

VALID_DOC_TYPES = {"장애보고", "기술문서", "회의록", "제안서"}


def _validate(top_k: int, doc_type: str | None) -> None:
    if not 1 <= top_k <= 10:
        raise ValueError(f"top_k는 1~10 사이여야 합니다: {top_k}")
    if doc_type is not None and doc_type not in VALID_DOC_TYPES:
        raise ValueError(f"doc_type은 {VALID_DOC_TYPES} 중 하나여야 합니다: {doc_type}")


def vector_search(query: str, top_k: int = 5, doc_type: str | None = None) -> list[dict]:
    """순수 벡터 검색 (코사인 유사도 top-k)."""
    _validate(top_k, doc_type)
    embedding = embed_query(query)
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM vector_search(%s::vector, %s, %s)",
            (json.dumps(embedding), top_k, doc_type),
        )
        rows = cur.fetchall()
    return [
        {
            "content": r[0],
            "doc_title": r[1],
            "doc_type": r[2],
            "similarity": round(r[3], 4),
            "source_path": r[4],
            "chunk_index": r[5],
        }
        for r in rows
    ]


def hybrid_search(query: str, top_k: int = 5, doc_type: str | None = None) -> list[dict]:
    """하이브리드 검색 (벡터 + pg_trgm 키워드, RRF 병합)."""
    _validate(top_k, doc_type)
    embedding = embed_query(query)
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM hybrid_search(%s, %s::vector, %s, %s)",
            (query, json.dumps(embedding), top_k, doc_type),
        )
        rows = cur.fetchall()
    return [
        {
            "content": r[0],
            "doc_title": r[1],
            "doc_type": r[2],
            "similarity": round(r[3], 4),
            "source_path": r[4],
            "chunk_index": r[5],
        }
        for r in rows
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="문서 의미 검색")
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--doc-type", choices=sorted(VALID_DOC_TYPES), default=None)
    parser.add_argument("--mode", choices=["vector", "hybrid"], default="hybrid")
    args = parser.parse_args()

    fn = hybrid_search if args.mode == "hybrid" else vector_search
    results = fn(args.query, top_k=args.top_k, doc_type=args.doc_type)
    print(json.dumps(results, ensure_ascii=False, indent=2))
