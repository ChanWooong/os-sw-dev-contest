"""라우팅 근거 어휘를 **데이터셋에서 직접 수집**한다.

키워드 목록을 손으로 나열하면 평가셋 30문항에 맞춰 적어 넣기 쉽고, 그러면
정확도가 실력이 아니라 조준 사격이 된다. 그래서 도구를 구분하는 어휘 중
데이터에서 유도할 수 있는 것은 전부 유도한다.

| 어휘 | 출처 | 가리키는 도구 |
|------|------|---------------|
| 개체 이름 | `graph/nodes.json` (133개) | `knowledge_graph` |
| 속성값 | 그래프 노드·간선 속성 (서울·금융·critical …) | `nl2sql` (정형 필터값) |
| 문서 전용어 | `documents/*.md` − 위 둘 | `vector_search` |

"문서 전용어"가 핵심이다. 문서에는 Client-A도 나오고 SSL도 나오는데, 앞의 것은
그래프에도 있고 뒤의 것은 문서에만 있다. 차집합을 취하면 "문서를 봐야만 알 수 있는
낱말"이 남는다. 이게 `vector_search`의 근거가 된다.
"""
from __future__ import annotations

import collections
import json
import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = Path(__file__).resolve().parent.parent.parent / "os_dataset"

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]*|[가-힣]{2,}")

# 문서 전체의 절반 이상에 나오는 낱말은 주제를 가리지 못한다(장애·고객사·제품 …).
# 반대로 한 문서에만 나오는 낱말은 오타·고유값일 수 있어 함께 버린다.
_DOC_FREQ_MIN = 2
_DOC_FREQ_MAX_RATIO = 0.5


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text)}


@lru_cache(maxsize=1)
def _graph() -> tuple[list[dict], list[dict]]:
    nodes = json.loads((DATASET_DIR / "graph" / "nodes.json").read_text(encoding="utf-8"))
    edges = json.loads((DATASET_DIR / "graph" / "edges.json").read_text(encoding="utf-8"))
    return nodes, edges


@lru_cache(maxsize=1)
def entity_names() -> frozenset[str]:
    """그래프 개체 이름. 질문에 이게 있으면 관계 탐색 대상이 특정된다는 뜻이다."""
    nodes, _ = _graph()
    return frozenset(n["name"].lower() for n in nodes)


@lru_cache(maxsize=1)
def attribute_values() -> frozenset[str]:
    """노드·간선 속성값(서울·금융·부장·critical·active …).

    정형 테이블의 필터값과 같은 어휘라 `nl2sql`의 약한 근거가 된다.
    숫자 속성(budget·price·amount)은 값 자체가 어휘 구실을 못 해 제외한다.
    """
    nodes, edges = _graph()
    values: set[str] = set()
    for item in (*nodes, *edges):
        for value in (item.get("properties") or {}).values():
            if isinstance(value, str) and len(value) >= 2:
                values.add(value.lower())
    return frozenset(values)


@lru_cache(maxsize=1)
def document_terms() -> frozenset[str]:
    """문서에만 나오는 낱말 (SSL·쿠버네티스·백업·튜닝 …).

    개체 이름과 속성값을 빼고 나면 "문서를 읽어야 알 수 있는" 어휘가 남는다.
    """
    doc_dir = DATASET_DIR / "documents"
    per_doc = [_tokens(p.read_text(encoding="utf-8")) for p in sorted(doc_dir.glob("*.md"))]
    freq: collections.Counter[str] = collections.Counter()
    for tokens in per_doc:
        freq.update(tokens)

    ceiling = len(per_doc) * _DOC_FREQ_MAX_RATIO
    # 개체 이름은 통째로도, 조각으로도 뺀다 ("Client-A" → "client", "a")
    entity_fragments = {frag for name in entity_names() for frag in _tokens(name)}
    excluded = entity_names() | entity_fragments | attribute_values()

    return frozenset(
        term
        for term, count in freq.items()
        if _DOC_FREQ_MIN <= count <= ceiling and term not in excluded
    )


def summary() -> dict[str, int]:
    return {
        "entity_names": len(entity_names()),
        "attribute_values": len(attribute_values()),
        "document_terms": len(document_terms()),
    }


if __name__ == "__main__":
    print(summary())
    docs = document_terms()
    for probe in ("ssl", "kubernetes", "백업", "튜닝", "마이그레이션", "인증서", "client-a", "서울"):
        print(f"  {probe:14s} 문서전용어? {probe in docs}")
