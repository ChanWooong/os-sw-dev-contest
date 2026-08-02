"""견고성 평가 — 평가셋과 **같은 의도를 다른 말로** 물었을 때도 답이 나오는지 본다.

`evaluate.py`의 10문항은 파서를 만들 때 이미 보고 있던 문제라, 통과해도 일반화
성능을 뜻하지 않는다. 이 스크립트는 그 10문항을 바꿔 말한 질문들로 채점해
"평가셋에 과적합됐는지"를 드러내는 것이 목적이다.

정답은 `evaluate.py`와 같은 방식으로 원본 JSON에서 직접 계산한다.
판정은 3단계다.

- 정확   : 결과 집합이 정답과 완전히 일치
- 과대포함: 정답을 다 담았지만 관계없는 노드가 섞임 (LLM이 걸러낼 여지는 있음)
- 오답   : 정답을 놓쳤거나 엉뚱한 유형을 반환

실행:
    python evaluate_robustness.py
"""
from __future__ import annotations

import collections
import json

from config import EDGES_PATH, NODES_PATH
from tool import knowledge_graph_query

NODES = {n["id"]: n for n in json.loads(NODES_PATH.read_text(encoding="utf-8"))}
EDGES = json.loads(EDGES_PATH.read_text(encoding="utf-8"))
ACTIVE = {"status": "active"}


def _id(name: str) -> str:
    return next(k for k, v in NODES.items() if v["name"] == name)


def _linked(node_id: str, relation: str, *, reverse: bool = False, where: dict | None = None) -> set[str]:
    src, dst = ("target", "source") if reverse else ("source", "target")
    return {
        e[dst] for e in EDGES
        if e["relation"] == relation and e[src] == node_id
        and all((e.get("properties") or {}).get(k) == v for k, v in (where or {}).items())
    }


def _degree_top(relation: str, node_type: str, where: dict | None = None) -> set[str]:
    counts: collections.Counter[str] = collections.Counter()
    for e in EDGES:
        if e["relation"] != relation:
            continue
        if not all((e.get("properties") or {}).get(k) == v for k, v in (where or {}).items()):
            continue
        for endpoint in (e["source"], e["target"]):
            if NODES[endpoint]["type"] == node_type:
                counts[endpoint] += 1
    best = max(counts.values())
    return {nid for nid, cnt in counts.items() if cnt == best}


def _two_hop_same_type(node_id: str, relation: str) -> set[str]:
    """`node_id` → (relation) → 중간 노드 → (relation) → 같은 유형의 다른 노드."""
    mids = {
        e["source"] if e["target"] == node_id else e["target"]
        for e in EDGES
        if e["relation"] == relation and node_id in (e["source"], e["target"])
    }
    far = {
        e["source"] if e["target"] in mids else e["target"]
        for e in EDGES
        if e["relation"] == relation and (e["source"] in mids or e["target"] in mids)
    }
    return {n for n in far if NODES[n]["type"] == NODES[node_id]["type"]} - {node_id}


def _cases() -> list[tuple[str, str, set[str]]]:
    ca, pc1, pd1, ps1 = _id("Client-A"), _id("Product-C1"), _id("Product-D1"), _id("Product-S1")
    cb = _id("Client-B")
    cloud, admin = _id("클라우드사업부"), _id("경영지원팀")

    d1_projects: set[str] = set()
    for client in _linked(pd1, "USES", reverse=True):
        d1_projects |= _linked(client, "HAS_PROJECT")
    leads_in_progress = {
        e["source"] for e in EDGES
        if e["relation"] == "LEADS" and NODES[e["target"]]["properties"].get("status") == "in_progress"
    }

    uses_a = _linked(ca, "USES", where=ACTIVE)
    uses_pc1 = _linked(pc1, "USES", reverse=True, where=ACTIVE)
    cloud_staff = _linked(cloud, "BELONGS_TO", reverse=True)
    admin_head = _linked(admin, "HEAD_IS")

    return [
        # (질문, 판정 방식, 정답)
        ("Client-A는 어떤 제품을 쓰고 있어?", "set", uses_a),
        ("Client-A가 도입한 솔루션 알려줘", "set", uses_a),
        ("Client-A랑 계약된 제품 뭐야?", "set", uses_a),
        ("Product-C1 도입한 회사 어디야?", "set", uses_pc1),
        ("Product-C1 쓰는 데가 어디지?", "set", uses_pc1),
        ("클라우드사업부에 속한 사람들", "set", cloud_staff),
        ("클라우드사업부 인원 알려줘", "set", cloud_staff),
        ("클라우드사업부에서 일하는 직원", "set", cloud_staff),
        ("경영지원팀 리더는?", "set", admin_head),
        ("경영지원팀을 이끄는 사람은?", "set", admin_head),
        ("Product-D1이랑 연결된 프로젝트", "set", d1_projects),
        ("Product-D1 관련 프로젝트 보여줘", "set", d1_projects),
        ("Product-S1에 문제 겪은 고객사", "set", _linked(ps1, "REPORTED_ISSUE", reverse=True)),
        ("Client-B의 프로젝트 목록", "set", _linked(cb, "HAS_PROJECT")),
        # Client-C는 담당자가 없어 기대값이 빈 집합이었다 → 0건 반환으로 자동 통과하는
        # 공허한 문항이라 담당자 5명이 있는 Client-B로 교체했다.
        ("Client-B 담당자 누구야?", "set", _linked(cb, "MANAGES_ACCOUNT", reverse=True)),
        ("진행중인 프로젝트 리드하는 직원", "set", leads_in_progress),
        ("이슈 제일 많은 제품", "top1", _degree_top("REPORTED_ISSUE", "product")),
        ("장애가 가장 잦은 제품은?", "top1", _degree_top("REPORTED_ISSUE", "product")),
        ("고객을 제일 많이 맡은 직원", "top1", _degree_top("MANAGES_ACCOUNT", "employee")),
        ("가장 많은 거래처를 관리하는 사람", "top1", _degree_top("MANAGES_ACCOUNT", "employee")),

        # ── 아래는 코드리뷰에서 나온 결함들의 회귀 방지용 ────────────────────
        # rank도 neighbors와 같은 계약 상태 조건을 써야 한다. 전체 기준으로 세면
        # Client-T 단독 1위지만, 유효 계약만 세면 5개사 공동 1위다.
        ("제품을 가장 많이 쓰는 고객사는?", "top1", _degree_top("USES", "client", where=ACTIVE)),
        # 이름이 여러 노드에 걸리면 임의로 고르지 않고 되물어야 한다.
        ("재원이 담당하는 고객사는?", "error", "ambiguous_entity"),
        # HAS_PROJECT는 관계 키워드가 없어 rank·scan에서 도달할 수 없었다.
        ("프로젝트가 가장 많은 고객사는?", "top1", _degree_top("HAS_PROJECT", "client")),
        # 출발 개체와 같은 유형을 묻는 질문 — 2홉으로 풀려야 한다.
        ("Client-A의 담당자가 맡은 다른 고객사는?", "set", _two_hop_same_type(ca, "MANAGES_ACCOUNT")),
        # 3홉이 필요한 질문은 답할 수 없다. 빈 결과를 조용히 주지 말고 한계를 밝혀야 한다.
        ("경영지원팀 직원이 담당하는 고객사의 프로젝트는?", "limit", None),
    ]


def evaluate() -> None:
    cases = _cases()
    # 기대값이 빈 집합이면 0건 반환으로 자동 통과해 아무것도 검증하지 못한다.
    # 그런 문항이 다시 섞여 들어오지 않도록 여기서 막는다.
    vacuous = [q for q, kind, exp in cases if kind == "set" and not exp]
    assert not vacuous, f"기대값이 빈 집합인 문항: {vacuous}"

    tally: collections.Counter[str] = collections.Counter()
    for question, kind, expected in cases:
        result = knowledge_graph_query(question, top_k=30)
        got = [r["id"] for r in result["results"]]

        if kind == "error":
            grade = "정확" if result.get("error") == expected else "오답"
            note = f"{result.get('error')} / 후보 {result.get('candidates') or result.get('suggestions')}"
        elif kind == "limit":
            # 답할 수 없는 질문 — 빈 결과와 함께 탐색 한계를 밝혀야 통과
            grade = "정확" if not got and result.get("max_hops") else "오답"
            note = f"반환 {len(got)}건 / max_hops={result.get('max_hops')}"
        elif result.get("error"):
            grade, note = "오답", result["error"]
        elif kind == "top1":
            tied = expected
            grade = "정확" if got and got[0] in tied else "오답"
            # 공동 1위는 tied_top으로 알려야 한다
            if grade == "정확" and len(tied) > 1 and len(result.get("tied_top", [])) != len(tied):
                grade, note = "오답", f"공동 1위 {len(tied)}건을 tied_top으로 알리지 않음"
            else:
                note = f"1위={got[0] if got else '없음'}" + (f" (공동 {len(tied)}건)" if len(tied) > 1 else "")
        elif set(got) == expected:
            grade, note = "정확", f"{len(got)}건"
        elif expected and expected <= set(got):
            grade, note = "과대포함", f"정답 {len(expected)}건 + 노이즈 {len(set(got) - expected)}건"
        else:
            grade, note = "오답", f"누락 {len(expected - set(got))}건 / 반환 {len(got)}건"

        tally[grade] += 1
        mark = {"정확": "✅", "과대포함": "△", "오답": "❌"}[grade]
        print(f"{mark} [{grade:4s}] {question}  ({note})")

    total = sum(tally.values())
    hit = tally["정확"] + tally["과대포함"]
    print(f"\n정확 {tally['정확']} · 과대포함 {tally['과대포함']} · 오답 {tally['오답']}")
    print(f"완전 정확 {tally['정확']}/{total} · 정답 포함 {hit}/{total}")


if __name__ == "__main__":
    evaluate()
