# `knowledge_graph` MCP 도구

② MCP 서버 파트의 3종 도구 중 **지식 그래프 관계 탐색** 담당.
`os_dataset/graph/`의 노드 133개·관계 354개를 메모리에 올려 개체 간 연결을 탐색한다.

DB도 임베딩 모델도 쓰지 않는다 — 이 폴더만 있으면 단독 실행된다.

```bash
pip install -r requirements.txt
python server.py                                    # MCP 서버 (stdio)
python tool.py "Client-A가 사용 중인 제품 목록은?"    # CLI 확인
python evaluate.py                                  # 자체 평가 (10문항)
python test_e2e.py                                  # MCP 프로토콜 E2E 확인
```

## 자체 평가 결과

`os_dataset/questions.json`의 knowledge_graph 10문항 **10/10 통과**.
정답은 `nodes.json`/`edges.json`에서 도구와 독립적으로 재계산해 비교했다
(도구와 같은 코드로 정답을 만들면 동어반복이므로). 상세: [`docs/evaluation.md`](docs/evaluation.md).

## 도구 계약

### 이름

`knowledge_graph`

### 도구 description (라우터/LLM 노출용)

> 사내 지식 그래프(고객사 30·제품 12·직원 45·프로젝트 40·부서 6, 관계 354건)에서
> 개체 사이의 관계를 탐색합니다. "누가 어떤 제품을 담당하나", "어느 고객사가 이 제품을
> 쓰나", "이 부서 소속 직원은 누구인가"처럼 **개체와 개체의 연결**을 묻는 질문에 사용하세요.
> 매출·계약 금액 같은 **수치 집계는 `nl2sql`**, 장애 원인·설치 방법처럼
> **문서의 서술 내용을 묻는 질문은 `vector_search`**를 사용하세요.

적합한 질문 예: "Client-A가 쓰는 제품은?", "클라우드사업부 소속 직원", "이슈가 가장 많은 제품"
부적합한 질문 예: "3분기 총 매출은?"(→ nl2sql), "SSL 장애 원인은?"(→ vector_search)

### 입력 스키마

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|------|------|:---:|:---:|------|
| `query` | string | ✅ | — | 자연어 질문 (한국어) |
| `top_k` | int | | 10 | 반환할 최대 관계 수. 30 초과 값은 30으로 절삭 |

```json
{
  "type": "object",
  "properties": {
    "query": { "type": "string", "description": "자연어 질문" },
    "top_k": { "type": "integer", "default": 10, "maximum": 30 }
  },
  "required": ["query"]
}
```

`vector_search`와 마찬가지로 **첫 인자가 자연어 문자열 하나**다. 규칙 기반 라우터(③)가
질문을 가공 없이 그대로 넘길 수 있고, 소형 LLM이 채워야 할 슬롯이 최소가 된다.

### 출력 스키마

성공 응답 — 모든 값이 한 겹인 평평한 JSON:

| 필드 | 타입 | 설명 |
|------|------|------|
| `mode` | string | 사용된 탐색 모드 (`neighbors` \| `rank` \| `scan`) |
| `anchor` | object | 출발 개체 (`neighbors`에서만). id·name·type + 노드 속성 |
| `relation` | string\|null | 사용된 관계 유형 |
| `target_type` | string\|null | 찾은 노드 유형 |
| `hops` | int | 도달 홉 수 (1 또는 2) |
| `count` / `returned` / `truncated` | int/int/bool | 전체 건수 / 반환 건수 / 상한 절삭 여부 |
| `results` | array | 아래 항목들 |
| `tied_top` | array | 1위가 여럿일 때만 (`rank` 모드) |

`results[]`의 각 항목:

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` `name` `type` | string | 노드 식별자·이름·유형 |
| (노드 속성) | — | 유형별 속성을 최상위로 펼침 (`industry`, `region`, `size` / `category`, `price` / `position`, `dept` / `status`, `budget`) |
| `relation` | string | 이 노드에 도달한 관계 |
| `via` | string | 2홉일 때 경유 노드 이름 |
| `link_count` | int | 평행 간선이 2개 이상일 때만 |
| `contract_amount` `contract_status` | int/string | `USES` 관계의 간선 속성 |
| `top_priority` `issue_count` | string/int | `REPORTED_ISSUE` 관계의 간선 속성 |

```json
{
  "mode": "neighbors",
  "anchor": { "id": "client_1", "name": "Client-A", "type": "client",
              "industry": "제조업", "region": "서울", "size": "startup" },
  "relation": "USES", "target_type": "product", "hops": 1,
  "count": 2, "returned": 2, "truncated": false,
  "results": [
    { "id": "product_7", "name": "Product-C3", "type": "product",
      "category": "cloud", "price": 120, "relation": "USES",
      "contract_amount": 960, "contract_status": "active" }
  ]
}
```

오류 응답 (예외를 던지지 않고 같은 모양의 객체로 반환):

```json
{
  "error": "entity_not_found",
  "message": "그래프에 '서울물산' 개체가 없습니다.",
  "results": [], "count": 0,
  "term": "서울물산", "suggestions": [],
  "hint": "이 그래프의 고객사·제품 이름은 'Client-A', 'Product-C1' 형식입니다."
}
```

| 오류 코드 | 발생 조건 |
|-----------|-----------|
| `entity_not_found` | 개체처럼 보이는 낱말이 있으나 그래프에 없음 |
| `unsupported_query` | 출발 개체도, 집계 대상도 특정하지 못함 |
| `empty_query` | 빈 질의 |

## 동작 방식

질문은 LLM이 아니라 **결정적 파서**([`parser.py`](parser.py))가 슬롯으로 바꾼다.
같은 질문은 항상 같은 슬롯 → 같은 결과가 나오므로 라우터·평가가 성립한다.

```
질문 → [parser] 개체·관계·대상유형·속성필터·랭킹여부 → [graph] 3가지 탐색 중 하나 → 평평한 JSON
```

| 조건 | 모드 | 예시 |
|------|------|------|
| 출발 개체가 그래프에 있음 | `neighbors` | "Client-A가 사용 중인 제품 목록은?" |
| 개체 없이 "가장 많은/적은" | `rank` | "기술 지원 이슈가 가장 많은 제품은?" |
| 개체 없이 관계 + 조건 | `scan` | "진행 중인 프로젝트를 이끄는 직원 목록" |

관계 키워드(`사용`→`USES`, `소속`→`BELONGS_TO`, `팀장`→`HEAD_IS` …)와 노드 유형
키워드는 `parser.py` 상단 표에 모여 있어 확장이 쉽다. 속성 필터 값은 하드코딩하지 않고
**그래프에 실제로 존재하는 속성값에서 자동 수집**한다(영문 값만 한국어 별칭 표를 둔다).
그래프에 없는 조건을 만들어내지 않기 위해서다.

## 설계 결정 사항

1. **자연어 슬롯 추출을 LLM에 맡기지 않음.** 최종 소비자가 4B~7B급 소형 모델이라
   구조화 인자를 정확히 채우기 어렵고, 호출마다 결과가 흔들리면 라우터와 평가가 무의미해진다.
   결정적 파서는 재현 가능하고 오프라인에서 채점할 수 있다.

2. **응답은 한 겹 JSON.** 노드 속성을 `properties` 아래 중첩하지 않고 최상위로 펼쳤다.
   중첩 구조는 소형 모델이 경로를 잘못 읽는 실수가 잦다.
   기본 `top_k=10` 기준 실제 응답 최대치는 약 1,800자(≈900토큰)로,
   `vector_search`의 top-5(≈2,000토큰)와 같은 수준으로 맞췄다.

3. **탐색은 최대 2홉.** "제품 → 사용 고객 → 그 고객의 프로젝트"까지가 실제 질문에서
   필요한 깊이다. 133노드 규모에서 3홉부터는 결과가 그래프 절반으로 번져 소형 LLM에 불리하다.
   1홉에서 답이 나오면 2홉으로 넓히지 않는다.

4. **`REPORTED_ISSUE`는 다홉 경로의 중간 간선으로 쓰지 않는다.** 조직 구조를 나타내는
   구조적 관계와 달리 "이슈를 신고한 적 있다"는 사건 기록이다. 중간 경유로 허용하면
   "이 제품에 이슈를 낸 적 있는 고객의 프로젝트"까지 딸려 와 결과가 흐려진다.
   질문이 이슈를 직접 물을 때만 탐색한다.

5. **없는 개체는 지어내지 않는다.** 개체처럼 보이는 낱말이 그래프에 없으면 임의의 노드로
   추측하지 않고 `entity_not_found`와 이름 형식 안내를 돌려준다. 소형 LLM은 도구가 준
   결과를 그대로 신뢰하는 경향이 강해, 근사 매칭이 곧 환각으로 이어진다.

6. **공동 1위를 숨기지 않는다.** `rank` 모드에서 1위가 여럿이면 `tied_top`으로 알린다.
   실제로 "가장 많은 고객을 담당하는 직원"은 4건으로 3명이 동점이라,
   한 명만 돌려주면 모델이 사실이 아닌 단정을 하게 된다.

## 통합 안내 (③ 라우터 · ④ 에이전트 담당자용)

- **Python에서 직접 호출**: `from tool import knowledge_graph_query` →
  `knowledge_graph_query(question, top_k=10) -> dict`. 예외를 던지지 않고 항상 dict를 돌려준다.
- **MCP 서버로 등록**: 루트 `.mcp.json`에 아래 항목을 추가하면 된다
  (공용 파일이라 이 브랜치에서는 건드리지 않았다).

  ```json
  "companyx-knowledge-graph": {
    "command": "py",
    "args": ["-3.12", "mcp-server/knowledge-graph/server.py"],
    "env": { "PYTHONUTF8": "1" }
  }
  ```

  macOS·Linux에서는 `command`를 `python`(또는 가상환경의 파이썬 경로)으로 바꾼다.
- **데이터셋 경로**는 `COMPANYX_DATASET` 환경변수로 재정의 가능. 기본값은 레포 루트의 `os_dataset/`.

## 알려진 한계

- 평가 4번 문항("서울물산 담당 엔지니어")의 힌트는 `client_2`를 가리키지만, 배포된 그래프의
  고객사 이름은 `Client-A`~`Client-AD` 형식뿐이라 해당 노드가 존재하지 않는다.
  근거: `docs/evaluation.md`의 "4번 문항에 대하여".
- 속성 필터는 노드 속성만 대상으로 한다. 간선 속성(`USES.status`, `REPORTED_ISSUE.priority`)은
  결과에 표시는 되지만 필터 조건으로는 아직 쓰이지 않는다.
- 3홉 이상 경로 질의("A의 담당자가 맡은 다른 고객사의 프로젝트")는 지원하지 않는다.
