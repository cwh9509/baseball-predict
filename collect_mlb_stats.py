#!/usr/bin/env python3
"""
MLB 2024-2025 시즌 스탯 수집 및 DB 업로드 스크립트

사용법:
    python collect_mlb_stats.py                # 현재 시즌 (2025)
    python collect_mlb_stats.py --season 2024  # 특정 시즌
    python collect_mlb_stats.py --all          # 2024-2025 모두 수집

데이터 소스:
    - 투수 스탯 (ERA, FIP, WHIP, K/9, BB/9): FanGraphs via pybaseball
    - 투구 방향 (L/R): MLB StatsAPI
    - 팀 불펜 집계: 위 투수 데이터에서 GS/G < 0.3 투수 IP 가중 평균
    - 팀 타선 (OPS, wRC+, K%): FanGraphs via pybaseball
    - 타선 스플릿 vs LHP/RHP: 팀 OPS 기반 추정값 (추후 Statcast 실측값으로 업그레이드 예정)

필요 패키지:
    pybaseball, MLB-StatsAPI, sqlalchemy, asyncpg, python-dotenv

주의:
    - pybaseball은 FanGraphs에서 스크래핑하므로 요청 간 딜레이 발생 가능
    - 처음 실행 시 data/raw/*.parquet 캐시 생성 (이후 재실행 빠름)
    - DB 마이그레이션(009) 먼저 적용 필요: alembic upgrade head
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

# .env 로드
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("collect_mlb_stats")


async def collect_season(season: int) -> dict:
    """단일 시즌 MLB 스탯 수집 및 DB upsert"""
    from app.core.database import AsyncSessionLocal
    from app.collectors.mlb_stats_collector import upsert_mlb_stats

    logger.info(f"▶ MLB {season} 시즌 수집 시작")
    async with AsyncSessionLocal() as db:
        summary = await upsert_mlb_stats(season, db)
    logger.info(f"✓ MLB {season} 시즌 완료: {summary}")
    return summary


async def main(seasons: list[int]) -> None:
    logger.info(f"MLB 스탯 수집 시작 — 대상 시즌: {seasons}")
    logger.info("pybaseball 캐시 활성화 (data/raw/*.parquet)")

    results = []
    for season in seasons:
        try:
            summary = await collect_season(season)
            results.append(summary)
        except Exception as e:
            logger.error(f"시즌 {season} 수집 실패: {e}", exc_info=True)

    # 결과 요약 출력
    print("\n" + "=" * 60)
    print("MLB 스탯 수집 완료 요약")
    print("=" * 60)
    for r in results:
        season = r["season"]
        print(f"\n[{season} 시즌]")
        print(f"  투수 개인:   {r['pitchers']:3d}명")
        print(f"  팀 불펜:     {r['bullpen_teams']:3d}팀")
        print(f"  팀 타선:     {r['batting_teams']:3d}팀")
        print(f"  스플릿 레코드: {r['split_records']:3d}건")
    print("\n다음 단계:")
    print("  1. alembic upgrade head (마이그레이션 미적용 시)")
    print("  2. python backend/main.py (서버 재시작)")
    print("  3. POST /api/v1/admin/retrain (모델 재학습 — 피처 변경으로 필수)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MLB 시즌 스탯 수집 및 DB 업로드")
    parser.add_argument("--season", type=int, help="수집할 시즌 연도 (예: 2024)")
    parser.add_argument("--all", action="store_true", dest="all_seasons",
                        help="2024-2025 전체 시즌 수집")
    args = parser.parse_args()

    if args.all_seasons:
        target_seasons = [2024, 2025]
    elif args.season:
        target_seasons = [args.season]
    else:
        from datetime import date
        target_seasons = [date.today().year]

    asyncio.run(main(target_seasons))
