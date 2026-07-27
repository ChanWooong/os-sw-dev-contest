"""MCP 서버 E2E 확인 — 실제 stdio 클라이언트로 붙어 도구를 호출한다.

`evaluate.py`가 탐색 로직의 정확도를 본다면, 이 스크립트는 그 로직이 MCP 프로토콜
위에서 제대로 노출·직렬화되는지를 본다.

실행:
    python test_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CASES = [
    ("Client-A가 사용 중인 제품 목록은?", "neighbors"),
    ("Product-D1 제품과 관련된 프로젝트는?", "neighbors"),
    ("기술 지원 이슈가 가장 많은 제품은?", "rank"),
    ("진행 중인 프로젝트를 이끄는 직원 목록", "scan"),
    ("서울물산 담당 엔지니어는 누구야?", "entity_not_found"),
]


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=["server.py"], env={"PYTHONUTF8": "1"})
    failures = 0

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = await session.list_tools()
        names = [t.name for t in tools.tools]
        print(f"도구 목록: {names}")
        assert names == ["knowledge_graph"], f"예상과 다른 도구 목록: {names}"

        schema = tools.tools[0].inputSchema
        print(f"입력 스키마 필드: {sorted(schema['properties'])} · 필수 {schema.get('required')}")

        for query, expected in CASES:
            res = await session.call_tool("knowledge_graph", {"query": query})
            payload = json.loads(res.content[0].text)
            actual = payload.get("error") or payload["mode"]
            ok = actual == expected
            failures += not ok
            print(f"[{'PASS' if ok else 'FAIL'}] {query}\n        {actual} · {payload.get('count')}건")

        # 상한 강제 확인: top_k를 넘겨도 MAX_TOP_K(30)를 초과하지 않는다
        res = await session.call_tool("knowledge_graph", {"query": "가장 많은 고객을 담당하는 직원은?", "top_k": 999})
        payload = json.loads(res.content[0].text)
        ok = payload["returned"] <= 30
        failures += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] top_k=999 → {payload['returned']}건 (상한 30)")

    print(f"\nE2E: {'전부 통과' if not failures else f'{failures}건 실패'}")
    return failures


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
