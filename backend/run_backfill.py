"""
백필 실행 스크립트
사용법:
  py -3.12 -m poetry run python run_backfill.py KBO 2022-04-02 2024-10-31
  py -3.12 -m poetry run python run_backfill.py MLB 2022-04-07 2024-09-29
  py -3.12 -m poetry run python run_backfill.py NPB 2022-03-25 2024-10-27
"""
import asyncio
import logging
import os
import sys
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

if __name__ == "__main__":
    league = sys.argv[1].upper() if len(sys.argv) > 1 else "KBO"

    # 리그별 기본 날짜
    defaults = {
        "KBO": (date(2025, 3, 22), date(2025, 11, 1)),
        "MLB": (date(2025, 3, 27), date(2025, 9, 28)),
        "NPB": (date(2025, 3, 28), date(2025, 10, 26)),
    }
    default_start, default_end = defaults.get(league, defaults["KBO"])

    start = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else default_start
    end   = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else default_end

    # LEAGUE 환경변수 설정 (settings.league 참조)
    os.environ["LEAGUE"] = league

    from app.pipeline.etl_runner import backfill_async

    # 백필 시 날씨 스킵 여부 (기본 True: Open-Meteo 429 방지)
    skip_weather = "--with-weather" not in sys.argv

    print(f"백필 시작: {league} {start} ~ {end} (날씨={'포함' if not skip_weather else '스킵'})")
    asyncio.run(backfill_async(start, end, league=league, skip_weather=skip_weather))
    print("백필 완료!")
