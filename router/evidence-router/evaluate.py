"""라우팅 정확도 평가 — `questions.json` 30문항 (도구별 10문항).

혼동행렬까지 내는 이유는, 브랜치별 라우터 변형을 나중에 섞을 때 필요한 정보가
총점이 아니라 **"어느 도구를 어느 도구로 착각하는가"**이기 때문이다.
변형 A가 nl2sql↔graph 혼동에 강하고 변형 B가 vector 판정에 강하다면
그 조합이 곧 합칠 근거가 된다.

실행:
    python evaluate.py            # 결과 출력 + 오답 근거 표시
"""
from __future__ import annotations

import collections
import json

from lexicon import DATASET_DIR, summary
from router import TOOLS, route


def evaluate(show_reasons: bool = True) -> float:
    questions = json.loads((DATASET_DIR / "questions.json").read_text(encoding="utf-8"))

    confusion: collections.Counter[tuple[str, str]] = collections.Counter()
    wrong: list[tuple[str, str, str, list[str]]] = []

    for item in questions:
        expected = item["tool"]
        result = route(item["q"])
        confusion[(expected, result.tool)] += 1
        if result.tool != expected:
            wrong.append((item["q"], expected, result.tool, result.reasons))

    total = len(questions)
    correct = sum(count for (exp, got), count in confusion.items() if exp == got)

    print(f"어휘 수집: {summary()}\n")
    print(f"정확도: {correct}/{total} ({correct * 100 // total}%)\n")

    print("혼동행렬 (행=정답, 열=예측)")
    header = "".join(f"{t[:14]:>16s}" for t in TOOLS)
    print(f"{'':>18s}{header}")
    for expected in TOOLS:
        row = "".join(f"{confusion[(expected, got)]:>16d}" for got in TOOLS)
        hit = confusion[(expected, expected)]
        print(f"{expected:>18s}{row}   ({hit}/10)")

    if wrong:
        print(f"\n오답 {len(wrong)}건")
        for question, expected, got, reasons in wrong:
            print(f"\n  {question}")
            print(f"    정답 {expected} → 예측 {got}")
            if show_reasons:
                for reason in reasons:
                    print(f"      {reason}")
    return correct / total


if __name__ == "__main__":
    evaluate()
