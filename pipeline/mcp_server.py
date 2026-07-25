"""`vector_search` MCP 서버 — 최소 구현 (벡터 DB 파트 범위).

docs/vector-search-contract.md 의 계약을 그대로 노출한다.
내부적으로 하이브리드 검색(벡터 + pg_trgm 키워드, RRF 병합)을 사용한다.

실행 (stdio):
    py -3.12 pipeline/mcp_server.py

Claude Code 등록: 프로젝트 루트의 .mcp.json 참고.
전제: DB 컨테이너(docker compose up -d)와 Ollama(bge-m3)가 떠 있어야 한다.
"""
from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

import search

mcp = FastMCP("companyx-vector-search")


@mcp.tool()
def vector_search(
    query: str,
    top_k: int = 5,
    doc_type: Literal["장애보고", "기술문서", "회의록", "제안서"] | None = None,
) -> list[dict]:
    """사내 비정형 문서(장애보고서, 기술문서, 회의록, 제안서 총 40건)를 의미 기반으로
    검색합니다. "장애 원인", "설치 방법", "회의에서 논의된 내용", "제안서 요약"처럼
    문서의 서술 내용을 묻는 질문에 사용하세요.
    매출·계약 수·직원 목록 같은 수치 집계/정형 데이터 질의는 nl2sql,
    "누가 어떤 제품을 담당하나" 같은 개체 간 관계 탐색은 knowledge_graph를 사용하세요.
    결과는 관련도 순으로 정렬된 문서 발췌(청크) 배열이며, 각 항목은
    content, doc_title, doc_type, similarity(0~1), source_path, chunk_index 필드를 가집니다.

    Args:
        query: 자연어 검색 질의 (한국어)
        top_k: 반환할 청크 수 (기본 5, 최대 10)
        doc_type: 문서 유형 필터 (생략 시 전체 검색)
    """
    return search.hybrid_search(query, top_k=top_k, doc_type=doc_type)


if __name__ == "__main__":
    mcp.run()
