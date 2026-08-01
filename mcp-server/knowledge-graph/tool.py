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

from config import DEFAULT_TOP_K, MAX_HOPS, MAX_TOP_K
from graph import EDGE_FILTERABLE, REL_ENDPOINTS, AmbiguousEntity, EntityNotFound, get_graph
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

    # "사용 중인 제품"의 자연스러운 해석은 해지·종료분을 뺀 유효 계약이다. USES 간선의
    # 3분의 1(61건 중 19건)이 cancelled/completed라, 거르지 않으면 지금 쓰지 않는 제품이
    # 섞여 나온다. USES를 명시적으로 물었을 때만 적용한다 — "관련된"처럼 넓은 질문에서는
    # 과거 계약도 관계의 일부다.
    edge_filter = slots.edge_filter
    if edge_filter is None and not slots.all_edges and relation == "USES":
        edge_filter = {"status": "active"}
    elif edge_filter and relation is None:
        # "해지한 제품"처럼 간선 조건만 말한 경우, 그 속성을 가진 관계를 물은 것이다.
        # 관계를 좁히지 않으면 조건이 무의미한 다른 관계(이슈 신고 등)까지 딸려 온다.
        relation = _relation_owning(edge_filter)

    if anchor is not None:
        result = graph.neighbors(
            anchor,
            relation=relation,
            target_type=slots.target_type,
            node_filter=slots.node_filter or None,
            edge_filter=edge_filter,
            top_k=limit,
        )
    elif slots.rank and relation and slots.target_type and endpoints_ok(relation, slots.target_type):
        result = graph.rank(
            relation,
            slots.target_type,
            ascending=slots.rank == "asc",
            edge_filter=edge_filter,
            top_k=limit,
        )
    elif slots.unresolved_term:
        return _entity_not_found(slots.unresolved_term, graph)
    elif relation and slots.target_type and endpoints_ok(relation, slots.target_type):
        result = graph.scan(
            relation,
            slots.target_type,
            far_filter=slots.node_filter or None,
            edge_filter=edge_filter,
            top_k=limit,
        )
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
        if result.get("mode") == "neighbors" and slots.target_type:
            # 3홉 이상 떨어진 답에는 도달할 수 없다. 빈 결과를 "그런 관계가 없다"로
            # 읽으면 LLM이 사실이 아닌 단정을 하므로 탐색 한계를 함께 밝힌다.
            result["max_hops"] = MAX_HOPS
            result["message"] += f" 이 도구는 최대 {MAX_HOPS}홉까지만 탐색합니다."
    return result


def _relation_owning(edge_filter: dict) -> str | None:
    """간선 조건의 속성을 가진 관계가 딱 하나면 그 관계를 돌려준다."""
    owners = {
        rel for rel, props in EDGE_FILTERABLE.items()
        if any(key in props for key in edge_filter)
    }
    return owners.pop() if len(owners) == 1 else None


def _entity_not_found(term: str, graph) -> dict:
    """개체를 특정하지 못한 이유를 구분해 돌려준다.

    이름이 여러 노드에 걸리는 것("재원" → 조재원·서재원·안재원·황재원)과
    아예 없는 것은 다른 상황이다. 뭉뚱그리면 되물을 수 있는 질문까지 막힌다.
    """
    try:
        graph.resolve(term)
    except AmbiguousEntity as exc:
        return _error(
            "ambiguous_entity",
            f"'{term}'에 해당하는 개체가 {len(exc.candidates)}개입니다. 어느 쪽인지 확인이 필요합니다.",
            term=term,
            candidates=exc.candidates,
            hint="후보 중 하나의 전체 이름으로 다시 물어보세요.",
        )
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
