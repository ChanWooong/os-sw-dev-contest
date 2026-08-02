"""지식 그래프 로딩·인덱싱·탐색 엔진.

데이터: `os_dataset/graph/nodes.json`(133노드) · `edges.json`(354관계).
스키마 근거: `os_dataset/graph/schema.md`.

이 모듈은 자연어를 다루지 않는다. 한국어 질문 → 슬롯 변환은 `parser.py`가 맡고,
여기서는 (개체, 관계, 대상 유형) 슬롯을 받아 그래프를 탐색해 평평한 결과를 낸다.
"""
from __future__ import annotations

import difflib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

from config import DEFAULT_TOP_K, EDGES_PATH, MAX_TOP_K, NODES_PATH

# 관계의 (출발 노드 유형, 도착 노드 유형). schema.md의 "관계 유형" 표와 1:1 대응.
REL_ENDPOINTS: dict[str, tuple[str, str]] = {
    "BELONGS_TO": ("employee", "department"),
    "HEAD_IS": ("department", "employee"),
    "USES": ("client", "product"),
    "MANAGES_ACCOUNT": ("employee", "client"),
    "HAS_PROJECT": ("client", "project"),
    "LEADS": ("employee", "project"),
    "REPORTED_ISSUE": ("client", "product"),
}

# 조직 구조를 나타내는 "구조적" 관계가 아니라, 발생한 사건을 나타내는 "이벤트" 관계.
# 다홉 경로의 중간 간선으로 쓰면 "이슈를 신고한 적 있는 고객"까지 경유해 결과가
# 과도하게 넓어지므로, 질문이 이슈를 직접 물을 때만 탐색한다.
EVENT_RELATIONS = frozenset({"REPORTED_ISSUE"})

# 간선 자체가 속성을 갖는 관계. USES는 계약이라 상태가 있고(active/cancelled/completed),
# REPORTED_ISSUE는 티켓이라 심각도가 있다. 노드가 아니라 "관계"의 조건이므로
# 노드 속성 필터(node_filter)와 분리해 다룬다.
EDGE_FILTERABLE: dict[str, frozenset[str]] = {
    "USES": frozenset({"status"}),
    "REPORTED_ISSUE": frozenset({"priority"}),
}

_PRIORITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    name: str
    properties: dict = field(default_factory=dict)

    def brief(self) -> dict:
        """소형 LLM용 평평한 표현 — 속성을 중첩하지 않고 최상위로 펼친다."""
        return {"id": self.id, "name": self.name, "type": self.type, **self.properties}


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    properties: dict = field(default_factory=dict)


class EntityNotFound(LookupError):
    """개체 이름을 그래프에서 찾지 못했을 때. 유사 후보를 함께 전달한다."""

    def __init__(self, term: str, suggestions: list[str]):
        self.term = term
        self.suggestions = suggestions
        super().__init__(f"그래프에서 '{term}'을(를) 찾지 못했습니다.")


class AmbiguousEntity(LookupError):
    """이름이 여러 노드에 걸릴 때.

    임의로 하나를 고르면 "없는 개체는 지어내지 않는다"는 원칙과 모순된다.
    없는 개체는 거부하면서 애매한 개체는 추측하는 셈이기 때문이다.
    후보를 돌려주고 호출자가 되묻게 한다.
    """

    def __init__(self, term: str, candidates: list[str]):
        self.term = term
        self.candidates = candidates
        super().__init__(f"'{term}'에 해당하는 개체가 여럿입니다: {', '.join(candidates)}")


class KnowledgeGraph:
    def __init__(self, nodes: list[Node], edges: list[Edge]) -> None:
        self.nodes = {n.id: n for n in nodes}
        self.edges = edges

        self._by_name: dict[str, Node] = {n.name.lower(): n for n in nodes}
        self._by_type: dict[str, list[Node]] = defaultdict(list)
        for n in nodes:
            self._by_type[n.type].append(n)

        # 무방향 인접 리스트: (이웃 노드 id, 관계, 방향, 간선 속성)
        self._adj: dict[str, list[tuple[str, str, str, dict]]] = defaultdict(list)
        for e in edges:
            self._adj[e.source].append((e.target, e.relation, "out", e.properties))
            self._adj[e.target].append((e.source, e.relation, "in", e.properties))

    # ── 로딩 ────────────────────────────────────────────────────────────────
    @classmethod
    def load(cls) -> KnowledgeGraph:
        raw_nodes = json.loads(NODES_PATH.read_text(encoding="utf-8"))
        raw_edges = json.loads(EDGES_PATH.read_text(encoding="utf-8"))
        nodes = [
            Node(n["id"], n["type"], n["name"], n.get("properties") or {})
            for n in raw_nodes
        ]
        edges = [
            Edge(e["source"], e["target"], e["relation"], e.get("properties") or {})
            for e in raw_edges
        ]
        return cls(nodes, edges)

    # ── 조회 헬퍼 ───────────────────────────────────────────────────────────
    @property
    def node_types(self) -> list[str]:
        return sorted(self._by_type)

    def names_of_type(self, node_type: str) -> list[str]:
        return [n.name for n in self._by_type.get(node_type, [])]

    def all_names(self) -> list[str]:
        return [n.name for n in self.nodes.values()]

    def resolve(self, term: str) -> Node:
        """이름 → 노드. 정확 일치 → 노드 id → 부분 일치 순으로 시도한다."""
        key = term.strip().lower()
        if key in self._by_name:
            return self._by_name[key]
        if key in self.nodes:
            return self.nodes[key]

        partial = [n for k, n in self._by_name.items() if key and key in k]
        if len(partial) == 1:
            return partial[0]
        if partial:
            raise AmbiguousEntity(term, sorted(n.name for n in partial))

        raise EntityNotFound(term, difflib.get_close_matches(term, self.all_names(), n=3, cutoff=0.6))

    # ── 탐색 1: 개체 기준 이웃/경로 ─────────────────────────────────────────
    def neighbors(
        self,
        anchor: Node,
        relation: str | None = None,
        target_type: str | None = None,
        node_filter: dict | None = None,
        edge_filter: dict | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> dict:
        """`anchor`에서 출발해 `target_type` 노드를 찾는다.

        1홉에서 찾으면 거기서 멈추고, 없을 때만 2홉으로 넓힌다
        (예: 제품 → 사용 고객 → 그 고객의 프로젝트).
        """
        hop1, excluded = self._expand(anchor.id, relation, allow_event=True, edge_filter=edge_filter)
        matches = self._select(hop1, target_type, node_filter)
        hops = 1

        if not matches and target_type is not None:
            two_hop, excluded_2 = self._expand_two_hop(anchor, relation, edge_filter)
            matches = self._select(two_hop, target_type, node_filter)
            excluded += excluded_2
            hops = 2

        rows = self._rows(matches, top_k)
        result = {
            "mode": "neighbors",
            "anchor": anchor.brief(),
            "relation": relation,
            "target_type": target_type,
            "hops": hops if rows else 0,
            "count": len(matches),
            "returned": len(rows),
            "truncated": len(matches) > len(rows),
            "results": rows,
        }
        # 조건에 걸러진 관계가 있으면 숨기지 않고 알린다. 예를 들어 "사용 중인 제품"은
        # 해지된 계약을 제외하는데, 몇 건을 뺐는지 모르면 LLM이 "제품이 없다"와
        # "지금 쓰는 게 없을 뿐"을 구분해 설명할 수 없다.
        if edge_filter:
            result["edge_filter"] = edge_filter
            if excluded:
                result["excluded_by_edge_filter"] = excluded
        return result

    def _expand(
        self,
        node_id: str,
        relation: str | None,
        allow_event: bool,
        via: str | None = None,
        edge_filter: dict | None = None,
    ) -> tuple[dict[str, dict], int]:
        """1홉 이웃 수집. 같은 이웃으로 가는 평행 간선은 하나로 합친다.

        `(이웃, 간선 조건에 걸러진 건수)`를 돌려준다.
        """
        found: dict[str, dict] = {}
        excluded = 0
        for neighbor_id, rel, direction, props in self._adj[node_id]:
            if relation is not None and rel != relation:
                continue
            if relation is None and not allow_event and rel in EVENT_RELATIONS:
                continue
            if edge_filter and not _edge_matches(rel, props, edge_filter):
                excluded += 1
                continue
            entry = found.setdefault(
                neighbor_id,
                {"node": self.nodes[neighbor_id], "relation": rel, "direction": direction,
                 "via": via, "link_count": 0, "edges": []},
            )
            entry["link_count"] += 1
            entry["edges"].append((rel, props))
        return found, excluded

    def _expand_two_hop(
        self, anchor: Node, relation: str | None, edge_filter: dict | None = None
    ) -> tuple[dict[str, dict], int]:
        """2홉 탐색. 중간 간선은 구조적 관계만 사용한다(EVENT_RELATIONS 주석 참고)."""
        result: dict[str, dict] = {}
        excluded = 0
        # 1홉은 관계 필터를 걸지 않는다 — 관계 슬롯은 보통 최종 도달 관계를 가리키므로
        # 중간 경유 관계까지 제한하면 경로가 끊긴다.
        mids, hop1_excluded = self._expand(anchor.id, None, allow_event=False, edge_filter=edge_filter)
        excluded += hop1_excluded
        for mid in mids.values():
            mid_node: Node = mid["node"]
            far, far_excluded = self._expand(
                mid_node.id, relation, allow_event=False, via=mid_node.name, edge_filter=edge_filter
            )
            excluded += far_excluded
            for far_id, entry in far.items():
                if far_id == anchor.id or far_id in result:
                    continue
                result[far_id] = entry
        return result, excluded

    # ── 탐색 2: 관계 차수 랭킹 ("가장 많은 ~") ──────────────────────────────
    def rank(
        self,
        relation: str,
        target_type: str,
        ascending: bool = False,
        edge_filter: dict | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> dict:
        """`relation` 간선을 `target_type` 쪽 끝점 기준으로 집계해 순위를 낸다.

        `edge_filter`는 `neighbors`/`scan`과 **같은 조건**이 걸려야 한다. 모드마다
        다르게 적용하면 "사용 중"의 뜻이 질문 형태에 따라 달라진다 — 실제로
        전체 기준 1위는 Client-T 단독이지만 유효 계약만 세면 5개사 공동 1위다.
        """
        counts: dict[str, int] = defaultdict(int)
        distinct: dict[str, set[str]] = defaultdict(set)
        excluded = 0
        for e in self.edges:
            if e.relation != relation:
                continue
            if edge_filter and not _edge_matches(e.relation, e.properties, edge_filter):
                excluded += 1
                continue
            for near, far in ((e.source, e.target), (e.target, e.source)):
                node = self.nodes.get(near)
                if node is not None and node.type == target_type:
                    counts[near] += 1
                    distinct[near].add(far)

        sign = 1 if ascending else -1
        ordered = sorted(counts.items(), key=lambda kv: (sign * kv[1], self.nodes[kv[0]].name))
        rows = [
            {**self.nodes[nid].brief(), "link_count": cnt, "distinct_count": len(distinct[nid])}
            for nid, cnt in ordered[: _clamp(top_k)]
        ]
        result = {
            "mode": "rank",
            "relation": relation,
            "target_type": target_type,
            "order": "asc" if ascending else "desc",
            "count": len(ordered),
            "returned": len(rows),
            "truncated": len(ordered) > len(rows),
            "results": rows,
        }
        # 1위가 여럿이면 명시한다. 소형 LLM이 "가장 많은 것은 A입니다"라고
        # 단정해 버리지 않도록, 공동 1위 사실을 응답에 드러내야 한다.
        if ordered:
            best = ordered[0][1]
            tied = [self.nodes[nid].name for nid, cnt in ordered if cnt == best]
            if len(tied) > 1:
                result["tied_top"] = tied
                result["tied_count"] = best
        if edge_filter:
            result["edge_filter"] = edge_filter
            if excluded:
                result["excluded_by_edge_filter"] = excluded
        return result

    # ── 탐색 3: 개체 없이 관계 전체 훑기 (조건부 목록) ──────────────────────
    def scan(
        self,
        relation: str,
        target_type: str,
        far_filter: dict | None = None,
        edge_filter: dict | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> dict:
        """"진행 중인 프로젝트를 이끄는 직원"처럼 시작 개체 없이
        관계 반대쪽 끝점의 속성으로 거르는 질의."""
        collected: dict[str, dict] = {}
        excluded = 0
        for e in self.edges:
            if e.relation != relation:
                continue
            if edge_filter and not _edge_matches(e.relation, e.properties, edge_filter):
                excluded += 1
                continue
            src, tgt = self.nodes.get(e.source), self.nodes.get(e.target)
            if src is None or tgt is None:
                continue
            if src.type == target_type:
                near, far = src, tgt
            elif tgt.type == target_type:
                near, far = tgt, src
            else:
                continue
            if far_filter and not _matches(far, far_filter):
                continue
            entry = collected.setdefault(
                near.id,
                {"node": near, "relation": relation, "direction": None, "via": far.name,
                 "link_count": 0, "edges": []},
            )
            entry["link_count"] += 1
            entry["edges"].append((relation, e.properties))

        rows = self._rows(collected, top_k)
        result = {
            "mode": "scan",
            "relation": relation,
            "target_type": target_type,
            "filter": far_filter or {},
            "count": len(collected),
            "returned": len(rows),
            "truncated": len(collected) > len(rows),
            "results": rows,
        }
        if edge_filter:
            result["edge_filter"] = edge_filter
            if excluded:
                result["excluded_by_edge_filter"] = excluded
        return result

    # ── 결과 정리 ───────────────────────────────────────────────────────────
    def _select(
        self, candidates: dict[str, dict], target_type: str | None, node_filter: dict | None
    ) -> dict[str, dict]:
        out = {}
        for nid, entry in candidates.items():
            node: Node = entry["node"]
            if target_type is not None and node.type != target_type:
                continue
            if node_filter and not _matches(node, node_filter):
                continue
            out[nid] = entry
        return out

    def _rows(self, matches: dict[str, dict], top_k: int) -> list[dict]:
        ordered = sorted(
            matches.values(), key=lambda m: (-m["link_count"], m["node"].name)
        )
        return [self._row(m) for m in ordered[: _clamp(top_k)]]

    @staticmethod
    def _row(entry: dict) -> dict:
        """노드 속성 + 관계 정보를 한 겹 딕셔너리로 펼친다."""
        node: Node = entry["node"]
        row = node.brief()
        row["relation"] = entry["relation"]
        if entry.get("via"):
            row["via"] = entry["via"]
        if entry["link_count"] > 1:
            row["link_count"] = entry["link_count"]

        # 간선 속성 요약 — 관계별로 의미 있는 값만 고정된 이름으로 올린다
        amounts = [p.get("amount") for _, p in entry["edges"] if p.get("amount") is not None]
        if amounts:
            row["contract_amount"] = sum(amounts)
        statuses = [p.get("status") for _, p in entry["edges"] if p.get("status")]
        if statuses:
            row["contract_status"] = "active" if "active" in statuses else statuses[0]
        priorities = [p.get("priority") for _, p in entry["edges"] if p.get("priority")]
        if priorities:
            row["top_priority"] = max(priorities, key=lambda p: _PRIORITY_RANK.get(p, -1))
            row["issue_count"] = len(priorities)
        return row


def _matches(node: Node, filters: dict) -> bool:
    return all(str(node.properties.get(k, "")).lower() == str(v).lower() for k, v in filters.items())


def _edge_matches(relation: str, props: dict, filters: dict) -> bool:
    """간선 조건 판정. 해당 관계에 없는 속성 조건은 무시한다 —
    예를 들어 계약 상태 조건은 USES에만 걸리고 BELONGS_TO 탐색은 막지 않아야 한다."""
    allowed = EDGE_FILTERABLE.get(relation, frozenset())
    for key, value in filters.items():
        if key not in allowed:
            continue
        if str(props.get(key, "")).lower() != str(value).lower():
            return False
    return True


def _clamp(top_k: int) -> int:
    return max(1, min(int(top_k), MAX_TOP_K))


@lru_cache(maxsize=1)
def get_graph() -> KnowledgeGraph:
    """프로세스당 한 번만 로딩 (133노드/354관계라 전량 메모리 적재가 가장 단순·빠름)."""
    return KnowledgeGraph.load()
