"""한국어 질문 → 그래프 탐색 슬롯 변환기.

LLM을 쓰지 않는 결정적(deterministic) 파서다. 최종 소비자가 4B~7B급 소형 LLM이라
슬롯 추출까지 모델에 맡기면 환각·형식 오류 위험이 크고, 도구 응답이 질문마다
달라지면 라우터·평가가 불가능해진다. 같은 질문은 항상 같은 슬롯을 낸다.

추출 슬롯: (개체, 관계, 대상 유형, 속성 필터, 랭킹 여부).
매칭된 구간은 순차적으로 공백 마스킹해서 뒤 단계가 같은 글자를 재사용하지 않게 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from graph import REL_ENDPOINTS, KnowledgeGraph, Node

# ── 관계 키워드 ─────────────────────────────────────────────────────────────
# `(후보 관계들, 키워드들)`. 표 순서가 곧 우선순위 — 구체적 표현("팀장")을
# 넓은 표현("담당")보다 앞에 둔다.
#
# 후보가 여럿인 항목은 맥락에 따라 관계가 갈리는 표현이다. "이끄는"은 부서를 이끌면
# HEAD_IS, 프로젝트를 이끌면 LEADS, 고객을 맡으면 MANAGES_ACCOUNT다. 최종 선택은
# 출발 개체·대상 유형과 대조하는 `_resolve_relation()`이 한다.
RELATION_KEYWORDS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("HEAD_IS",), ("팀장", "부서장", "본부장", "수장", "책임자")),
    (("BELONGS_TO",), ("소속", "속한", "속해", "일하는", "근무", "재직", "몸담")),
    (("HEAD_IS", "LEADS"), ("리더",)),
    (("LEADS", "MANAGES_ACCOUNT", "HEAD_IS"),
     ("이끄는", "이끌", "리드", "총괄", "맡고 있는", "맡은", "맡는")),
    (("MANAGES_ACCOUNT",), ("담당", "관리하는", "어카운트")),
    (("REPORTED_ISSUE",),
     ("기술 지원", "기술지원", "이슈", "장애", "클레임", "불만", "고장", "문제")),
    (("USES",), ("사용", "쓰는", "쓰고", "쓰던", "이용", "도입", "계약", "구독")),
]

# ── 노드 유형 키워드 ────────────────────────────────────────────────────────
TYPE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("employee", ("엔지니어", "담당자", "직원", "사원", "임직원", "사람", "인원", "멤버", "누구")),
    ("product", ("제품", "솔루션", "상품")),
    ("client", ("고객사", "고객", "거래처", "회사")),
    ("project", ("프로젝트",)),
    ("department", ("부서", "팀")),
]

# ── 랭킹 트리거 ─────────────────────────────────────────────────────────────
RANK_DESC = ("가장 많은", "가장 많이", "가장 많게", "제일 많은", "제일 많이", "가장 잦은",
             "제일 잦은", "가장 자주", "가장 높은", "제일 높은", "가장 큰", "제일 큰",
             "최다", "최고", "많은 순", "높은 순")
RANK_ASC = ("가장 적은", "가장 적게", "제일 적은", "제일 적게", "가장 작은", "제일 작은",
            "가장 낮은", "제일 낮은", "가장 드문", "최소", "적은 순", "낮은 순")

# ── 간선(계약) 상태 표현 ────────────────────────────────────────────────────
# USES 간선은 계약이라 상태를 갖는다. 노드 속성값과 겹치지 않는 낱말만 골랐다 —
# "완료/종료"는 프로젝트 상태와 충돌하므로 여기 넣지 않는다.
CONTRACT_STATUS_WORDS: dict[str, str] = {
    "해지": "cancelled", "해약": "cancelled", "취소": "cancelled", "만료": "completed",
}
# 상태를 가리지 말라는 표현 — 해지분까지 포함해 보고 싶을 때
ALL_EDGES_WORDS = ("전체", "모든", "이력", "과거", "역대", "지금까지")

# ── 영문 속성값의 한국어 별칭 ───────────────────────────────────────────────
# 그래프 속성값이 한국어인 것(region "서울", position "부장", industry "금융" 등)은
# 아래 표 없이 데이터에서 자동으로 수집한다. 영문 값만 별칭을 명시한다.
VALUE_ALIASES: dict[str, str] = {
    "진행 중": "in_progress", "진행중": "in_progress",
    "계획": "planning", "기획": "planning",
    "보류": "on_hold", "중단": "on_hold",
    "완료": "completed", "종료": "completed",
    "활성": "active", "베타": "beta",
    "대기업": "enterprise", "중견": "mid", "스타트업": "startup",
    "보안": "security", "클라우드": "cloud", "데이터": "data", "컨설팅": "consulting",
}

# 남은 토큰이 "못 찾은 개체 이름"인지 판정할 때 무시할 일반어.
STOPWORDS = frozenset({
    "목록", "현황", "리스트", "정보", "전체", "모든", "각각", "관련", "관련된", "연관",
    "누구", "어디", "무엇", "어떤", "얼마", "언제", "몇", "개", "명", "건", "곳",
    "알려줘", "보여줘", "알려", "보여", "해줘", "줘", "있는", "하는", "되는", "있나",
    "중인", "중에", "중", "대해", "대한", "그리고", "또는", "지금", "현재", "이번",
    "이야", "인가", "인가요", "일까", "인지", "무슨", "좀", "쪽", "관계", "연결",
    # 랭킹·수식 표현의 잔여물. 이것들이 "그래프에 없는 개체"로 오인되면
    # 답이 있는데도 entity_not_found가 나므로 반드시 걸러야 한다.
    "가장", "제일", "많은", "많이", "많게", "적은", "적게", "높은", "낮은", "큰", "작은",
    "잦은", "자주", "드문", "순서", "순", "상위", "하위", "이력", "과거", "역대",
    "단계", "상태", "기준", "여부", "때", "곳들", "것", "거", "게",
})

# 토큰 끝에 붙는 조사 — 개체 후보 판정 전에 떼어낸다.
JOSA = ("에서는", "으로는", "이라는", "에서", "으로", "이랑", "에게", "한테", "까지", "부터",
        "들은", "들의", "들이", "들을", "들", "은", "는", "이", "가", "을", "를", "의",
        "와", "과", "도", "로", "에", "야", "요", "만", "랑")

_ENTITY_PATTERNS = (
    re.compile(r"(?i)\b(client-[a-z]{1,2})\b"),
    re.compile(r"(?i)\b(product-[a-z]\d)\b"),
    re.compile(r"(?i)\b((?:client|product|employee|project|dept)_\d+)\b"),
)

# 한국어 속성값 뒤에 올 수 있는 경계 — "서울 지역"·"서울에서"는 값으로 보고
# "서울물산"(뒤에 한글 음절이 이어짐)은 값으로 보지 않는다.
_BOUNDARY = r"(?=$|[^가-힣]|에서|에|의|은|는|이|가|을|를|과|와|도|로)"


@dataclass
class Slots:
    entity_term: str | None = None
    relation: str | None = None
    target_type: str | None = None
    node_filter: dict = field(default_factory=dict)
    edge_filter: dict | None = None         # 간선(계약·티켓) 조건. 명시됐을 때만 채워진다
    all_edges: bool = False                 # 상태를 가리지 말라고 명시했는가
    rank: str | None = None                 # None | "desc" | "asc"
    top_k: int | None = None
    unresolved_term: str | None = None      # 개체로 보이지만 그래프에 없는 낱말


def parse(question: str, graph: KnowledgeGraph) -> tuple[Slots, Node | None]:
    """질문을 슬롯으로 변환한다. 개체가 그래프에서 확인되면 노드도 함께 돌려준다."""
    text = question
    slots = Slots()

    # 1) 개체 — 명시적 ID 패턴 → 노드 이름 전량 대조(긴 이름 우선)
    anchor, text = _extract_entity(text, graph)
    if anchor is not None:
        slots.entity_term = anchor.name

    # 2) 랭킹 트리거
    for word in RANK_DESC:
        if word in text:
            slots.rank, text = "desc", text.replace(word, " ")
            break
    else:
        for word in RANK_ASC:
            if word in text:
                slots.rank, text = "asc", text.replace(word, " ")
                break
    if m := re.search(r"상위\s*(\d+)", text):
        slots.top_k, slots.rank = int(m.group(1)), slots.rank or "desc"
        text = text.replace(m.group(0), " ")

    # 3) 간선(계약) 조건 → 노드 속성 필터 순
    for word, status in CONTRACT_STATUS_WORDS.items():
        if word in text:
            slots.edge_filter, text = {"status": status}, text.replace(word, " ")
            break
    slots.all_edges = any(w in text for w in ALL_EDGES_WORDS)
    slots.node_filter, text = _extract_filters(text, graph)

    # 4) 관계 후보 — 확정은 대상 유형까지 본 뒤 6)에서 한다.
    #    언급된 유형은 관계어를 지우기 전에 모아둔다("팀장"이 지워지면 단서가 사라진다).
    mentioned = _mentioned_types(text)
    candidates: tuple[str, ...] = ()
    for relations, words in RELATION_KEYWORDS:
        hit = next((w for w in words if w in text), None)
        if hit:
            candidates, text = relations, text.replace(hit, " ")
            break

    # 5) 대상 유형 — 문장 뒤쪽에 나온 것이 묻는 대상이다(한국어 어순).
    #    출발 개체와 같은 유형도 후보로 둔다. "Client-A의 담당자가 맡은 다른 고객사"처럼
    #    같은 유형을 묻는 질문이 있고, 이 스키마에는 같은 유형을 잇는 관계가 없어
    #    자연히 2홉 경로로 풀린다. 제외해 버리면 엉뚱한 유형을 답하게 된다.
    anchor_type = anchor.type if anchor else None
    best: tuple[int, str] | None = None
    for node_type, words in TYPE_KEYWORDS:
        for w in words:
            pos = text.rfind(w)
            if pos >= 0 and (best is None or pos > best[0]):
                best = (pos, node_type)
    if best:
        slots.target_type = best[1]
    # 고른 유형뿐 아니라 등장한 유형어를 모두 지운다. 남겨두면 6)에서 그 낱말이
    # "그래프에 없는 개체 이름"으로 잘못 잡힌다.
    for _, words in TYPE_KEYWORDS:
        for w in words:
            text = text.replace(w, " ")

    # 6) 관계 확정 — 후보가 여럿이면 출발 개체·대상 유형과 맞는 것을 고른다.
    #    관계어가 아예 없으면 언급된 유형 조합으로 추론한다.
    slots.relation = _resolve_relation(candidates, anchor_type, slots.target_type, mentioned)
    if slots.relation is None:
        slots.relation = _infer_relation(anchor_type, slots.target_type, mentioned)

    # 7) 남은 낱말 중 개체처럼 보이는 것 — 개체를 못 찾았을 때의 진단용
    if anchor is None:
        slots.unresolved_term = _leftover_entity(text)

    return slots, anchor


def _mentioned_types(text: str) -> set[str]:
    """질문에 등장한 노드 유형 전부. 관계 후보를 좁히는 단서로 쓴다."""
    return {t for t, words in TYPE_KEYWORDS if any(w in text for w in words)}


def _resolve_relation(
    candidates: tuple[str, ...], anchor_type: str | None, target_type: str | None,
    mentioned: set[str],
) -> str | None:
    """후보 관계 중 문맥에 맞는 하나를 고른다.

    관계마다 양 끝점 유형이 정해져 있으므로(REL_ENDPOINTS), 출발 개체 유형과
    대상 유형이 그 끝점에 들어맞는지로 거른다. 남은 후보 중에서는 질문에 언급된
    유형을 더 많이 덮는 쪽을 고른다 — "고객을 맡은 직원"은 client·employee를 모두
    덮는 MANAGES_ACCOUNT가, "프로젝트를 이끄는 직원"은 LEADS가 이긴다.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    def score(relation: str) -> int:
        endpoints = set(REL_ENDPOINTS[relation])
        if anchor_type and anchor_type not in endpoints:
            return -1
        if target_type and target_type not in endpoints:
            return -1
        return len(endpoints & mentioned)

    best = max(candidates, key=score)
    # 어느 후보도 문맥과 맞지 않으면 관계를 비운다. 잘못 고정하면 결과가
    # 빈 배열이 되지만, 비워두면 이웃 전체를 훑어 답을 포함할 여지가 남는다.
    return best if score(best) >= 0 else None


def _infer_relation(anchor_type: str | None, target_type: str | None, mentioned: set[str]) -> str | None:
    """관계를 가리키는 낱말이 없을 때, 언급된 유형 조합으로 관계를 좁힌다.

    "프로젝트가 가장 많은 고객사"에는 관계어가 없지만 client와 project를 잇는 관계는
    HAS_PROJECT 하나뿐이라 특정된다. 이 추론이 없으면 7종 중 HAS_PROJECT만
    rank·scan에서 도달할 수 없다(neighbors는 관계 없이도 이웃을 훑어 가려져 있었다).

    후보가 둘 이상이면(client-product를 잇는 USES와 REPORTED_ISSUE처럼) 비워 둔다 —
    찍는 것보다 넓게 훑는 편이 안전하다.
    """
    if target_type is None:
        return None
    known = set(mentioned) | ({anchor_type} if anchor_type else set())
    hits = {
        relation
        for relation, endpoints in REL_ENDPOINTS.items()
        if target_type in endpoints and set(endpoints) <= known
    }
    return hits.pop() if len(hits) == 1 else None


def _extract_entity(text: str, graph: KnowledgeGraph) -> tuple[Node | None, str]:
    for pattern in _ENTITY_PATTERNS:
        if m := pattern.search(text):
            try:
                node = graph.resolve(m.group(1))
            except LookupError:
                continue
            return node, text[: m.start()] + " " + text[m.end() :]

    # 노드 이름 직접 대조. 긴 이름부터 봐야 "Client-AB"가 "Client-A"에 먹히지 않는다.
    lowered = text.lower()
    for name in sorted(graph.all_names(), key=len, reverse=True):
        idx = lowered.find(name.lower())
        if idx >= 0:
            node = graph.resolve(name)
            return node, text[:idx] + " " + text[idx + len(name) :]
    return None, text


def _extract_filters(text: str, graph: KnowledgeGraph) -> tuple[dict, str]:
    """노드 속성값(한국어 원값 + 영문값의 한국어 별칭)을 질문에서 찾아 필터로 만든다."""
    # 그래프에 실제로 존재하는 (속성, 값) 조합만 후보로 삼는다 → 없는 조건을 만들지 않음
    known: dict[str, set[str]] = {}
    for node in graph.nodes.values():
        for key, value in node.properties.items():
            if isinstance(value, str):
                known.setdefault(key, set()).add(value)

    filters: dict[str, str] = {}
    for korean, english in VALUE_ALIASES.items():
        if korean in text and any(english in values for values in known.values()):
            prop = next(k for k, v in known.items() if english in v)
            filters[prop] = english
            text = text.replace(korean, " ")

    for prop, values in known.items():
        for value in sorted(values, key=len, reverse=True):
            if re.search(re.escape(value) + _BOUNDARY, text):
                filters.setdefault(prop, value)
                text = re.sub(re.escape(value) + _BOUNDARY, " ", text)
    return filters, text


def _leftover_entity(text: str) -> str | None:
    for token in re.findall(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9-]*", text):
        stripped = token
        for josa in JOSA:
            if len(stripped) > len(josa) and stripped.endswith(josa):
                stripped = stripped[: -len(josa)]
                break
        if len(stripped) >= 2 and stripped not in STOPWORDS and token not in STOPWORDS:
            return stripped
    return None


def endpoints_ok(relation: str | None, node_type: str | None) -> bool:
    """`relation`의 양 끝점 중 하나가 `node_type`인지 — 잘못된 조합 방어용."""
    if relation is None or node_type is None:
        return True
    return node_type in REL_ENDPOINTS.get(relation, ())
