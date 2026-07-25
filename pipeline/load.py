"""적재 파이프라인: Markdown 로드 → 청킹 → 임베딩 → document_chunks INSERT.

멱등성: 매 실행마다 TRUNCATE 후 전체 재적재. 문서 40건/수백 청크 규모라
증분 upsert보다 전체 재적재가 단순하고 상태 꼬임이 없다.
"""
from __future__ import annotations

import json
import sys

import psycopg

from chunking import chunk_all, print_stats
from config import DB_DSN
from embedding import embed_all


def main() -> None:
    print("=== 1. 청킹 ===")
    chunks = chunk_all()
    print_stats(chunks)

    print("\n=== 2. 임베딩 (Ollama) ===")
    embeddings = embed_all([c.content for c in chunks])

    print("\n=== 3. 적재 ===")
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE document_chunks RESTART IDENTITY")
            cur.executemany(
                """
                INSERT INTO document_chunks (doc_id, chunk_index, content, embedding, metadata)
                VALUES (%s, %s, %s, %s::vector, %s)
                """,
                [
                    (
                        c.doc_id,
                        c.chunk_index,
                        c.content,
                        json.dumps(emb),
                        json.dumps(c.metadata, ensure_ascii=False),
                    )
                    for c, emb in zip(chunks, embeddings, strict=True)
                ],
            )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT count(*), count(DISTINCT doc_id) FROM document_chunks")
            n_chunks, n_docs = cur.fetchone()
    print(f"적재 완료: 문서 {n_docs}건, 청크 {n_chunks}건")
    if n_chunks != len(chunks):
        print(f"경고: 적재 수({n_chunks})가 청킹 수({len(chunks)})와 다릅니다", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
