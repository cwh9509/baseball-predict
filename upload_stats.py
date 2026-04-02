"""
로컬에서 statiz 스탯을 수집해 Railway admin API로 업로드하는 스크립트.

사용법:
  python upload_stats.py --url https://your-backend.railway.app --season 2026

환경변수로도 설정 가능:
  RAILWAY_BACKEND_URL=https://... python upload_stats.py
"""
import argparse
import asyncio
import dataclasses
import json
import logging
import os
import sys

import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))


async def collect_and_upload(backend_url: str, season: int):
    from app.collectors.kbo_collector import KBOCollector

    collector = KBOCollector()

    # ── 투수 스탯 수집 ──────────────────────────────────────
    logger.info(f"투수 스탯 수집 중... (season={season})")
    pitchers = await collector.fetch_pitcher_stats_season(season)
    if not pitchers:
        logger.warning("투수 스탯 수집 실패 — statiz 로그인 확인 필요")
    else:
        logger.info(f"투수 {len(pitchers)}명 수집 완료")

    # ── 팀 타선 스탯 수집 ──────────────────────────────────
    KBO_TEAMS = ["삼성", "KIA", "롯데", "LG", "두산", "한화", "SSG", "키움", "NC", "KT"]
    team_batting = []
    logger.info("팀 타선 스탯 수집 중...")
    for team_short in KBO_TEAMS:
        stats = await collector.fetch_team_batting_stats(team_short, season)
        if stats:
            team_batting.append({"team_short": team_short, **stats})
            logger.info(f"  {team_short}: OPS={stats['ops']:.3f}, wRC+={stats['wrc_plus']:.1f}, K%={stats['k_rate']:.3f}")
        else:
            logger.warning(f"  {team_short}: 타선 스탯 없음")

    # ── 팀 불펜 스탯 수집 ──────────────────────────────────
    team_bullpen = []
    logger.info("팀 불펜 스탯 수집 중...")
    for team_short in KBO_TEAMS:
        stats = await collector.fetch_team_bullpen_stats(team_short, season)
        if stats:
            team_bullpen.append({"team_short": team_short, **stats})
            logger.info(f"  {team_short}: 불펜ERA={stats['bullpen_era']:.2f}, WHIP={stats['bullpen_whip']:.2f}, 투수수={stats['bullpen_count']}")
        else:
            logger.warning(f"  {team_short}: 불펜 스탯 없음")

    # ── 팀 타선 좌우 스플릿 수집 ─────────────────────────
    team_batting_splits = []
    logger.info("팀 타선 좌우 스플릿 수집 중...")
    split_data = await collector.fetch_team_batting_split_stats(season)
    for team_short, splits in split_data.items():
        for split_key, s in splits.items():
            team_batting_splits.append({
                "team_short": team_short,
                "split": split_key,
                "ops": s["ops"],
                "pa": s["pa"],
            })
            logger.info(f"  {team_short} {split_key}: OPS={s['ops']:.3f} (PA={s['pa']})")
    if not split_data:
        logger.warning("타선 스플릿 수집 실패 — statiz ph 파라미터 확인 필요")

    if not pitchers and not team_batting and not team_bullpen:
        logger.error("수집된 데이터가 없습니다. 종료.")
        return

    # ── Railway 업로드 ─────────────────────────────────────
    payload = {
        "season": season,
        "pitchers": [
            {
                "name": p.name,
                "team_short": p.team_short,
                "era": p.era,
                "whip": p.whip,
                "k9": p.k9,
                "ip": p.ip,
                "handedness": p.handedness,
            }
            for p in pitchers
        ],
        "team_batting": team_batting,
        "team_bullpen": team_bullpen,
        "team_batting_splits": team_batting_splits,
    }

    upload_url = f"{backend_url.rstrip('/')}/api/v1/admin/upload-stats"
    logger.info(f"업로드 중: {upload_url}")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(upload_url, json=payload)
        if resp.status_code == 200:
            result = resp.json()
            logger.info(
                f"업로드 완료: 투수={result['pitchers_upserted']}명, "
                f"팀타선={result['team_batting_upserted']}팀, "
                f"불펜={result['team_bullpen_upserted']}팀, "
                f"스플릿={result['splits_upserted']}건"
            )
        else:
            logger.error(f"업로드 실패: {resp.status_code} — {resp.text[:200]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="statiz 스탯 → Railway 업로드")
    parser.add_argument("--url", default=os.environ.get("RAILWAY_BACKEND_URL", ""), help="Railway backend URL")
    parser.add_argument("--season", type=int, default=2026, help="시즌 연도 (기본: 2026)")
    args = parser.parse_args()

    if not args.url:
        print("오류: --url 또는 RAILWAY_BACKEND_URL 환경변수를 설정하세요.")
        print("예시: python upload_stats.py --url https://your-backend.railway.app")
        sys.exit(1)

    asyncio.run(collect_and_upload(args.url, args.season))
