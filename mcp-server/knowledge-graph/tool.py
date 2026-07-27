"""knowledge_graph 도구의 진입점 — 질문 한 줄을 받아 평평한 JSON을 돌려준다.

`parser.parse()`로 슬롯을 뽑고, 슬롯 조합에 따라 `graph.py`의 세 가지 탐색 중
하나를 고른다.

| 조건 | 모드 | 예시 질문 |
|------|------|-----------|
| 출발 개체가 그래프에 있음 | `neighbors` | "Client-A가 사용 중인 제품 목록은?" |
| 개체 없이 "가장 많은/적은" | `rank` | "기술 지원 이슈가 가장 많은 제품은?" |
| 개체 없이 관계 + 조건 | `scan` | "진행 중인 프로젝트를 이끄는 직원 목록" |
"""
from __future__ import annotations

from config import DEFAULT_TOP_K, MAX_TOP_K
from graph import REL_ENDPOINTS, EntityNotFound, get_graph
from parser import endpoints_ok, parse


def knowledge_graph_query(question: str, top_k: int = DEFAULT_TOP_K) -> dict:
    if not question or not question.strip():
        return _error("empty_query", "질문이 비어 있습니다.", hint="예: 'Client-A가 사용 중인 제품 목록은?'")

    graph = get_graph()
    slots, anchor = parse(question, graph)
    limit = max(1, min(int(slots.top_k or top_k), MAX_TOP_K))

    # 관계와 대상 유형이 어긋나면(예: LEADS + product) 관계 쪽을 버리고 탐색으로 넘긴다
    relation = slots.relation
    if relation and not endpoints_ok(relation, slots.target_type) and anchor is not None:
        if not endpoints_ok(relation, anchor.type):
            relation = None

    if anchor is not None:
        result = graph.neighbors(
            anchor,
            relation=relation,
            target_type=slots.target_type,
            node_filter=slots.node_filter or None,
            top_k=limit,
        )
    elif slots.rank and relation and slots.target_type and endpoints_ok(relation, slots.target_type):
        result = graph.rank(relation, slots.target_type, ascending=slots.rank == "asc", top_k=limit)
    elif slots.unresolved_term:
        return _entity_not_found(slots.unresolved_term, graph)
    elif relation and slots.target_type and endpoints_ok(relation, slots.target_type):
        result = graph.scan(relation, slots.target_type, far_filter=slots.node_filter or None, top_k=limit)
    else:
        return _error(
            "unsupported_query",
            "질문에서 탐색 대상을 찾지 못했습니다.",
            hint="고객사·제품·직원·프로젝트·부서 이름을 하나 포함하거나, "
                 "'가장 많은 ~' 처럼 집계 대상을 명시해 주세요.",
            relations=sorted(REL_ENDPOINTS),
        )

    result["question"] = question
    if not result["results"]:
        result["message"] = "조건에 맞는 관계를 찾지 못했습니다."
    return result


def _entity_not_found(term: str, graph) -> dict:
    try:
        graph.resolve(term)
    except EntityNotFound as exc:
        suggestions = exc.suggestions
    else:
        suggestions = []
    return _error(
        "entity_not_found",
        f"그래프에 '{term}' 개체가 없습니다.",
        term=term,
        suggestions=suggestions,
        hint="이 그래프의 고객사·제품 이름은 'Client-A', 'Product-C1' 형식입니다.",
    )


def _error(code: str, message: str, **extra) -> dict:
    return {"error": code, "message": message, "results": [], "count": 0, **extra}


if __name__ == "__main__":  # CLI 확인용
    import argparse
    import json

    ap = argparse.ArgumentParser(description="지식 그래프 관계 탐색")
    ap.add_argument("query")
    ap.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    args = ap.parse_args()
    print(json.dumps(knowledge_graph_query(args.query, args.top_k), ensure_ascii=False, indent=2))
