"""knowledge_graph 도구 자체 평가 — `questions.json`의 그래프 질의 10문항.

정답셋은 `graph.py`를 거치지 않고 `nodes.json`/`edges.json`에서 직접 계산한다.
도구와 같은 코드로 정답을 만들면 검증이 아니라 동어반복이 되기 때문이다.
정답의 근거는 `questions.json`의 `hint` 필드(대회 제공)와 `graph/schema.md`.

실행:
    python evaluate.py            # 결과 출력 + docs/evaluation.md 갱신
"""
from __future__ import annotations

import datetime
import json
from collections import Counter

from config import DATASET_DIR, EDGES_PATH, NODES_PATH, TOOL_ROOT
from tool import knowledge_graph_query

NODES = {n["id"]: n for n in json.loads(NODES_PATH.read_text(encoding="utf-8"))}
EDGES = json.loads(EDGES_PATH.read_text(encoding="utf-8"))

ACTIVE = {"status": "active"}   # 유효 계약만 — USES 간선 조건


def _id_of(name: str) -> str:
    return next(n["id"] for n in NODES.values() if n["name"] == name)


def _linked(
    node_id: str, relation: str, *, reverse: bool = False, where: dict | None = None
) -> set[str]:
    """`node_id`에 `relation`으로 직접 연결된 반대쪽 노드 id 집합.

    `where`로 간선 속성 조건을 걸 수 있다 — "사용 중인 제품"은 유효 계약(active)만
    세야 하므로, 계약 상태를 무시하면 정답셋 자체가 틀린다.
    """
    src, dst = ("target", "source") if reverse else ("source", "target")
    return {
        e[dst]
        for e in EDGES
        if e["relation"] == relation
        and e[src] == node_id
        and all((e.get("properties") or {}).get(k) == v for k, v in (where or {}).items())
    }


def _degree_top(relation: str, node_type: str) -> set[str]:
    """`relation` 간선을 `node_type` 쪽 끝점 기준으로 세어 1위 노드 id 집합.

    동점이면 여러 개가 나온다 (실제로 MANAGES_ACCOUNT는 4건으로 3명이 공동 1위).
    그런 문항은 유일 정답이 없으므로 동점자 중 하나면 통과로 본다.
    """
    counts: Counter[str] = Counter()
    for e in EDGES:
        if e["relation"] != relation:
            continue
        for endpoint in (e["source"], e["target"]):
            if NODES[endpoint]["type"] == node_type:
                counts[endpoint] += 1
    best = max(counts.values())
    return {nid for nid, cnt in counts.items() if cnt == best}


def _expected() -> dict[str, dict]:
    """질문 → 기대 결과. kind='set'이면 id 집합 일치, 'top1'이면 1위 일치, 'error'면 오류 코드."""
    client_a, product_c1 = _id_of("Client-A"), _id_of("Product-C1")
    product_d1, product_s1 = _id_of("Product-D1"), _id_of("Product-S1")
    cloud_dept, admin_dept = _id_of("클라우드사업부"), _id_of("경영지원팀")

    # Product-D1을 쓰는 고객사들의 프로젝트 (2홉)
    d1_projects: set[str] = set()
    for client in _linked(product_d1, "USES", reverse=True):
        d1_projects |= _linked(client, "HAS_PROJECT")

    # 진행 중인 프로젝트를 이끄는 직원
    leads_in_progress = {
        e["source"]
        for e in EDGES
        if e["relation"] == "LEADS" and NODES[e["target"]]["properties"].get("status") == "in_progress"
    }

    return {
        # "사용 중"이므로 해지·종료된 계약은 제외한다. Product-C1은 6개 고객사와
        # USES 간선이 있지만 그중 Client-T는 completed라 실제 정답은 5개다.
        "Client-A가 사용 중인 제품 목록은?":
            {"kind": "set", "ids": _linked(client_a, "USES", where=ACTIVE)},
        "Product-C1을 사용하는 고객사는 어디야?":
            {"kind": "set", "ids": _linked(product_c1, "USES", reverse=True, where=ACTIVE)},
        "클라우드사업부 소속 직원들은 누구야?": {"kind": "set", "ids": _linked(cloud_dept, "BELONGS_TO", reverse=True)},
        # 데이터셋 힌트는 client_2를 가리키지만 '서울물산'이라는 이름의 노드는 그래프에 없다.
        # 없는 개체를 지어내지 않고 명시적 오류를 내는 것이 올바른 동작이다.
        "서울물산 담당 엔지니어는 누구야?": {"kind": "error", "code": "entity_not_found"},
        "Product-D1 제품과 관련된 프로젝트는?": {"kind": "set", "ids": d1_projects},
        "기술 지원 이슈가 가장 많은 제품은?": {"kind": "top1", "ids": _degree_top("REPORTED_ISSUE", "product")},
        "경영지원팀 팀장은 누구야?": {"kind": "set", "ids": _linked(admin_dept, "HEAD_IS")},
        "진행 중인 프로젝트를 이끄는 직원 목록": {"kind": "set", "ids": leads_in_progress},
        "Product-S1 관련 고객 이슈 현황은?": {"kind": "set", "ids": _linked(product_s1, "REPORTED_ISSUE", reverse=True)},
        "가장 많은 고객을 담당하는 직원은?": {"kind": "top1", "ids": _degree_top("MANAGES_ACCOUNT", "employee")},
    }


def _check(result: dict, expected: dict) -> tuple[bool, str]:
    got = [r["id"] for r in result.get("results", [])]
    if expected["kind"] == "error":
        ok = result.get("error") == expected["code"]
        return ok, f"error={result.get('error')}"
    if result.get("error"):
        return False, f"예기치 않은 오류: {result['error']}"
    if expected["kind"] == "top1":
        tied = expected["ids"]
        ok = bool(got) and got[0] in tied
        # 공동 1위인 문항은 도구가 그 사실을 응답에 표시해야 통과
        if ok and len(tied) > 1 and len(result.get("tied_top", [])) != len(tied):
            return False, f"공동 1위 {len(tied)}명을 tied_top으로 알리지 않음"
        note = f" (공동 1위 {len(tied)}명)" if len(tied) > 1 else ""
        return ok, f"1위={got[0] if got else '-'}{note}"
    ok = set(got) == expected["ids"]
    missing, extra = expected["ids"] - set(got), set(got) - expected["ids"]
    detail = f"{len(got)}건 일치" if ok else f"누락{sorted(missing)} 초과{sorted(extra)}"
    return ok, detail


def evaluate() -> list[dict]:
    questions = [
        q["q"]
        for q in json.loads((DATASET_DIR / "questions.json").read_text(encoding="utf-8"))
        if q["tool"] == "knowledge_graph"
    ]
    expected = _expected()
    assert set(questions) == set(expected), "questions.json과 정답셋 불일치"

    rows = []
    for q in questions:
        # 집합 비교이므로 상한에 잘리지 않도록 최대치로 조회한다
        result = knowledge_graph_query(q, top_k=30)
        ok, detail = _check(result, expected[q])
        rows.append({"q": q, "ok": ok, "detail": detail,
                     "mode": result.get("error") or result.get("mode", "-"),
                     "count": result.get("count", 0)})
        print(f"[{'PASS' if ok else 'FAIL'}] {q}\n        {result.get('error') or result.get('mode')} · {detail}")

    passed = sum(r["ok"] for r in rows)
    print(f"\n정확도: {passed}/{len(rows)}")
    _write_report(rows, passed)
    return rows


def _write_report(rows: list[dict], passed: int) -> None:
    modes = Counter(r["mode"] for r in rows)
    lines = [
        "# knowledge_graph 자체 평가 결과",
        "",
        f"> 생성일: {datetime.date.today().isoformat()} · `evaluate.py` 실행 결과",
        "> 평가셋: `os_dataset/questions.json`의 knowledge_graph 10문항",
        "> 정답은 `nodes.json`/`edges.json`에서 도구와 **독립적으로** 재계산해 비교했다.",
        "",
        f"## 요약: {passed}/{len(rows)} 통과",
        "",
        "| 지표 | 값 |",
        "|------|-----|",
        f"| 정확도 | {passed}/{len(rows)} ({passed * 100 // len(rows)}%) |",
        f"| 모드 분포 | {', '.join(f'{k} {v}건' for k, v in sorted(modes.items()))} |",
        "",
        "판정 기준: 목록형은 결과 노드 id 집합이 정답과 **완전 일치**해야 통과",
        "(부분 일치는 실패). 랭킹형은 1위 노드가 일치해야 통과. 오류형은 오류 코드가 일치해야 통과.",
        "",
        "## 문항별 결과",
        "",
        "| # | 질문 | 모드 | 결과 수 | 판정 | 비고 |",
        "|:-:|------|------|:------:|:----:|------|",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r['q']} | `{r['mode']}` | {r['count']} | "
            f"{'✅' if r['ok'] else '❌'} | {r['detail']} |"
        )
    lines += [
        "",
        "## 참고: 4번 문항에 대하여",
        "",
        "`questions.json`의 힌트는 \"서울물산\"을 `client_2`로 매핑하지만, 배포된 그래프 데이터의",
        "고객사 이름은 `Client-A`~`Client-AD` 형식뿐이라 \"서울물산\"이라는 노드는 존재하지 않는다.",
        "따라서 이 도구는 임의의 노드를 추측해 반환하지 않고 `entity_not_found` 오류와 함께",
        "이름 형식 안내를 돌려준다. 소형 LLM이 없는 사실을 지어내는 것을 막기 위한 의도된 동작이다.",
        "",
    ]
    out_dir = TOOL_ROOT / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"리포트 저장: {out_dir / 'evaluation.md'}")


if __name__ == "__main__":
    evaluate()
