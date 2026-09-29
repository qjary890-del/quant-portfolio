"""
Pre-fetch the PIT price universe into the local cache at a pace that stays
under the Tiingo free tier (50 requests/hour). Safe to stop and re-run:
cached names are skipped.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from data.providers import cached_tiingo_tickers, load_price_frame
from data.universe_pit import pit_price_tickers

PAUSE_SEC = 75  # 48 requests/hour


def main() -> None:
    tickers = pit_price_tickers(
        config.START,
        index=config.PIT_INDEX,
        max_names=int(config.PIT_MAX_PRICED_NAMES),
        seed=config.UNIVERSE,
    )
    cached = set(cached_tiingo_tickers(config.START, config.END))
    need = [t for t in tickers if t not in cached]
    print(f"Universe {len(tickers)} names: cached {len(tickers) - len(need)}, to fetch {len(need)}")
    print(f"ETA ~{len(need) * PAUSE_SEC / 3600:.1f} h at {3600 // PAUSE_SEC} requests/hour")

    empty = []
    for i, t in enumerate(need, 1):
        try:
            load_price_frame([t], config.START, config.END, pause_sec=0)
            status = "ok"
        except RuntimeError:
            empty.append(t)
            status = "no data"
        print(f"  [{i}/{len(need)}] {t}: {status}", flush=True)
        if i < len(need):
            time.sleep(PAUSE_SEC)

    print(f"Done. No data for {len(empty)}: {empty}")


if __name__ == "__main__":
    main()
