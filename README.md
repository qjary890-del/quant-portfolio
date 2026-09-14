# Mean-Reversion Quant Portfolio

통계적 차익거래(페어) + 횡단면 평균회귀로 **평균 회귀 시세차익**을 백테스트합니다.

## 전략 요약

| 슬리브 | 아이디어 | 진입 |
|--------|----------|------|
| Statistical Arb | 유사 종목 스프레드가 벌어지면 수렴에 베팅 | \|z\| ≥ 2 진입, \|z\| ≤ 0.5 청산, \|z\| ≥ 4 손절 |
| Cross-Sectional MR | 최근 낙폭 과대 종목 롱 / 급등 종목 숏 | 5일 수익률 기준 하위·상위 20%, 5일마다 리밸런싱 |

두 슬리브를 `config.py`의 가중치(기본 50:50)로 합쳐 달러 중립에 가까운 포트폴리오를 만듭니다.

## 설치

```bash
pip install -r requirements.txt
```

## 실행

```bash
python run_backtest.py
```

결과물:

- `output/equity_curves.png` — 슬리브·결합 자산곡선
- `output/*_equity.csv` — 일별 자산
- `output/latest_combined_weights.csv` — 최신 결합 비중

## 설정

`config.py`에서 유니버스, 페어, lookback, z-score, 비용(bps)을 바꿀 수 있습니다.

## 주의

- 룩어헤드를 줄이기 위해 **당일 종가 비중 → 익일 수익률**에 적용합니다.
- 공매도·차입 비용, 배당, 서킷브레이커는 단순화되어 있습니다.
- 과거 성과는 미래 수익을 보장하지 않습니다.
