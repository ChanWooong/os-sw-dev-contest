"""Markdown 청킹 파이프라인.

전략 (근거: docs/design.md):
1. `##`/`###` 헤딩 단위로 1차 분할
2. 작은 섹션은 목표 토큰(400)까지 그리디하게 병합 — 과도한 파편화 방지
3. 최대 토큰(500) 초과 섹션은 문단/문장 단위로 재분할, 청크 간 overlap 약 50토큰
4. 각 청크 앞에 문서 제목을 붙여 임베딩 시 문서 맥락을 보존
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from config import (
    CHUNK_MAX_TOKENS,
    CHUNK_OVERLAP_TOKENS,
    CHUNK_TARGET_TOKENS,
    DOC_TYPE_KO,
    DOCUMENTS_DIR,
)


def estimate_tokens(text: str) -> int:
    """bge-m3(XLM-R 계열) 기준 토큰 수 근사치.

    한글 등 CJK는 음절당 약 1토큰, 영문/숫자는 단어당 약 1.3토큰으로 추정.
    정확한 토크나이저 대신 근사치를 쓰는 이유는 docs/design.md 참고.
    """
    cjk = len(re.findall(r"[가-힣一-鿿぀-ヿ]", text))
    words = len(re.findall(r"[A-Za-z0-9]+", text))
    return int(cjk + words * 1.3)


@dataclass
class Chunk:
    doc_id: str
    chunk_index: int
    content: str
    metadata: dict = field(default_factory=dict)


def _split_by_heading(markdown: str) -> list[str]:
    """##/### 헤딩 단위 1차 분할. 헤딩은 해당 섹션에 포함."""
    lines = markdown.splitlines()
    sections: list[list[str]] = [[]]
    for line in lines:
        if re.match(r"^#{2,3}\s", line):
            sections.append([line])
        else:
            sections[-1].append(line)
    return ["\n".join(s).strip() for s in sections if "\n".join(s).strip()]


def _split_oversize(section: str) -> list[str]:
    """max_tokens 초과 섹션을 문단(빈 줄) 단위로 나누고 overlap을 준다."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section) if p.strip()]
    parts: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for para in paragraphs:
        p_tokens = estimate_tokens(para)
        if current and current_tokens + p_tokens > CHUNK_MAX_TOKENS:
            parts.append("\n\n".join(current))
            # overlap: 직전 청크의 끝부분을 다음 청크 앞에 유지
            tail: list[str] = []
            tail_tokens = 0
            for prev in reversed(current):
                tail_tokens += estimate_tokens(prev)
                tail.insert(0, prev)
                if tail_tokens >= CHUNK_OVERLAP_TOKENS:
                    break
            current = tail[:]
            current_tokens = sum(estimate_tokens(p) for p in current)
        current.append(para)
        current_tokens += p_tokens
    if current:
        parts.append("\n\n".join(current))
    return parts


def chunk_document(doc_meta: dict, markdown: str) -> list[Chunk]:
    """단일 문서를 청크 리스트로 변환. doc_meta는 index.json의 항목."""
    sections = _split_by_heading(markdown)

    # 1차 분할 결과를 목표 토큰까지 병합
    merged: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for sec in sections:
        s_tokens = estimate_tokens(sec)
        if buf and buf_tokens + s_tokens > CHUNK_TARGET_TOKENS:
            merged.append("\n\n".join(buf))
            buf, buf_tokens = [], 0
        buf.append(sec)
        buf_tokens += s_tokens
    if buf:
        merged.append("\n\n".join(buf))

    # 초과분 재분할
    pieces: list[str] = []
    for m in merged:
        if estimate_tokens(m) > CHUNK_MAX_TOKENS:
            pieces.extend(_split_oversize(m))
        else:
            pieces.append(m)

    title = doc_meta["title"]
    doc_type_ko = DOC_TYPE_KO[doc_meta["type"]]
    chunks = []
    for i, piece in enumerate(pieces):
        content = piece if piece.startswith("# ") else f"# {title}\n\n{piece}"
        chunks.append(
            Chunk(
                doc_id=doc_meta["id"],
                chunk_index=i,
                content=content,
                metadata={
                    "doc_id": doc_meta["id"],
                    "doc_title": title,
                    "doc_type": doc_type_ko,
                    "doc_type_raw": doc_meta["type"],
                    "chunk_index": i,
                    "source_path": f"documents/{doc_meta['filename']}",
                },
            )
        )
    return chunks


def chunk_all() -> list[Chunk]:
    index = json.loads((DOCUMENTS_DIR / "index.json").read_text(encoding="utf-8"))
    all_chunks: list[Chunk] = []
    for doc_meta in index:
        markdown = (DOCUMENTS_DIR / doc_meta["filename"]).read_text(encoding="utf-8")
        all_chunks.extend(chunk_document(doc_meta, markdown))
    return all_chunks


def print_stats(chunks: list[Chunk]) -> None:
    """문서별 청크 수·평균 길이 통계 출력."""
    by_doc: dict[str, list[Chunk]] = {}
    for c in chunks:
        by_doc.setdefault(c.doc_id, []).append(c)

    print(f"{'문서':<10} {'유형':<8} {'청크수':>4} {'평균토큰':>6} {'최대토큰':>6}")
    for doc_id, doc_chunks in sorted(by_doc.items()):
        tokens = [estimate_tokens(c.content) for c in doc_chunks]
        print(
            f"{doc_id:<10} {doc_chunks[0].metadata['doc_type']:<8}"
            f" {len(doc_chunks):>4} {sum(tokens)//len(tokens):>6} {max(tokens):>6}"
        )
    all_tokens = [estimate_tokens(c.content) for c in chunks]
    print(
        f"\n총 {len(by_doc)}개 문서, {len(chunks)}개 청크 / "
        f"평균 {sum(all_tokens)//len(all_tokens)}토큰, 최대 {max(all_tokens)}토큰"
    )


if __name__ == "__main__":
    print_stats(chunk_all())
