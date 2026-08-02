"""knowledge_graph 도구 설정. 모두 환경변수로 재정의 가능."""
from __future__ import annotations

import os
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent                 # mcp-server/knowledge-graph/
REPO_ROOT = TOOL_ROOT.parent.parent                         # 모노레포 루트
DATASET_DIR = Path(os.environ.get("COMPANYX_DATASET", str(REPO_ROOT / "os_dataset")))
GRAPH_DIR = DATASET_DIR / "graph"
NODES_PATH = GRAPH_DIR / "nodes.json"
EDGES_PATH = GRAPH_DIR / "edges.json"

# ── 소형 LLM(4B~7B) 컨텍스트 보호를 위한 응답 상한 ──────────────────────────
# vector_search 계약(../../vector-db/docs/vector-search-contract.md)의
# "설계 결정 사항"과 같은 취지로 knowledge_graph에도 도구 계층에서 상한을 강제한다.
DEFAULT_TOP_K = 10
MAX_TOP_K = 30

# 탐색 최대 홉 수. 2홉이면 "제품 → (사용 고객) → 프로젝트" 같은 질문까지 커버되고,
# 3홉부터는 그래프 규모(133노드) 대비 결과가 과도하게 넓어져 소형 LLM에 불리하다.
MAX_HOPS = 2
