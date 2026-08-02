# `knowledge_graph` MCP 도구

② MCP 서버 파트의 3종 도구 중 **지식 그래프 관계 탐색** 담당.
`os_dataset/graph/`의 노드 133개·관계 354개를 메모리에 올려 개체 간 연결을 탐색한다.

DB도 임베딩 모델도 쓰지 않는다 — 이 폴더만 있으면 단독 실행된다.

```bash
pip install -r requirements.txt
python server.py                                    # MCP 서버 (stdio)
python tool.py "Client-A가 사용 중인 제품 목록은?"    # CLI 확인
python evaluate.py                                  # 자체 평가 (공식 10문항)
python evaluate_robustness.py                       # 견고성 평가 (바꿔 말한 20문항)
python test_e2e.py                                  # MCP 프로토콜 E2E 확인
```

## 평가 결과

| 평가 | 문항 | 결과 |
|------|:---:|------|
| [`evaluate.py`](evaluate.py) — 공식 평가셋 | 10 | **10/10** |
| [`evaluate_robustness.py`](evaluate_robustness.py) — 바꿔 말한 질문 + 결함 회귀 | 25 | **25/25** |
| [`test_e2e.py`](test_e2e.py) — MCP 프로토콜 | 6 | 전부 통과 |

정답은 `nodes.json`/`edges.json`에서 도구와 독립적으로 재계산해 비교한다
(도구와 같은 코드로 정답을 만들면 동어반복이므로). 목록형은 노드 id 집합이
**완전 일치**해야 통과한다. 상세: [`docs/evaluation.md`](docs/evaluation.md).

공식 10문항은 파서를 만들 때 이미 보고 있던 문제라 통과해도 일반화 성능을 뜻하지
않는다. 그래서 같은 의도를 다른 말로 묻는 견고성 평가를 따로 뒀다. 두 평가에
쓰지 않은 새 질문 12개로 확인했을 때도 12/12였다.

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
| `edge_filter` | object | 간선 조건이 걸렸을 때만 (예: `{"status": "active"}`) |
| `excluded_by_edge_filter` | int | 그 조건에 걸러진 관계 수 (0이면 생략) |
| `max_hops` | int | 2홉까지 훑고도 답을 못 찾았을 때만. 탐색 한계를 알린다 |

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

| 오류 코드 | 발생 조건 | 함께 오는 필드 |
|-----------|-----------|----------------|
| `entity_not_found` | 개체처럼 보이는 낱말이 있으나 그래프에 없음 | `term`, `suggestions` |
| `ambiguous_entity` | 그 낱말이 여러 노드에 걸림 (예: "재원" → 4명) | `term`, `candidates` |
| `unsupported_query` | 출발 개체도, 집계 대상도 특정하지 못함 | `relations` |
| `empty_query` | 빈 질의 | — |

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

7. **"사용 중"은 유효 계약만 센다.** `USES` 간선 61건 중 19건(31%)이 해지·종료된
   계약이다. 이를 구분하지 않으면 "지금 쓰는 제품"에 이미 끊긴 계약이 섞여 나온다
   (30개 고객사 중 16개가 해당). 그래서 `USES`를 명시적으로 물으면 기본으로
   `status=active`만 반환하고, 걸러낸 건수를 `excluded_by_edge_filter`로 함께 알린다.
   "해지한 제품", "계약 전체"처럼 다르게 물으면 그에 맞춰 조건이 바뀐다.
   반면 "관련된"처럼 넓게 물을 때는 과거 계약도 관계의 일부이므로 거르지 않는다.

8. **애매한 관계어는 문맥으로 정한다.** "이끄는"은 부서를 이끌면 `HEAD_IS`,
   프로젝트를 이끌면 `LEADS`, 고객을 맡으면 `MANAGES_ACCOUNT`다. 관계마다 양 끝점
   유형이 정해져 있으므로, 출발 개체·대상 유형과 대조해 맞는 것을 고른다.
   하나로 고정하면 "경영지원팀을 이끄는 사람"이 빈 결과가 된다.
   관계어가 아예 없어도 언급된 유형 조합으로 좁힌다 — client와 project를 잇는 관계는
   `HAS_PROJECT` 하나뿐이라 "프로젝트가 가장 많은 고객사"가 특정된다.

9. **애매한 이름도 추측하지 않는다.** "재원"은 조재원·서재원·안재원·황재원에 걸린다.
   가장 짧은 이름을 고르는 식으로 하나를 찍으면 5번 원칙(없는 개체를 지어내지 않는다)과
   모순된다 — 없는 개체는 거부하면서 애매한 개체는 추측하는 셈이다.
   `ambiguous_entity`와 후보 목록을 돌려주고 되묻게 한다.

10. **간선 조건은 모든 모드에 똑같이 적용한다.** `neighbors`에서만 유효 계약을 세고
    `rank`에서는 전체를 세면, "사용 중"의 뜻이 질문 형태에 따라 달라진다. 실제로
    전체 기준 1위는 Client-T 단독이지만 유효 계약만 세면 5개사 공동 1위라 답이 갈렸다.

11. **못 미치면 못 미친다고 말한다.** 2홉까지 훑고도 답이 없으면 `max_hops`를 붙인다.
    빈 결과를 "그런 관계가 없다"로 읽으면 LLM이 사실이 아닌 단정을 하기 때문이다.

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
아래는 코드리뷰에서 확인됐으나 **아직 고치지 않은** 항목이다. 순서는 수정 우선순위다.

- **동명이인 노드가 이름으로 조회되지 않는다.** `_by_name`이 1:1 dict라 같은 이름의
  뒤 노드가 앞 노드를 덮는다. `박성민`은 `employee_4`·`employee_31` 둘인데
  `employee_31`만 잡히고, 프로젝트도 `Client-B CI/CD 파이프라인 구축`이 2건 중복이다.
  45명 규모에서 이미 충돌했으므로 데이터가 커지면 확대된다.
- **파서가 이해 못한 질문이 대부분 `entity_not_found`로 귀결된다.** "3분기 총 매출은?"에
  "3분기라는 개체가 없다"고 답하면 소형 LLM이 "3분기 데이터가 없다"로 읽는다.
  라우터가 오분류했을 때 라우팅 실패가 사실 오류로 둔갑하므로 `unsupported_query`여야 한다.
- **속성만으로 거르는 목록 질의가 안 된다.** `_extract_filters`가 "서울"·"금융"을
  정확히 뽑는데도 앵커나 관계가 없으면 어느 모드에도 들어가지 못한다
  ("서울 지역 고객사 목록").
- **속성값 랭킹이 안 된다.** `rank`는 차수만 센다. `budget`·`price`·`amount`가
  있는데도 "예산이 가장 큰 프로젝트"에 답하지 못한다.
- **노드 ID에 조사가 붙으면 인식하지 못한다.** `\b` 경계가 한글 앞에서 성립하지 않아
  `employee_1은`은 실패하고 `employee_1 `은 성공한다.

그 밖의 구조적 제약:

- 간선 속성 필터는 엔진(`graph.py`의 `EDGE_FILTERABLE`)에 `USES.status`와
  `REPORTED_ISSUE.priority` 둘 다 열려 있으나, 한국어 표현이 붙은 것은 계약 상태뿐이다.
  "critical 이슈를 낸 고객사" 같은 심각도 조건은 `parser.py`에 낱말만 추가하면 동작한다.
- 3홉 이상 경로 질의는 지원하지 않는다. 다만 조용히 다른 답을 주지 않고 `max_hops`로
  한계를 알린다. 출발 개체와 **같은 유형**을 묻는 질문("Client-A의 담당자가 맡은 다른
  고객사")은 2홉이라 지원된다.
- 파서는 키워드 기반이라 표에 없는 표현은 잡지 못한다. 확장은 `parser.py` 상단 표에
  항목을 추가하는 것으로 끝나며, 추가할 때마다 `evaluate_robustness.py`에 문항을
  같이 넣어야 회귀를 잡을 수 있다.
