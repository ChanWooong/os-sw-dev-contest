"""Ollama /api/embed 클라이언트 (배치 + 재시도)."""
from __future__ import annotations

import sys
import time

import requests

from config import EMBED_BATCH_SIZE, EMBED_DIM, EMBED_MODEL, OLLAMA_URL

MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 2.0


def embed_batch(texts: list[str]) -> list[list[float]]:
    """텍스트 배치를 임베딩. 실패 시 지수 백오프로 재시도."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": EMBED_MODEL, "input": texts},
                timeout=120,
            )
            resp.raise_for_status()
            embeddings = resp.json()["embeddings"]
            for emb in embeddings:
                if len(emb) != EMBED_DIM:
                    raise ValueError(
                        f"임베딩 차원 불일치: 기대 {EMBED_DIM}, 실제 {len(emb)}"
                    )
            return embeddings
        except Exception as e:  # noqa: BLE001 — 재시도 후 최종 raise
            last_error = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SEC * (2 ** (attempt - 1))
                # stderr 사용: MCP 서버가 stdio로 통신하므로 stdout 오염 금지
                print(f"  [재시도 {attempt}/{MAX_RETRIES}] {e} — {wait:.0f}초 대기", file=sys.stderr)
                time.sleep(wait)
    raise RuntimeError(f"임베딩 실패 (재시도 {MAX_RETRIES}회 소진): {last_error}")


def embed_all(texts: list[str]) -> list[list[float]]:
    """전체 텍스트를 배치 단위로 임베딩. 진행 로그 출력."""
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        embeddings.extend(embed_batch(batch))
        print(f"  임베딩 진행: {min(i + EMBED_BATCH_SIZE, len(texts))}/{len(texts)}")
    return embeddings


def embed_query(text: str) -> list[float]:
    return embed_batch([text])[0]
