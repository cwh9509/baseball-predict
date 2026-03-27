"""KBO 투수 통계 스크래핑 테스트"""
import asyncio
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

from app.collectors.kbo_collector import KBOCollector

async def main():
    collector = KBOCollector()
    print("2025 KBO 투수 통계 스크래핑 중...")
    stats = await collector.fetch_pitcher_stats_season(2025)
    print(f"수집된 투수 수: {len(stats)}")
    if stats:
        print("\n상위 5명 (ERA 기준):")
        top5 = sorted([s for s in stats if s.ip >= 30], key=lambda x: x.era)[:5]
        for p in top5:
            print(f"  {p.name} ({p.team_short}) ERA={p.era:.2f} WHIP={p.whip:.2f} K/9={p.k9:.1f} IP={p.ip:.0f}")

        print("\n팀별 로테이션 ERA:")
        teams = ["KIA", "삼성", "LG", "두산", "한화", "SSG", "롯데", "키움", "NC", "KT"]
        for team in teams:
            era = await collector.fetch_team_rotation_era(team, 2025)
            print(f"  {team}: {era:.2f}" if era else f"  {team}: 데이터 없음")

asyncio.run(main())
