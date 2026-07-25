"""(선택 구현) 임베딩 유사도 기반 도구 라우터 프로토타입.

규칙 기반 라우터를 보완하는 아이디어 검증:
- 도구별 대표 예시 질문(수작업 작성, questions.json과 겹치지 않음)을 임베딩해 두고
- 입력 질문과 각 도구 예시들의 최대 코사인 유사도로 라우팅
- questions.json 30문항으로 정확도 측정

주의: 평가셋(questions.json)의 질문을 프로토타입 예시로 쓰면 자기 채점이 되므로
예시 질문은 별도로 작성했다.
"""
from __future__ import annotations

import json

from config import DATASET_DIR
from embedding import embed_batch

# 도구별 대표 예시 질문 (수작업 작성)
TOOL_EXAMPLES: dict[str, list[str]] = {
    "nl2sql": [
        "부산 지역 올해 매출 합계 알려줘",
        "계약 금액이 가장 큰 고객사 3곳은?",
        "부서별 직원 수를 세어줘",
        "지난 분기 대비 매출 증가율은?",
        "해결된 지원 티켓 개수는 몇 개야?",
    ],
    "vector_search": [
        "장애 원인 분석 보고서 찾아줘",
        "제품 설치할 때 사전 요구사항이 뭐야?",
        "운영 매뉴얼에서 모니터링 방법 알려줘",
        "회의에서 논의된 리스크가 뭐였지?",
        "도입 제안서의 기대 효과 요약해줘",
    ],
    "knowledge_graph": [
        "이 고객사와 연결된 제품과 담당자를 알려줘",
        "누가 어떤 프로젝트를 이끌고 있어?",
        "특정 제품을 쓰는 고객사 목록 보여줘",
        "이 직원이 담당하는 고객사는 어디야?",
        "부서와 직원의 소속 관계를 알려줘",
    ],
}


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb)


def main() -> None:
    # 도구별 예시 임베딩
    tool_embs: dict[str, list[list[float]]] = {}
    for tool, examples in TOOL_EXAMPLES.items():
        tool_embs[tool] = embed_batch(examples)

    questions = json.loads((DATASET_DIR / "questions.json").read_text(encoding="utf-8"))
    q_embs = embed_batch([q["q"] for q in questions])

    correct = 0
    per_tool: dict[str, list[int]] = {t: [0, 0] for t in TOOL_EXAMPLES}  # [맞춤, 전체]
    print(f"{'질문':<40} {'정답':<16} {'예측':<16} 결과")
    for q, emb in zip(questions, q_embs):
        # 각 도구 예시들과의 최대 유사도로 분류
        scores = {
            tool: max(cosine(emb, ex) for ex in exs) for tool, exs in tool_embs.items()
        }
        predicted = max(scores, key=scores.get)
        ok = predicted == q["tool"]
        correct += ok
        per_tool[q["tool"]][0] += ok
        per_tool[q["tool"]][1] += 1
        print(f"{q['q']:<40} {q['tool']:<16} {predicted:<16} {'O' if ok else 'X'}")

    print(f"\n전체 정확도: {correct}/{len(questions)} ({correct*100//len(questions)}%)")
    for tool, (hit, total) in per_tool.items():
        print(f"  {tool}: {hit}/{total}")


if __name__ == "__main__":
    main()
