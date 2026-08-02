"""근거 점수 라우터 — 질문이 어느 도구로 가야 하는지 규칙으로 정한다.

## 이 변형의 관점

라우터를 "키워드 목록"으로 짜면 평가셋 30문항에 맞춰 낱말을 적어 넣게 되고,
정확도가 실력이 아니라 조준 사격이 된다. 그래서 두 가지를 나눴다.

- **의도 신호** — 질문이 무엇을 *원하는가*. 집계인가, 관계인가, 서술인가.
  이건 데이터에서 유도할 수 없어 손으로 적는다(아래 표).
- **근거 어휘** — 질문이 무엇에 *대한* 것인가. 개체 이름·속성값·문서 전용어는
  전부 `lexicon.py`가 데이터셋에서 수집한다.

## 핵심 판별 규칙

세 도구가 겹치는 지점이 두 군데 있고, 거기서만 규칙이 필요하다.

1. **"가장 많은 ~"은 집계 대상이 무엇이냐로 갈린다.**
   수치 컬럼을 세면(`매출`·`연봉`) `nl2sql`, 관계를 세면(`담당`·`이슈`)
   `knowledge_graph`다. 같은 표현이 다른 도구를 가리킨다.

2. **관계어가 있어도 문서 전용 기술 용어가 있으면 문서 쪽이다.**
   "SSL 인증서 관련 장애"의 `장애`는 관계어지만 `SSL`은 문서에만 나온다.
   그래프에 없는 낱말을 물었다면 그래프가 답할 수 없다.

점수는 합산이고, 어떤 신호가 왜 켜졌는지 `reasons`로 함께 돌려준다.
브랜치별 변형을 나중에 섞을 때 "왜 그렇게 판단했는지"를 비교할 수 있어야 하기 때문이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from lexicon import attribute_values, document_terms, entity_names

TOOLS = ("nl2sql", "vector_search", "knowledge_graph")
FALLBACK = "vector_search"

# ── 의도 신호 (데이터에서 유도 불가 — 손으로 적는 부분) ─────────────────────
AGGREGATION = ("총 ", "총액", "합계", "평균", "개수", "건수", "몇 개", "몇 명", "몇 건",
               "얼마", "수는", "비율", "통계")
RANKING = ("가장 많", "가장 적", "가장 높", "가장 낮", "가장 큰", "가장 작",
           "제일 많", "제일 적", "최다", "최소", "상위", "하위", "순서로", "순위")
MEASURE = ("매출", "연봉", "급여", "금액", "예산", "가격", "요금", "비용", "단가")
PERIOD = re.compile(r"20\d{2}\s*년|[1-4]\s*분기|월별|분기별|연도별|올해|작년|지난해")
# "제품별·부서별·지역별" — 묶어서 세는 의도(GROUP BY)는 정형 집계 쪽이다.
GROUPING = re.compile(r"[가-힣]{2,}별(?:\s|로|,|$)")

# 정형 테이블 어휘. DB 스키마가 영문 컬럼명이라 한국어 대응은 유도할 수 없어
# 여기만 손으로 적는다. 관계 탐색과 겹치는 낱말(이슈·프로젝트)은 일부러 넣지 않았다.
TABLE_TERMS = ("계약", "티켓", "우선순위", "재직", "입사", "등록된", "해결되지", "미해결")

RELATION = ("담당", "소속", "속한", "사용", "쓰는", "쓰고", "이용", "도입", "이끄는",
            "이끌", "맡은", "맡고", "팀장", "부서장", "관리하는", "이슈", "관련된",
            "연결", "누구야", "누구인가")
NARRATIVE = ("원인", "방법", "어떻게", "절차", "정책", "내용", "논의", "요약", "방식",
             "가이드", "사례", "대응", "설치", "점검", "현상", "조치", "설명", "무엇인가")
DOC_KIND = ("장애보고", "보고서", "기술문서", "매뉴얼", "레퍼런스", "회의록", "회의",
            "미팅", "제안서", "문서")

_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]*|[가-힣]{2,}")


@dataclass
class Route:
    tool: str
    confidence: float
    scores: dict[str, float]
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"tool": self.tool, "confidence": round(self.confidence, 3),
                "scores": self.scores, "reasons": self.reasons}


def route(question: str) -> Route:
    text = question.strip()
    lowered = text.lower()
    scores = dict.fromkeys(TOOLS, 0.0)
    reasons: list[str] = []

    def add(tool: str, points: float, why: str) -> None:
        scores[tool] += points
        reasons.append(f"{tool} +{points:g} · {why}")

    has_aggregation = _any_in(text, AGGREGATION)
    has_ranking = _any_in(text, RANKING)
    has_measure = _any_in(text, MEASURE)
    has_relation = _any_in(text, RELATION)

    # ── nl2sql ──────────────────────────────────────────────────────────────
    if has_aggregation:
        add("nl2sql", 3, "집계 표현")
    if has_measure:
        add("nl2sql", 3, "수치 컬럼 어휘")
    if PERIOD.search(text):
        add("nl2sql", 2, "기간 조건")
    if GROUPING.search(text):
        add("nl2sql", 3, "묶어서 세는 의도(GROUP BY)")
    for term in TABLE_TERMS:
        if term in text:
            add("nl2sql", 2, f"정형 테이블 어휘 '{term}'")
            break
    if _matched(lowered, attribute_values()):
        add("nl2sql", 1, "정형 필터값")

    # ── knowledge_graph ─────────────────────────────────────────────────────
    if has_relation:
        add("knowledge_graph", 3, "관계 표현")
    hit_entity = _matched(lowered, entity_names())
    if hit_entity:
        add("knowledge_graph", 2, f"그래프 개체 '{hit_entity}'")

    # ── vector_search ───────────────────────────────────────────────────────
    if _any_in(text, NARRATIVE):
        add("vector_search", 3, "서술 질문")
    if _any_in(text, DOC_KIND):
        add("vector_search", 2, "문서 유형 지칭")
    doc_hits = _doc_hits(text)
    if doc_hits:
        add("vector_search", min(2, len(doc_hits)), f"문서 전용어 {doc_hits[:3]}")
    latin = [t for t in doc_hits if _LATIN.fullmatch(t)]
    if latin:
        # 그래프에도 DB에도 없고 문서에만 있는 영문 기술 용어(SSL·Kubernetes·API).
        # 그래프가 답할 수 없는 낱말이므로 관계어가 있어도 문서 쪽이 맞다.
        add("vector_search", 3, f"문서 전용 기술 용어 {latin[:2]}")

    # ── 겹치는 지점 조정 ────────────────────────────────────────────────────
    if has_ranking:
        if has_relation and not has_measure:
            add("knowledge_graph", 3, "관계 개수 순위")
        else:
            add("nl2sql", 3, "수치 순위")

    best = max(TOOLS, key=lambda t: scores[t])
    if scores[best] == 0:
        return Route(FALLBACK, 0.0, scores,
                     reasons + [f"근거 없음 → 기본값 {FALLBACK}"])

    ordered = sorted(scores.values(), reverse=True)
    margin = ordered[0] - ordered[1]
    confidence = min(1.0, margin / 6) if margin else 0.0
    return Route(best, confidence, scores, reasons)


def _any_in(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _matched(lowered: str, vocabulary: frozenset[str]) -> str | None:
    """어휘집 중 질문에 등장하는 가장 긴 항목. 긴 것부터 봐야 부분 일치에 안 먹힌다."""
    return next((v for v in sorted(vocabulary, key=len, reverse=True) if v in lowered), None)


def _doc_hits(text: str) -> list[str]:
    docs = document_terms()
    return [t for t in {m.lower() for m in _TOKEN.findall(text)} if t in docs]


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="질문 → 도구 라우팅")
    ap.add_argument("question")
    args = ap.parse_args()
    print(json.dumps(route(args.question).as_dict(), ensure_ascii=False, indent=2))
