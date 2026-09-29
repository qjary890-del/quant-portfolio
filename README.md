# Quant Portfolio — Mean Reversion

미국 대형주 유니버스에서 **통계적 차익거래**와 **횡단면 평균회귀**를 결합한 퀀트 포트폴리오 백테스트 프로젝트입니다.

---

## 가설

> 단기적으로 공정가치(또는 상대가치)에서 벗어난 가격·스프레드는 평균으로 회귀하며,  
> 그 수렴 구간에서 **시세차익(mean-reversion alpha)** 을 체계적으로 취할 수 있다.

| 슬리브 | 가설의 구현 | 시그널 |
|--------|-------------|--------|
| **Statistical Arbitrage** | 섹터·사업이 유사한 페어의 스프레드는 공적분 관계를 따르며, z-score 이탈 후 수렴한다 | 롤링 헤지비율 스프레드, \|z\| ≥ 2.5 진입 / ≤ 0.5 청산 / ≥ 4 손절 |
| **Cross-Sectional Mean Reversion** | 횡단면상 단기 과잉반응(급등·급락)은 수일 내 반전된다 | 5일 수익률 하위 20% 롱 / 상위 20% 숏, 5일 리밸런싱 |

두 슬리브를 비교·검증한 뒤, **본선은 Statistical Arbitrage**로 둔다.  
매크로 쇼크(바스켓 급락·vol 스파이크)와 북 고점 대비 −12% 드로다운 시 즉시 플랫하는 가드를 붙인다.  
Cross-Sectional MR은 위성·비교용으로 유지한다.

---

## 진행 방향

### 현재 상태 (Done)

- [x] 가설 정의 및 이중 슬리브 설계
- [x] yfinance 제거 → Stooq EOD(기본) / Tiingo(API키) 가격
- [x] pitindex 기반 S&P500 Point-in-Time 유니버스 (생존 편향 완화)
- [x] 페어 스프레드 z-score Stat Arb + 횡단면 평균회귀 시그널
- [x] 벡터화 백테스트 (익일 수익률 적용, commission/slippage bps)
- [x] 슬리브별·결합 성과(CAGR, Sharpe, MDD, turnover) 및 equity curve 산출
- [x] 보수적 슬리피지 + 숏 borrow fee + 연간 비용/turnover 분해 리포트
- [x] 섹터별 Engle-Granger 공적분 페어 자동 스크리닝 (formation OOS)
- [x] 롤링 페어 갱신 + 거시 회복력(resilience) 지표로 슬리브 선정
- [x] Stat Arb 본선 + 매크로 쇼크 브레이커 + 북 DD 손절 (기본 북)
- [x] 북 DD 손절 재무장(re-arm) 버그 수정
- [x] 유니버스 50 → 200종목 확장 + 탈락 종목 GICS 섹터 보완
- [x] 파라미터 스윕 도구 + 표본외 검증 → **튜닝값 미채택, 기본 논리·파라미터 유지**

### 시행착오 기록

기본 논리(롤링 공적분 페어 + z-score 진입/청산/손절 + 쇼크·북DD 가드)와 파라미터는
과최적화 이전 값(entry 2.5 / exit 0.5 / stop 4.0, 페어 24개·섹터당 3개, 북DD −12%/15일)으로 유지한다.
아래는 그 결론에 이르기까지의 실험 기록이다.

**현재 기본값 성과 (200종목, 2018-01~2026-09, 비용 포함)** — 튜닝하지 않은 정직한 기준선

| 북 | CAGR | Sharpe | MDD | Turnover |
|----|------|--------|-----|----------|
| Stat Arb + Shock + BookDD (기본 북) | −7.6% | −0.67 | −57.0% | 33.0x |
| Stat Arb (가드 없음) | −9.2% | −0.69 | −62.4% | 38.0x |
| Cross-Sectional MR | −1.8% | −0.41 | −20.9% | 8.2x |

높은 turnover(연 30배 이상 → 거래비용만 연 약 5%)가 가장 큰 손실 요인. 다음 과제는 파라미터가 아니라 거래 빈도·구조 개선.

**1. 스윕 경로 불일치 수정**
- 실전 백테스트는 재선정마다 약 25일 비는 별도 빌더를, 스윕은 다른 빌더를 써서 결과가 달랐음
- 실전도 스윕과 같은 `weights_from_pair_log`를 쓰도록 통일 → 두 경로 수치 일치 확인

**2. 북 DD 손절 버그 (가장 중요한 발견)**
- 고점이 한 번도 재설정되지 않아, 원본 북이 고점을 회복 못 한 2021-02 이후 **5년 넘게 영구 flat**
- 이전 "기본 북 CAGR −0.74%"는 실제로 약 13개월 매매 결과였고, 그 위에서 고른 z·페어 수도 무의미했음
- 수정: 쿨다운이 끝나는 시점의 수준에서 고점을 재설정 (`strategies/regime.py`)

**3. 탈락 종목 섹터 누락**
- 2018년 S&P500 멤버 중 146개(대부분 이후 탈락)가 pitindex에 섹터 정보가 없어 "Unknown" 한 그룹으로 묶임
  → 항공·자동차부품·보험 같은 무관한 종목끼리 페어 후보가 됨
- 수정: GICS 섹터 수동 매핑 (`data/pit_sector_overrides.py`). 탈락 종목을 버리지 않아 생존 편향도 완화

**4. 유니버스 확장 (50 → 200종목)**
- 50종목에서는 재선정 시점의 페어 후보가 2–5개뿐 (2024–25년엔 거의 0)
- 2018-01 멤버 중 시드 이후 GICS 섹터를 번갈아 선택 (`pit_price_tickers`, 미래 정보 미사용)
- `fetch_universe.py`로 Tiingo 무료 한도(시간당 50회) 내 사전 다운로드. 가격 확보 185종목(티커 변경 8개는 무료 데이터 없음)
- 200종목에서는 매 재선정마다 11개 섹터 전체에서 후보 풀 48개 확보

**5. 파라미터 스윕과 과최적화**
- 단계별 스윕(`run_cagr_sweep.py`): z → 페어 수·섹터 캡 → 시간손절 → 북DD → 가드 → formation/refresh → 1차 분류
- 전체 기간 튜닝: 200종목 CAGR +7.5%, Sharpe 0.63, MDD −23.7% — 그러나 수익이 2025(+36%)·2026(+14%)에 집중
- 표본외 검증(`--select-until 2023-05-10`, `NEUTRAL_START` = entry 2.5 / exit 0.25 / stop 5.0, 페어 8개·섹터당 3개에서 시작):

| 설정 | 학습 2020-01~2023-05 | 보류 2023-05~2026-09 | 보류 MDD |
|------|------|------|------|
| 학습 구간에서 고른 설정 | CAGR +14.1% | **CAGR −14.8%** | −44.1% |
| 시작값(`NEUTRAL_START`) | CAGR −18.5% | CAGR −8.0% | −25.0% |

- 학습 구간 최적값일수록 보류 구간에서 더 나빴고, 최적 설정이 구간마다 뒤집힘(진입 2.0·페어 4개 vs 3.0·16개)
- 결론: 튜닝값은 시기별 우연을 따라감 → **채택하지 않음**. 현재 구조에는 견고한 엣지가 확인되지 않음

**6. 페어 후보 1차 분류 실험 (모두 미채택)**
- 자본구조(순차입금/EBITDA 등) 필터: 롤링 OOS에서 개선 없음 + 회계 데이터 도입은 신중해야 한다고 판단해 제외
- 수익률 상관 군집(`PRIMARY_GROUPING`): 50·200종목 모두 섹터 그대로보다 나빠 기본 off

### 핵심 이슈와 해결 방향

| 구분 | 이슈 | 해결 방향 |
|------|------|-----------|
| **슬리피지·거래비용** | 5일 리밸런싱 시 연간 turnover가 높음. Borrow fee·스프레드·세금을 빼면 실전 손익이 반전될 수 있음 | ✅ 슬리피지 10bps + 연 1.5% borrow + 비용/turnover 분해 (세금은 후순위) |
| **생존 편향** | 현재 TOP50으로 과거를 조회하면 상장폐지·탈락 종목이 빠져 수익이 과대평가됨 | ✅ pitindex S&P500 PIT 멤버십 + 일자별 적격 종목 필터. 상장폐지 **가격**은 무료 API 한계로 부분 커버(Tiingo/Norgate로 고도화 가능) |
| **숏 실행력** | 리테일·IBKR에서 대차 불가·차입비 급등 가능 | Hard-to-borrow 필터, borrow cap, 불가 시 롱온리/페어만 폴백 |
| **동적 비중** | VIX 급등 시 횡단면 롱숏 폭망 리스크 | ✅ 실현vol regime + 쇼크 브레이커 + 북 DD 손절 (Stat Arb 기본) |

### 다음 단계 (Roadmap)

1. **데이터 수집·정제** — ✅ Stooq/Tiingo + PIT 멤버십; 상장폐지 시세 완전 커버는 유료 데이터로 확장  
2. **페어 선정·공적분 테스트** — ✅ 섹터 내 후보 Engle-Granger p-value + half-life + rolling 안정성, formation 이후 매매  
3. **거래비용 포함 백테스트 고도화** — ✅ 기본 비용 모델 반영; 파라미터·유니버스 재측정은 계속  
4. **실전 제약·리스크** — ✅ 쇼크/북DD 가드·합의 스케일; 숏 가능 여부·VIX 캡은 추가 가능

---

## 프로젝트 구조

```
quant/
├── config.py              # PIT/데이터 소스, 파라미터, 비용
├── run_backtest.py        # 엔드투엔드 실행
├── utils.py
├── data/
│   ├── loader.py          # Stooq / Tiingo 가격
│   ├── providers.py       # 프로바이더 구현
│   ├── universe_pit.py    # pitindex S&P500 PIT 멤버십 + 가격 유니버스 선택
│   └── pit_sector_overrides.py  # 탈락 종목 GICS 섹터 보완
├── strategies/
│   ├── pair_screener.py   # 공적분 페어 자동 선정
│   ├── rolling_pairs.py   # 롤링 formation/refresh
│   ├── stat_arb.py        # 통계적 차익거래
│   ├── mean_reversion.py  # 횡단면 평균회귀
│   ├── hybrid.py          # 합의 스케일·슬리브 믹스
│   ├── regime.py          # vol regime / 쇼크 / 북 DD
│   └── universe_structure.py  # 페어 후보 1차 분류 (수익률 상관 군집, 기본 off)
├── backtest/
│   ├── engine.py          # 백테스트·슬리브 결합
│   └── resilience.py      # 거시 회복력 순위
└── output/                # equity, weights, 차트 (gitignore)
```

## 설치 · 실행

```bash
pip install -r requirements.txt
python run_backtest.py
python run_z_sweep.py          # Stat Arb z/lookback 그리드 (페어 스케줄 고정)
python run_pair_cap_sweep.py   # max_pairs → max_per_sector 순 스윕
python fetch_universe.py       # PIT 유니버스 가격 사전 다운로드 (Tiingo 무료 한도 페이싱, 재실행 가능)
python run_cagr_sweep.py       # 단계별 CAGR 스윕 (--names N, --baseline-only, --select-until 날짜 = 표본외 검증)
```

가격 소스 (**Tiingo만 지원** — Yahoo/Stooq 제외):

1. https://www.tiingo.com/account/api/token 에서 무료 토큰 발급  
2. 프로젝트 루트에 `.env` 생성:

```bash
TIINGO_API_KEY=your_token_here
```

3. 실행:

```bash
pip install -r requirements.txt
python run_backtest.py
```

`PIT_PRICE_UNIVERSE=asof_start` + `PIT_MAX_PRICED_NAMES=200`(기본)입니다. Tiingo 무료 한도(시간당 50회)에 맞춰  
처음 한 번 `python fetch_universe.py`로 가격을 캐시에 받아 두세요(약 2.5시간, 중단 후 재실행 가능).  
일자별 S&P500 편입/편출 필터(pitindex)는 그대로 적용되고, 가격을 받는 종목 수만 제한합니다.

| 산출물 | 내용 |
|--------|------|
| `output/equity_curves.png` | 슬리브·결합 자산곡선 |
| `output/*_equity.csv` | 일별 자산 |
| `output/coint_pairs.csv` | 공적분 스크리닝 통과 페어 |
| `output/pit_coverage.csv` | PIT 멤버 대비 가격 커버리지 |
| `output/latest_combined_weights.csv` | 최신 결합 비중 |

파라미터는 `config.py`에서 조정합니다.

## 백테스트 주의사항

- 룩어헤드 완화: **당일 종가 비중 → 익일 수익률**에 적용
- 거래비용: commission + slippage(bps)×turnover, 숏 노셔널에 연환산 borrow fee/252
- 유니버스: 그날 S&P500 멤버만 매매 가능(pitindex). 상장폐지 종목의 과거 시세는 무료 소스에서 빠질 수 있음
- 종목별 hard-to-borrow·배당·세금·유동성 한도는 아직 단순화되어 있음
- 과거 성과는 미래 수익을 보장하지 않음
