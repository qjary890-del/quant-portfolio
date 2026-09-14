# Quant Portfolio — Mean Reversion

미국 대형주 유니버스에서 **통계적 차익거래**와 **횡단면 평균회귀**를 결합한 퀀트 포트폴리오 백테스트 프로젝트입니다.

---

## 가설

> 단기적으로 공정가치(또는 상대가치)에서 벗어난 가격·스프레드는 평균으로 회귀하며,  
> 그 수렴 구간에서 **시세차익(mean-reversion alpha)** 을 체계적으로 취할 수 있다.

| 슬리브 | 가설의 구현 | 시그널 |
|--------|-------------|--------|
| **Statistical Arbitrage** | 섹터·사업이 유사한 페어의 스프레드는 공적분 관계를 따르며, z-score 이탈 후 수렴한다 | 롤링 헤지비율 스프레드, \|z\| ≥ 2 진입 / ≤ 0.5 청산 / ≥ 4 손절 |
| **Cross-Sectional Mean Reversion** | 횡단면상 단기 과잉반응(급등·급락)은 수일 내 반전된다 | 5일 수익률 하위 20% 롱 / 상위 20% 숏, 5일 리밸런싱 |

두 슬리브를 기본 **50:50**으로 결합해 달러 중립에 가까운 북을 구성한다.

---

## 진행 방향

### 현재 상태 (Done)

- [x] 가설 정의 및 이중 슬리브 설계
- [x] yfinance 기반 일봉 수집·캐시
- [x] 페어 스프레드 z-score Stat Arb + 횡단면 평균회귀 시그널
- [x] 벡터화 백테스트 (익일 수익률 적용, commission/slippage bps)
- [x] 슬리브별·결합 성과(CAGR, Sharpe, MDD, turnover) 및 equity curve 산출

### 핵심 이슈와 해결 방향

| 구분 | 이슈 | 해결 방향 |
|------|------|-----------|
| **슬리피지·거래비용** | 5일 리밸런싱 시 연간 turnover가 높음. Borrow fee·스프레드·세금을 빼면 실전 손익이 반전될 수 있음 | 보수적 슬리피지(5~10bps), 숏 차입 이자(일일), 비용·turnover 분해 리포트 |
| **생존 편향** | 현재 TOP50으로 과거를 조회하면 상장폐지·탈락 종목이 빠져 수익이 과대평가됨 | Point-in-Time 유니버스(역사적 지수 구성 / Polygon·Norgate 등) |
| **숏 실행력** | 리테일·IBKR에서 대차 불가·차입비 급등 가능 | Hard-to-borrow 필터, borrow cap, 불가 시 롱온리/페어만 폴백 |
| **동적 비중** | VIX 급등 시 횡단면 롱숏 폭망 리스크 | Volatility targeting으로 슬리브 비중 조절 (고정 50:50 탈피) |

### 다음 단계 (Roadmap)

1. **데이터 수집·정제** — 2018~현재 대형주 일봉 안정화, 결측·조정주가 검증, (가능 시) PIT 유니버스 도입  
2. **페어 선정·공적분 테스트** — XOM–CVX, JPM–BAC 외에 섹터별 후보(Tech, Semi 등) Engle-Granger / Johansen p-value, rolling 안정성 검증  
3. **거래비용 포함 백테스트 고도화** — 슬리피지·수수료·borrow fee 반영 후 슬리브별 Sharpe·MDD·연환산 turnover 재측정  
4. **실전 제약·리스크** — 숏 가능 종목만 편입, VIX 기반 동적 비중, 드로다운 한도

---

## 프로젝트 구조

```
quant/
├── config.py              # 유니버스, 페어, 파라미터, 비용
├── run_backtest.py        # 엔드투엔드 실행
├── utils.py
├── data/loader.py         # 가격 다운로드·캐시
├── strategies/
│   ├── stat_arb.py        # 통계적 차익거래
│   └── mean_reversion.py  # 횡단면 평균회귀
├── backtest/engine.py     # 백테스트·슬리브 결합
└── output/                # equity, weights, 차트 (gitignore)
```

## 설치 · 실행

```bash
pip install -r requirements.txt
python run_backtest.py
```

| 산출물 | 내용 |
|--------|------|
| `output/equity_curves.png` | 슬리브·결합 자산곡선 |
| `output/*_equity.csv` | 일별 자산 |
| `output/latest_combined_weights.csv` | 최신 결합 비중 |

파라미터는 `config.py`에서 조정합니다.

## 백테스트 주의사항

- 룩어헤드 완화: **당일 종가 비중 → 익일 수익률**에 적용
- 공매도 차입비·배당·세금·유동성 제약은 아직 단순화되어 있음
- 과거 성과는 미래 수익을 보장하지 않음
