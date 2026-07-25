"""공통 설정. 환경변수로 재정의 가능."""
import os
from pathlib import Path

PART_ROOT = Path(__file__).resolve().parent.parent      # vector-db/
REPO_ROOT = PART_ROOT.parent                            # 모노레포 루트
DATASET_DIR = REPO_ROOT / "os_dataset"                  # 데이터셋은 레포 루트에 배치 (공용)
DOCUMENTS_DIR = DATASET_DIR / "documents"
DOCS_OUT_DIR = PART_ROOT / "docs"

DB_DSN = os.environ.get(
    "COMPANYX_DSN",
    "host=localhost port=5432 dbname=companyx user=companyx password=companyx",
)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "1024"))
EMBED_BATCH_SIZE = 16

# 청킹 파라미터 (토큰 추정 기준, 근거: docs/design.md)
CHUNK_TARGET_TOKENS = 400   # 300~500 목표의 중간값
CHUNK_MAX_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50

# 문서 유형: 데이터셋(index.json) 영문 타입 → MCP 계약의 한글 enum
DOC_TYPE_KO = {
    "incident_report": "장애보고",
    "technical_doc": "기술문서",
    "meeting_note": "회의록",
    "proposal": "제안서",
}
DOC_TYPE_EN = {v: k for k, v in DOC_TYPE_KO.items()}
