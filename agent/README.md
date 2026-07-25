# ④ LLM 에이전트 파트 (작업 예정)

Ollama 소형 LLM(Gemma 3 4B ~ Qwen 2.5 KO 7B)을 MCP 클라이언트로 연동해
"질문 → 라우터 → MCP 도구 호출 → 답변 생성" 전체 흐름을 완성하는 파트.

## 범위

- Ollama 모델 선정 (한국어 성능 비교: Gemma 3 4B vs Qwen 2.5 KO 7B급)
- MCP 클라이언트 연동 (② MCP 서버의 3종 도구 호출)
- ③ 라우터와 결합해 end-to-end 질의응답 데모
- `os_dataset/questions.json` 30문항으로 최종 답변 품질 검증

## 주의: 소형 LLM 컨텍스트 제약

도구 응답이 컨텍스트를 잠식하지 않도록 시스템 전반에 상한이 설계되어 있음
(`vector_search`는 청크 ≤ 500토큰 × top_k ≤ 10 강제).
프롬프트 설계 시 근거는 `vector-db/docs/design.md`의
"소형 LLM 제약을 고려한 응답 설계" 섹션 참고.
