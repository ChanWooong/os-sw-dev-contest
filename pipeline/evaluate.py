"""자체 평가: questions.json의 벡터 검색용 10문항으로
순수 벡터 vs 하이브리드 검색의 top-3/top-5 문서 적중률을 비교하고
docs/evaluation.md 리포트를 생성한다.

정답셋(EXPECTED)은 문서 내용을 직접 확인해 수작업으로 구축했다
(questions.json에는 힌트만 있고 정답 문서 ID가 없음). 근거는 각 항목 주석 참고.
"""
from __future__ import annotations

import datetime
import json

from config import DATASET_DIR, DOCS_OUT_DIR
from search import hybrid_search, vector_search

# 질문 → 관련 문서 ID 집합 (하나라도 top-k 안에 들면 적중)
EXPECTED: dict[str, set[str]] = {
    # 장애보고 전체 (DOC-001~010 모두 서버 장애 사례+원인 포함)
    "최근 서버 장애 사례와 원인을 알려줘": {f"DOC-{i:03d}" for i in range(1, 11)},
    # DOC-011 = Product-C1 설치 가이드
    "Product-C1 설치 방법이 궁금해": {"DOC-011"},
    # DOC-007 = 장애 내용에 Kubernetes 언급된 유일한 장애보고
    "Kubernetes 관련 장애 대응 방법은?": {"DOC-007"},
    # DOC-014/019 = 성능 튜닝 가이드
    "성능 최적화를 위한 DB 튜닝 방법 알려줘": {"DOC-014", "DOC-019"},
    # 회의록 중 "보안 취약점 점검" 언급 5건
    "보안 취약점 점검 관련 내용이 있어?": {"DOC-021", "DOC-022", "DOC-024", "DOC-028", "DOC-029"},
    # DOC-013/018 = 운영 매뉴얼 (백업 정책 섹션 포함)
    "백업 정책은 어떻게 되어 있어?": {"DOC-013", "DOC-018"},
    # DOC-015/020 = API 레퍼런스 (인증 방식 기술)
    "API 인증 방식은 뭐야?": {"DOC-015", "DOC-020"},
    # 회의록 중 일정/마일스톤 지연 언급 6건
    "고객사 미팅에서 논의된 일정 지연 이슈는?": {"DOC-021", "DOC-023", "DOC-025", "DOC-026", "DOC-027", "DOC-029"},
    # 제안서 전체 (DOC-031~040 모두 마이그레이션 계획 포함)
    "클라우드 마이그레이션 제안서 내용 보여줘": {f"DOC-{i:03d}" for i in range(31, 41)},
    # SSL 인증서 만료 장애 3건
    "SSL 인증서 관련 장애가 있었어?": {"DOC-002", "DOC-005", "DOC-006"},
}


def _doc_ids(results: list[dict]) -> list[str]:
    """검색 결과에서 문서 ID 목록(순서 유지, 중복 제거)."""
    seen: list[str] = []
    for r in results:
        doc_id = r["source_path"].split("/")[-1].removesuffix(".md")
        if doc_id not in seen:
            seen.append(doc_id)
    return seen


def evaluate() -> None:
    questions = [
        q["q"]
        for q in json.loads((DATASET_DIR / "questions.json").read_text(encoding="utf-8"))
        if q["tool"] == "vector_search"
    ]
    assert set(questions) == set(EXPECTED), "questions.json과 정답셋 불일치"

    rows = []
    for q in questions:
        row = {"q": q}
        for mode, fn in (("vector", vector_search), ("hybrid", hybrid_search)):
            results = fn(q, top_k=5)
            found = _doc_ids(results)
            expected = EXPECTED[q]
            row[mode] = {
                "top1": found[:1],
                "found": found,
                "hit3": bool(expected & set(found[:3])),
                "hit5": bool(expected & set(found[:5])),
            }
            print(f"[{mode:6s}] {q}")
            print(f"         top-5 문서: {found}  (기대: {sorted(expected)[:3]}{'...' if len(expected) > 3 else ''})")
        rows.append(row)

    write_report(rows)


def write_report(rows: list[dict]) -> None:
    n = len(rows)
    stats = {
        mode: {
            "hit3": sum(r[mode]["hit3"] for r in rows),
            "hit5": sum(r[mode]["hit5"] for r in rows),
        }
        for mode in ("vector", "hybrid")
    }

    lines = [
        "# 벡터 검색 자체 평가 결과",
        "",
        f"> 생성일: {datetime.date.today().isoformat()} · `pipeline/evaluate.py` 실행 결과",
        "> 평가셋: `questions.json`의 벡터 검색용 10문항 · 정답 문서는 수작업 큐레이션(스크립트 주석 참고)",
        "",
        "## 요약: 순수 벡터 vs 하이브리드",
        "",
        "| 지표 | 순수 벡터 | 하이브리드 (RRF) |",
        "|------|-----------|------------------|",
        f"| Top-3 적중률 | {stats['vector']['hit3']}/{n} ({stats['vector']['hit3']*100//n}%) "
        f"| {stats['hybrid']['hit3']}/{n} ({stats['hybrid']['hit3']*100//n}%) |",
        f"| Top-5 적중률 | {stats['vector']['hit5']}/{n} ({stats['vector']['hit5']*100//n}%) "
        f"| {stats['hybrid']['hit5']}/{n} ({stats['hybrid']['hit5']*100//n}%) |",
        "",
        "적중 기준: 관련 문서 중 하나라도 top-k 검색 결과(청크의 소속 문서 기준, 중복 제거)에 포함되면 적중.",
        "",
        "## 문항별 상세",
        "",
        "| 질문 | 벡터 top-3 | 벡터 top-5 | 하이브리드 top-3 | 하이브리드 top-5 | 하이브리드 1위 문서 |",
        "|------|:---:|:---:|:---:|:---:|------|",
    ]
    for r in rows:
        mark = lambda b: "✅" if b else "❌"  # noqa: E731
        top1 = r["hybrid"]["top1"][0] if r["hybrid"]["top1"] else "-"
        lines.append(
            f"| {r['q']} | {mark(r['vector']['hit3'])} | {mark(r['vector']['hit5'])} "
            f"| {mark(r['hybrid']['hit3'])} | {mark(r['hybrid']['hit5'])} | {top1} |"
        )

    DOCS_OUT_DIR.mkdir(exist_ok=True)
    out = DOCS_OUT_DIR / "evaluation.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n리포트 저장: {out}")
    print(f"벡터   top-3 {stats['vector']['hit3']}/{n}, top-5 {stats['vector']['hit5']}/{n}")
    print(f"하이브리드 top-3 {stats['hybrid']['hit3']}/{n}, top-5 {stats['hybrid']['hit5']}/{n}")


if __name__ == "__main__":
    evaluate()
