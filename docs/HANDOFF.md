# 인수인계 문서 — 로컬 환경으로 이어가기

작성: 2026-10-15 (클라우드 세션 종료 시점). 다음 작업자(사람 또는 Claude)는 이 문서만 읽으면 이어갈 수 있도록 썼다.

---

## 0. 한 줄 요약

**목표:** 한국투자증권 2026 하반기 신입 공채 **AI/디지털/정보보호** 직무 지원(접수 마감 10/19경, 원문 확인 필요).
증권 경험이 없는 지원자가 "왜 한투인가"를 증명할 **4일짜리 프로젝트**를 만든다.
**주제:** 「KIS API·DART 기반 기업금융 사후 모니터링 조사 Agent」 — IMA 사업을 공부하다 "투자한 기업의 회수 가능성을 계속 확인하는 업무"에 관심이 생겨, 그 업무를 공개 데이터로 시뮬레이션했다는 서사.
**현재 상태:** 코드 뼈대 완성·테스트 통과·GitHub push 완료. **키가 없어 실데이터는 아직 한 번도 안 돌렸다.** 2일차(실데이터)부터 로컬에서 진행.

---

## 1. 지원 서사 (자소서·면접의 뼈대)

> AI 에이전트(GAPAGO: 논문 원문에서 근거 있는 한계점을 뽑고 검증해 리포트로 만드는 멀티 에이전트, 2026 AI Co-Scientist Challenge 우수상)를 만들어 본 사람으로서, 한투가 "금융 라이선스를 가진 테크 기업"을 내걸고 본부별 AI 활용을 KPI 에 넣는 것을 보고 관심이 생겼다. 어느 업무에 AI 가 쓰여야 하는지 알고 싶어 올해 핵심 신사업인 IMA 를 공부했고, 투자 후 사후관리가 "근거를 찾아 조사하는 일"이라는 점에서 내가 해온 일과 닿아 있다고 느꼈다. 그래서 DART·KIS API 로 사후 모니터링 조사 Agent 를 직접 만들었다. 입사하면 디지털혁신본부에서 IMA·IB·리스크 같은 현업의 AI 어시스턴트를 만드는 일에 기여하고 싶다.

**주의할 표현**
- "IMA 투자 대상 기업의 부실을 예측했다" ✗ → "IMA 사후관리 업무를 이해하기 위해 공개 데이터로 모니터링 메모를 만들고 사례를 복기했다" ✓
- GAPAGO 와 "구조가 같다"로 끝내지 말 것. **금융을 이해하려고 새로 배운 것**(근거와 상환능력의 관계, 현금흐름·차입금 만기·자금조달을 함께 읽는 기준, 공개 자료로 판단 불가한 항목 식별)을 덧붙일 것.
- 조직명·수치는 `docs/business_notes.md` 의 `[확인 필요]` 항목을 원문으로 확인한 뒤 사용. 기준수익률은 목표이지 확정 수익률이 아님.
- "심사역"이 아니라 "기업금융 투자자산 모니터링 담당자(가정)".

---

## 2. 지금까지의 결정 과정 (왜 이 주제인가)

| 단계 | 내용 |
|---|---|
| 주제 탐색 | 흔한 주식 예측·종목 추천 제외. 한투 API 활용 주제 다수 검토 |
| 한투 현황 조사 | 2026 신년사 'Beyond Boundaries'(자본·국경·업). **IMA** 가 CEO 레벨 핵심, 디지털 조직은 AI PB·AI 트레이더·**AI 어시스턴트**·AI 파운데이션 4대 분야, 본부별 AI KPI, 에이전틱 WM 구상 |
| 1차 안: IMA 신용위험 조기경보 모델 | 외부 피드백: "부실 예측 모델에 IMA 를 붙인 것"으로 보임. 금융사는 이미 조기경보를 운영함 (신한 AI 신용공여 지킴이, 수협 Creditracker 등) |
| 전수 조사 | 한투 기존 서비스·KIS API 334개·MCP·경쟁사·제도 변화·미해결 불편 조사 → `docs/research/hantu_unsolved_problems_report.md` |
| 2차 후보: NXT 체결 품질 / API 신뢰성 관측 / 상폐 카운트다운 | 기술 차별성은 있으나 "지원 동기·사업 관심"을 설명하기엔 약함 (피드백) |
| **최종:** IMA 기업금융 **투자 후 모니터링** 업무 시뮬레이션 Agent | 관심 사업 → 이유 → 구체 업무 → 공개 데이터로 경험 → KIS+AI 활용 순서로 재구성. 기존 업무여도 됨. 차별성은 다룬 깊이와 본인 판단에서 |

**핵심 설계 결정 (피드백 반영)**
1. 부실 예측 성능 ✗ → "이전 점검 대비 **변화 보고서**" + 추가 확인 사항
2. **상환능력 신호 / 시장 신호 분리**, 엇갈리는 사례 분석이 핵심 판단
3. 자금조달 **'결정' ≠ '완료'** — 납입·발행실적 공시 확인 전엔 조달 완료라 쓰지 않음
4. **기준일(as-of) 고정** — 모든 도구가 기준일 이전 접수분만 반환 (사후 지식 차단)
5. 숫자는 코드, LLM 은 근거 id 로 인용만, 검증 코드가 대조
6. 단일 Agent + 도구 4개 (멀티에이전트 불필요). 도구 호출 경로가 신호에 따라 달라지는 것이 "Agent" 의 근거
7. 평가는 보고서 품질이 아니라 **조사 행동** (5개 루브릭 + 도구 없는 대조군 비교)

---

## 3. 저장소 상태

- GitHub: https://github.com/HwangJae-won/ima-monitor-agent (main, 공개)
- 커밋: 초기 구현 → 예외 체이닝 → API 확장 메모 → 프록시 인증 모드 → (이 문서)
- 테스트 12건 통과(`pytest`), `ruff check` 통과. 코드 약 2,100줄.

| 경로 | 역할 |
|---|---|
| `monitor/kis_client.py` | KIS 조회 전용 (주문 모듈 없음). 토큰 캐시·초당 제한·EGW00201 백오프·응답 캐시. `KIS_AUTH_MODE=env|proxy` |
| `monitor/dart_client.py` | OpenDART: 공시 목록, 단일회사 전체 재무제표, 주요사항보고서 14종, 채무증권 신고서. rcept_no 앞 8자리=접수일 |
| `monitor/tools.py` | 도구 4종: `get_financial_snapshot`, `get_disclosures`, `get_market_signals`, `check_funding_completion`. 전부 as-of 필터, 근거 id |
| `monitor/signals.py` | 변화 탐지 (repayment / market), 패턴 both·repayment_only·market_only |
| `monitor/agent.py` | 조사 Agent 루프 (최대 6스텝, 종목·기준일 고정, trace). 시스템 프롬프트에 업무 원칙 |
| `monitor/verify.py` | 메모 검증: 근거 id·숫자·단정 표현·'조달 완료' 표현 |
| `monitor/report.py` | 담당자용 마크다운 메모 (8개 섹션) |
| `monitor/llm.py` | `LLM_PROVIDER=azure|azure_proxy|openai` |
| `scripts/run_monitor.py` | 1건 실행 → `reports/<code>/<asof>_memo.md` + `trace_<asof>.json` |
| `scripts/run_case.py` | 사례 복기 (여러 기준일) → `timeline.md` |
| `scripts/baseline.py` | 대조군 (도구 없음) → `<asof>_baseline.md` |
| `scripts/build_universe.py` | 채권·CB 로 조달한 비금융 상장사 후보 CSV |
| `tests/` | 가짜 KIS·DART 로 as-of·완료 추적·신호·검증 테스트 |
| `docs/business_notes.md` | IMA 사업 공부 노트 (5개 질문, `[확인 필요]` 표시) |
| `docs/kis_api_gaps.md` | KIS API 확장 가능 영역 (자소서용, 사실/의견 구분) |
| `docs/kis_api_bug_notes.md` | 공식 샘플 저장소 결함 (ETF 구성종목 chk COLUMN_MAPPING 오염) — PR 후보 |
| `docs/research/hantu_unsolved_problems_report.md` | 한투 전수 조사 보고서 (사업부 구조·기존 서비스·API·경쟁사·제도·미해결 문제·수치 재검증 목록) |
| `docs/research/archive_plan_v2_credit_monitor.md` | 폐기된 1차 안(신용위험 조기경보) 계획. 참고용 |

**알려진 미확인 사항 (실데이터로 처음 돌릴 때 확인)**
- KIS 일봉 `FID_ORG_ADJ_PRC` 0/1 의미 (샘플 docstring: 0=수정주가, 커뮤니티: 반대 보고)
- 상장폐지 종목의 과거 일봉 조회 가능 여부 (복기 사례 선정에 영향)
- DART `fnlttSinglAcntAll` 의 계정명이 `_ACCOUNTS` 동의어와 맞는지 (안 맞으면 `missing_accounts` 에 나옴 → 동의어 추가)
- 분기 보고서 IS/CF 의 누적(`thstrm_add_amount`) vs 당기 선택 로직
- KIS `investor-trade-by-stock-daily`, `daily-short-sale` 의 1회 반환 행 수
- 주요사항보고서 API 응답 필드명 (`_key_fields` 휴리스틱이 거칠 수 있음)

---

## 4. 로컬 시작 절차

```bash
git clone https://github.com/HwangJae-won/ima-monitor-agent && cd ima-monitor-agent
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env     # 편집기로 열어 아래 값 채우기 (채팅·커밋 금지)
python -m pytest         # 12 passed 확인
```

`.env` 에 채울 것 (로컬은 전부 env 모드)
```
KIS_AUTH_MODE=env
KIS_APP_KEY=...          # KIS Developers 실전투자 앱키 (주문도 가능한 키 → 계좌 비밀번호급으로 관리)
KIS_APP_SECRET=...
KIS_ENV=prod
DART_API_KEY=...         # opendart.fss.or.kr 즉시 발급
LLM_PROVIDER=azure       # GAPAGO 와 같은 Azure OpenAI
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://<리소스>.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=<배포명>
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

연결 확인 (각각 한 줄)
```bash
python -c "from monitor.dart_client import DARTClient as D; print(D().corp_by_stock('005930'))"
python -c "from monitor.kis_client import KISClient as K; print(K().daily_prices('005930','20251001','20251015')[-1])"
python -c "from monitor.llm import LLM; print(LLM().complete([{'role':'user','content':'ping'}], force_text=True)['content'][:40])"
```

---

## 5. 남은 일정 (10/15 저녁 기준)

| 날짜 | 작업 | 산출물 | 명령 |
|---|---|---|---|
| **10/16 (목)** | 연결 확인 → 후보 기업 CSV → 10곳 선정(위험 신호 6~7 + 평범 3~4) → 10곳 메모 생성 → 미확인 사항 수정 | `data/universe_candidates.csv`, `reports/<code>/<asof>_memo.md` ×10 | `python scripts/build_universe.py --months 18` → `python scripts/run_monitor.py --code <code> --asof 20251015` |
| **10/17 (금)** | 복기 사례 1곳(2025년 회생 신청 또는 감사의견 거절 기업) 기준일 4~5개로 실행 → 대조군 실행 → 루브릭 채점표 | `reports/<code>/timeline.md`, `<asof>_baseline.md`, `docs/evaluation.md` | `python scripts/run_case.py --code <code> --dates 20240630,20240930,20241231,20250331` / `python scripts/baseline.py --code <code> --asof <date>` |
| **10/18 (토)** | README 결과물 섹션(메모 예시·타임라인·루브릭 표), 수치 원문 재확인, KIS 저장소 버그 PR, 자소서 2~3문장 | README, PR, 자소서 문장 | — |
| 10/19 | 제출 | | |

**루브릭 (docs/evaluation.md 로 만들 것)** — 사례별 ○/△/✗
1. 필요한 공시를 찾아냈는가 (정답 공시 목록을 먼저 만들고 trace 와 대조)
2. 차환·증자 계획을 조달 완료로 오해하지 않았는가
3. 주가 하락을 상환능력 악화로 단정하지 않았는가
4. 근거 부족 시 추가 조회하거나 보류했는가 (open_items 의 질)
5. 도구 없는 대조군보다 누락·오류가 적은가

**대상 기업 선정 이유** (물어보면): IMA 는 기업금융 자산 70% 이상 → 회사채·CB 발행 기업이 "증권사가 자금을 공급하는 기업군"에 가장 가까움. 비금융(재무구조 상이), 상장사(KIS 시세·DART 충실), 최근 18개월(결정→완료 추적이 작동), 10곳(사람이 채점 가능한 상한), 평범한 기업 포함(오경보 확인).

---

## 6. 부수 작업 상태

| 항목 | 상태 |
|---|---|
| GAPAGO 모바일 흰 화면 | 원인: Render 무료 플랜 512MB 에서 시작 시 모델 프리로드 → OOM 재시작 루프 + 슬립 깨어남 지연. 모바일은 빈 502/503 을 흰 화면으로 표시. 수정 PR: https://github.com/Coding-Maengsu/gapago/pull/125 (`PRELOAD_MODELS` 옵트인). **머지 대기**. 머지 후 Render 로그에 `Model preload skipped` → `Warm-up complete.` 확인 |
| GAPAGO CI/CD + Cloud Run | 계획만 세움(Dockerfile 모델 포함, JSON 구조화 로그, GitHub Actions→Artifact Registry→Cloud Run, WIF). **착수 안 함.** 이번 공채엔 불필요, 면접 전 확장 과제 |
| KIS 샘플 저장소 버그 PR | `docs/kis_api_bug_notes.md`. 10/18 에 제출 예정 (Issues 비활성, PR 만 가능) |
| 채용 정보 | 2026 하반기 5급 공채 IT/Digital 이 '개발/운영'과 'AI/디지털/정보보호'로 분리. 전형: 서류→직무역량평가→AI면접→1·2차→최종. 자소서는 성장과정 500자·실패극복 300자 중심이라는 조사 결과(원문 미확인). **실제 문항 확보 후 README 강조점 조정 (사용자가 '추후'로 미룸)** |

---

## 7. 다음 세션에 붙여넣을 컨텍스트 프롬프트

```
한국투자증권 2026 하반기 신입 공채(AI/디지털/정보보호, 10/19 마감)용 프로젝트를 진행 중이야.
저장소: HwangJae-won/ima-monitor-agent. 먼저 docs/HANDOFF.md 를 읽고 이어가 줘.
오늘은 <날짜>이고, 로컬에 .env(키)가 준비돼 있어. 오늘 할 일은 HANDOFF 5장의 <날짜> 행이야.
규칙: 키는 절대 출력하지 말 것, 주문 API 는 쓰지 말 것, 수치는 기준 시점·출처와 함께, "IMA 투자 대상을 예측했다"식 과장 금지.
```
