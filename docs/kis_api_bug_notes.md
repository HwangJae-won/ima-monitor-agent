# KIS open-trading-api 결함 기록 (PR 후보)

## 1. ETF 구성종목시세 chk 파일의 COLUMN_MAPPING 오염

- **발견일:** 2026-10-15
- **저장소:** https://github.com/koreainvestment/open-trading-api
- **파일:** `examples_llm/etfetn/inquire_component_stock_price/chk_inquire_component_stock_price.py` (22~49행)
- **상태:** 미수정, PR 미제출

### 증상
`COLUMN_MAPPING`의 키(API 응답 필드명)는 ETF 구성종목시세 API의 것이지만, 값(한글 라벨)은 **신용잔고 일별추이 API**의 라벨이 한 칸씩 밀려 붙어 있음. 다른 API의 chk 파일을 복사한 뒤 라벨을 고치지 않은 것으로 보임.

| 필드 | 현재 라벨 (잘못됨) | 실제 의미 (추정, 공식 문서로 확인 필요) |
|---|---|---|
| `stck_prpr` | 매매 일자 | 주식 현재가 |
| `prdy_vrss` | 주식 현재가 | 전일 대비 |
| `prdy_vrss_sign` | 전일 대비 부호 | (정상) |
| `prdy_ctrt` | 전일 대비 | 전일 대비율 |
| `etf_cnfg_issu_avls` | 전일 대비율 | ETF 구성종목 시가총액 |
| `nav` | 누적 거래량 | NAV |
| `nav_prdy_vrss_sign` | 결제 일자 | NAV 전일 대비 부호 |
| `nav_prdy_vrss` | 전체 융자 신규 주수 | NAV 전일 대비 |
| `nav_prdy_ctrt` | 전체 융자 상환 주수 | NAV 전일 대비율 |
| `etf_ntas_ttam` | 전체 융자 잔고 주수 | ETF 순자산 총액 |
| `prdy_clpr_nav` | 전체 융자 신규 금액 | 전일 종가 NAV |
| `oprc_nav` | 전체 융자 상환 금액 | 시가 NAV |
| `hprc_nav` | 전체 융자 잔고 금액 | 고가 NAV |
| `lprc_nav` | 전체 융자 잔고 비율 | 저가 NAV |
| `etf_cu_unit_scrt_cnt` | 전체 융자 공여율 | ETF CU 단위 증권 수 |
| `etf_cnfg_issu_cnt` | 전체 대주 신규 주수 | ETF 구성종목 수 |

`stck_shrn_iscd`(39행) 이후 output2(구성종목 목록) 매핑은 정상.

### 영향
- 핵심 API 함수 `inquire_component_stock_price.py`는 정상. 데이터는 맞게 오고 **표시 라벨만** 틀림.
- chk 파일을 그대로 실행하면 NAV가 "누적 거래량", 순자산총액이 "전체 융자 잔고 주수"로 출력됨.
- `NUMERIC_COLUMNS`(52~56행)도 같은 잘못된 라벨을 참조하므로 함께 수정 필요.

### 수정 절차
1. KIS Developers 문서에서 "ETF 구성종목시세" API 응답 명세(output1) 한글 필드명 확인
2. `COLUMN_MAPPING`과 `NUMERIC_COLUMNS` 수정
3. 같은 유형의 복사 오류가 다른 chk 파일에도 있는지 전수 점검 (Code Assistant MCP `data.csv`의 column_mapping과 자동 대조하면 됨)
4. PR 제출 (저장소 Issues 탭 비활성화 상태, PR만 가능)

### 활용
- 추천 주제 3(KIS API 신뢰성 관측·명세 회귀 테스트)의 첫 사례
- 자소서·면접: "공식 저장소 결함을 직접 발견해 PR 제출" 근거
