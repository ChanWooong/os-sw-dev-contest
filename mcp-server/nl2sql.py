"""nl2sql MCP 도구 — 자연어 질문을 SQL로 바꿔 Company-X DB를 조회한다.

진행 상황:
  [조각 1] DB 연결 + SQL 실행          (execute_sql)
  [조각 2] 안전 검증 + 행 수 상한        (validate_sql, enforce_limit)
  [조각 3] 결과를 평평한 JSON으로 정리    (format_result)
  [조각 4] 자연어 → SQL 생성 (Ollama)   (generate_sql)
  [조각 5] 조립 + 자가 교정 재시도        (answer)                     ← 지금 추가
"""
import os
import re
import json
import decimal
import datetime
import requests
import psycopg

# ── 설정 ──────────────────────────────────────────
DB_DSN = os.environ.get(
    "COMPANYX_DSN",
    "host=localhost port=5432 dbname=companyx user=companyx password=companyx",
)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
SQL_MODEL = os.environ.get("SQL_MODEL", "gemma3:4b")

ALLOWED_TABLES = {
    "departments", "employees", "clients", "products",
    "contracts", "projects", "sales", "support_tickets",
}
FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter",
    "truncate", "create", "grant", "revoke",
}
DEFAULT_ROW_LIMIT = 50
MAX_ATTEMPTS = 3          # 자가 교정 최대 시도 횟수


class UnsafeSQLError(Exception):
    pass


# ── 스키마 커닝페이퍼 (LLM 프롬프트용) ──────────────
SCHEMA = """테이블과 컬럼 (PostgreSQL):
departments(id, name, head_id)  -- 부서
employees(id, name, email, position, dept_id, hire_date, salary, is_active)  -- 직원. dept_id→departments.id
clients(id, name, industry, region, company_size, contact_name, contact_email, registered_at, is_active)  -- 고객사
products(id, name, category, description, price_monthly, version, release_date, status)  -- 제품
contracts(id, client_id, product_id, manager_id, contract_type, amount, start_date, end_date, status)  -- 계약. client_id→clients, product_id→products, manager_id→employees
projects(id, name, client_id, manager_id, contract_id, status, start_date, end_date, budget, description)  -- 프로젝트
sales(id, contract_id, client_id, product_id, amount, sale_date, quarter, category, region)  -- 매출
support_tickets(id, client_id, product_id, assignee_id, title, description, priority, status, created_at, resolved_at)  -- 지원 티켓

값 형식:
- sales.quarter: '2025-Q3' 형식
- 카테고리(sales.category / products.category): 'cloud','security','data','consulting'
- contracts.status: 'active','expired','pending'
- projects.status: 'in_progress','planning','on_hold','completed'
- support_tickets.priority: 'critical','high','medium','low'
- support_tickets.status: 'open','in_progress','resolved','closed'
  ("아직 해결되지 않은" = status IN ('open','in_progress'))
- 지역/업종/부서명/고객명 등 텍스트 값은 모두 한국어로 저장됨 (영어로 바꾸지 말 것).
  region 값 예: '서울','경기','부산','대구','인천','광주','대전','제주'
- 부서명 예: '기술지원팀','영업팀','클라우드사업부','보안솔루션팀','데이터플랫폼팀','경영지원팀'
"""

SYSTEM_PROMPT = f"""너는 PostgreSQL 전문가다. 사용자의 한국어 질문을 PostgreSQL SELECT 쿼리 하나로 변환하라.

규칙:
- 오직 SELECT 문 하나만 출력하라. 설명, 주석, 마크다운(```) 절대 금지.
- 아래 스키마의 테이블/컬럼만 사용하라. 없는 이름을 지어내지 마라.
- 집계에는 SUM/AVG/COUNT를 적절히 사용하라.
- "가장 ~한 것 하나"를 물으면 ORDER BY ... DESC LIMIT 1 로 하나만 반환하라. HAVING으로 비교하지 마라.
- 텍스트 조건 값은 스키마에 적힌 실제 한국어 값을 그대로 사용하라.
- '제품별','부서별'처럼 '~별' 표현이 있을 때만 GROUP BY로 나눠라. 그런 표현이 없으면 불필요한 GROUP BY 없이 전체를 하나로 집계하라.

{SCHEMA}
예시:
질문: 2025년 3분기 총 매출액은 얼마야?
SELECT SUM(amount) FROM sales WHERE quarter = '2025-Q3'

질문: 기술지원팀 직원 목록과 연봉을 알려줘
SELECT e.name, e.position, e.salary FROM employees e JOIN departments d ON e.dept_id = d.id WHERE d.name = '기술지원팀'

질문: 제품별 총 계약 금액을 큰 순서로 보여줘
SELECT p.name, SUM(c.amount) FROM contracts c JOIN products p ON c.product_id = p.id GROUP BY p.name ORDER BY SUM(c.amount) DESC

질문: 예산이 가장 큰 프로젝트의 이름은?
SELECT name FROM projects ORDER BY budget DESC LIMIT 1

질문: 부산 지역 고객사는 몇 개야?
SELECT COUNT(*) FROM clients WHERE region = '부산'

질문: 미해결 상태인 high 우선순위 티켓 목록을 보여줘
SELECT title, priority, status FROM support_tickets WHERE priority = 'high' AND status IN ('open','in_progress')
"""


# ────────────────────────────────────────────────
# [조각 1] DB 실행
# ────────────────────────────────────────────────
def execute_sql(sql: str):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [d.name for d in cur.description]
            rows = cur.fetchall()
    return columns, rows


# ────────────────────────────────────────────────
# [조각 2] 안전 검증
# ────────────────────────────────────────────────
def validate_sql(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    low = s.lower()
    if ";" in s:
        raise UnsafeSQLError("한 번에 하나의 SQL만 허용됩니다.")
    if not (low.startswith("select") or low.startswith("with")):
        raise UnsafeSQLError("SELECT 조회만 허용됩니다.")
    hit = set(re.findall(r"[a-z_]+", low)) & FORBIDDEN_KEYWORDS
    if hit:
        raise UnsafeSQLError(f"허용되지 않는 키워드: {', '.join(sorted(hit))}")
    used = set(re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", low))
    unknown = used - ALLOWED_TABLES
    if unknown:
        raise UnsafeSQLError(f"존재하지 않는 테이블: {', '.join(sorted(unknown))}")
    return s


def enforce_limit(sql: str, limit: int = DEFAULT_ROW_LIMIT) -> str:
    if re.search(r"\blimit\b", sql, re.IGNORECASE):
        return sql
    return f"{sql} LIMIT {limit}"


# ────────────────────────────────────────────────
# [조각 3] 출력 정리
# ────────────────────────────────────────────────
def _to_jsonable(v):
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return v


def format_result(sql: str, columns, rows, max_rows: int = DEFAULT_ROW_LIMIT) -> dict:
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    return {
        "sql": sql,
        "columns": columns,
        "rows": [[_to_jsonable(v) for v in row] for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }


# ────────────────────────────────────────────────
# [조각 4] 자연어 → SQL 생성 (Ollama)
# ────────────────────────────────────────────────
def _call_ollama(messages: list) -> str:
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": SQL_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(1)
    m = re.search(r"\b(?:select|with)\b.*", text, re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(0)
    return text.split(";")[0].strip()


def generate_sql(question: str, error_feedback: str = None) -> str:
    """자연어 질문 → SQL. error_feedback이 있으면 교정 요청으로 함께 보낸다."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    if error_feedback:
        messages.append({"role": "user", "content": error_feedback})
    return _extract_sql(_call_ollama(messages))


# ────────────────────────────────────────────────
# [조각 5] 조립 + 자가 교정 재시도
# ────────────────────────────────────────────────
def answer(question: str, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """자연어 질문에 답한다. 실패하면 에러를 피드백해 최대 max_attempts번 재시도."""
    feedback = None
    last_sql = None
    for attempt in range(1, max_attempts + 1):
        last_sql = generate_sql(question, feedback)
        try:
            safe = enforce_limit(validate_sql(last_sql))   # 검증 + 상한
            cols, rows = execute_sql(safe)                  # 실행
            result = format_result(safe, cols, rows)        # JSON
            result["attempts"] = attempt                    # 몇 번 만에 성공했는지
            return result
        except (UnsafeSQLError, psycopg.Error) as e:
            # 실패 → 에러를 다음 시도에 피드백 (자가 교정)
            feedback = (
                f"방금 생성한 SQL에 문제가 있었다:\n{last_sql}\n"
                f"에러: {e}\n"
                f"이 에러를 고쳐서 올바른 SELECT 쿼리 하나만 다시 출력하라."
            )
    return {
        "error": "여러 번 시도했지만 올바른 SQL을 생성하지 못했습니다.",
        "last_sql": last_sql,
        "attempts": max_attempts,
    }


# ────────────────────────────────────────────────
# 직접 실행 시 테스트
# ────────────────────────────────────────────────
if __name__ == "__main__":
    questions = [
        "2025년 3분기 총 매출액은 얼마야?",
        "현재 활성 상태인 계약 수는 몇 개야?",
        "평균 연봉이 가장 높은 부서는 어디야?",
    ]
    for q in questions:
        print("=" * 60)
        print("질문:", q)
        result = answer(q)
        if "error" in result:
            print("❌ 실패:", result["error"], "| 마지막 SQL:", result["last_sql"])
        else:
            print(f"✅ {result['attempts']}번 만에 성공")
            print("   SQL :", result["sql"])
            print("   결과:", result["rows"])
