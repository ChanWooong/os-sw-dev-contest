"""`knowledge_graph` MCP 서버 (FastMCP · stdio).

실행:
    python server.py

전제 조건 없음 — 그래프는 `os_dataset/graph/*.json`을 메모리에 올려 쓰므로
DB 컨테이너도 Ollama도 필요하지 않다.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from config import DEFAULT_TOP_K
from tool import knowledge_graph_query

mcp = FastMCP("companyx-knowledge-graph")


@mcp.tool()
def knowledge_graph(query: str, top_k: int = DEFAULT_TOP_K) -> dict:
    """사내 지식 그래프(고객사 30·제품 12·직원 45·프로젝트 40·부서 6, 관계 354건)에서
    개체 사이의 관계를 탐색합니다. "누가 어떤 제품을 담당하나", "어느 고객사가 이 제품을
    쓰나", "이 부서 소속 직원은 누구인가"처럼 **개체와 개체의 연결**을 묻는 질문에 사용하세요.

    매출·계약 금액 같은 수치 집계는 nl2sql, 장애 원인·설치 방법처럼 문서의 서술 내용을
    묻는 질문은 vector_search를 사용하세요.

    응답은 평평한 JSON입니다. `results`의 각 항목은 id·name·type과 해당 노드의 속성,
    도달 관계(relation), 2홉일 때 경유 노드(via)를 가집니다. 개체를 찾지 못하면
    결과를 지어내지 않고 `error: "entity_not_found"`를 돌려줍니다.

    Args:
        query: 자연어 질문 (한국어). 예: "Client-A가 사용 중인 제품 목록은?"
        top_k: 반환할 최대 관계 수 (기본 10, 최대 30)
    """
    return knowledge_graph_query(query, top_k)


if __name__ == "__main__":
    mcp.run()
