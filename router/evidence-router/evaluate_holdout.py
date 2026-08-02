"""홀드아웃 평가 — `questions.json`에 없는 24문항.

공식 30문항은 규칙을 짜면서 이미 보고 있던 문제라, 통과해도 일반화 성능을 뜻하지
않는다. 여기 문항은 같은 세 도구를 겨냥하되 표현과 소재를 새로 지었다.

**투명성**: 최초 실행에서 "부서별 인원수 알려줘" 1건이 틀렸고, 그 원인으로
`GROUPING`(묶어서 세는 의도) 규칙을 추가했다. 따라서 이 24문항은 지금은
**회귀 스위트이지 홀드아웃이 아니다.** 규칙을 더 손댈 때는 새 문항으로 다시 재야 한다.

실행:
    python evaluate_holdout.py
"""
from __future__ import annotations

import collections

from router import TOOLS, route

# (질문, 정답 도구)
CASES: list[tuple[str, str]] = [
    # ── nl2sql ──────────────────────────────────────────────────────────────
    ("부서별 인원수 알려줘", "nl2sql"),
    ("작년 대비 올해 매출 증가율은?", "nl2sql"),
    ("계약 금액이 1억 넘는 건 몇 개야?", "nl2sql"),
    ("제주 지역 고객사 수를 알려줘", "nl2sql"),
    ("가장 비싼 제품의 월 요금은?", "nl2sql"),
    ("완료된 프로젝트 개수", "nl2sql"),
    ("직원 평균 근속연수는?", "nl2sql"),
    ("분기별 매출 추이 보여줘", "nl2sql"),
    # ── vector_search ───────────────────────────────────────────────────────
    ("장애 재발 방지 대책이 뭐였어?", "vector_search"),
    ("모니터링 설정 절차 알려줘", "vector_search"),
    ("로드밸런서 헬스체크 실패 사례 있어?", "vector_search"),
    ("제안서에 나온 기대 효과는?", "vector_search"),
    ("회의에서 결정된 사항 정리해줘", "vector_search"),
    ("데이터베이스 인덱스 최적화 어떻게 해?", "vector_search"),
    ("권한 관리 정책이 어떻게 돼?", "vector_search"),
    ("배포 자동화 스크립트 관련 문서 있어?", "vector_search"),
    # ── knowledge_graph ─────────────────────────────────────────────────────
    ("Client-K와 거래하는 담당 직원은?", "knowledge_graph"),
    ("Product-C2를 도입한 곳 알려줘", "knowledge_graph"),
    ("영업팀에 속한 사람들", "knowledge_graph"),
    ("누가 Client-P를 맡고 있어?", "knowledge_graph"),
    ("데이터플랫폼팀 팀장이 누구지?", "knowledge_graph"),
    ("프로젝트를 제일 많이 이끄는 직원은?", "knowledge_graph"),
    ("Client-AB와 연결된 제품들", "knowledge_graph"),
    ("이슈를 가장 많이 낸 고객사는?", "knowledge_graph"),
]


def evaluate() -> float:
    per_tool: collections.Counter[str] = collections.Counter()
    totals: collections.Counter[str] = collections.Counter()
    wrong = []

    for question, expected in CASES:
        result = route(question)
        totals[expected] += 1
        if result.tool == expected:
            per_tool[expected] += 1
        else:
            wrong.append((question, expected, result.tool, result.scores))

    correct = sum(per_tool.values())
    print(f"홀드아웃 정확도: {correct}/{len(CASES)} ({correct * 100 // len(CASES)}%)\n")
    for tool in TOOLS:
        print(f"  {tool:16s} {per_tool[tool]}/{totals[tool]}")
    for question, expected, got, scores in wrong:
        print(f"\n  ❌ {question}\n     정답 {expected} → 예측 {got} · 점수 {scores}")
    return correct / len(CASES)


if __name__ == "__main__":
    evaluate()
