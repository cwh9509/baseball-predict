"""
네이버 스포츠 KBO 라인업 수집기
- api-gw.sports.naver.com 사용 (서버 IP 차단 없음)
- preview 엔드포인트: 선발투수 (경기 전부터 접근 가능)
- lineup 엔드포인트: 타순 (공식 발표 후 접근 가능)

Naver game ID 규칙:
  kbo_game_id[:12] + "0" + str(year)
  예: 20260403NCHT0 → 20260403NCHT02026

API 라벨 주의:
  awayStarter → 실제 원정팀 선발 (game_id[8:10])
  homeStarter → 실제 홈팀 선발  (game_id[10:12])
  awayTeamLineUp → 원정팀 타순
  homeTeamLineUp → 홈팀 타순
"""
import asyncio
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

NAVER_API_BASE = "https://api-gw.sports.naver.com/schedule/games"
NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://m.sports.naver.com/",
    "Origin": "https://m.sports.naver.com",
    "Accept": "application/json",
}


def _naver_game_id(kbo_game_id: str) -> str:
    """KBO game ID → Naver game ID 변환
    20260403NCHT0 → 20260403NCHT02026
    """
    year = kbo_game_id[:4]
    prefix = kbo_game_id[:12]  # YYYYMMDDAAHH
    return f"{prefix}0{year}"


class NaverLineupCollector:

    async def fetch_lineup(self, kbo_game_id: str) -> Optional[dict]:
        """
        네이버 스포츠에서 선발투수 + 타순 수집

        Returns:
            {
              "home_starter": "선수명",
              "away_starter": "선수명",
              "home_lineup": [{"order":1,"name":"...","position":"..."},...],
              "away_lineup": [...],
              "source": "naver"
            }
            또는 None
        """
        naver_id = _naver_game_id(kbo_game_id)

        # 1) lineup 엔드포인트 시도 (공식 발표 후 데이터 있음)
        result = await asyncio.to_thread(self._fetch_lineup_endpoint, naver_id)
        if result:
            return result

        # 2) preview 엔드포인트 폴백 (선발투수만 가져옴)
        result = await asyncio.to_thread(self._fetch_preview_endpoint, naver_id)
        return result

    def _fetch_lineup_endpoint(self, naver_id: str) -> Optional[dict]:
        try:
            time.sleep(0.3)
            resp = httpx.get(
                f"{NAVER_API_BASE}/{naver_id}/lineup",
                headers=NAVER_HEADERS,
                timeout=10,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            lineup_data = data.get("result", {}).get("lineUpData")
            if not lineup_data:
                return None
            return self._parse_lineup_data(lineup_data)
        except Exception as e:
            logger.debug(f"Naver lineup endpoint 실패 ({naver_id}): {e}")
            return None

    def _fetch_preview_endpoint(self, naver_id: str) -> Optional[dict]:
        try:
            time.sleep(0.3)
            resp = httpx.get(
                f"{NAVER_API_BASE}/{naver_id}/preview",
                headers=NAVER_HEADERS,
                timeout=10,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            preview = data.get("result", {}).get("previewData")
            if not preview:
                return None
            return self._parse_preview_data(preview)
        except Exception as e:
            logger.debug(f"Naver preview endpoint 실패 ({naver_id}): {e}")
            return None

    def _parse_lineup_data(self, lineup_data: dict) -> Optional[dict]:
        """lineup 엔드포인트 응답 파싱 (타순 + 선발투수)"""
        # Naver 라벨: awayBatters=원정타순, homeBatters=홈타순
        away_batters = lineup_data.get("awayBatters") or lineup_data.get("awayLineUp") or []
        home_batters = lineup_data.get("homeBatters") or lineup_data.get("homeLineUp") or []
        away_pitcher = lineup_data.get("awayStartingPitcher") or {}
        home_pitcher = lineup_data.get("homeStartingPitcher") or {}

        away_starter = (
            away_pitcher.get("name") or
            away_pitcher.get("playerName") or
            away_pitcher.get("playerInfo", {}).get("name")
        )
        home_starter = (
            home_pitcher.get("name") or
            home_pitcher.get("playerName") or
            home_pitcher.get("playerInfo", {}).get("name")
        )

        home_lineup = [
            {"order": i + 1, "name": p.get("name") or p.get("playerName", ""), "position": p.get("position", "")}
            for i, p in enumerate(home_batters) if p.get("name") or p.get("playerName")
        ]
        away_lineup = [
            {"order": i + 1, "name": p.get("name") or p.get("playerName", ""), "position": p.get("position", "")}
            for i, p in enumerate(away_batters) if p.get("name") or p.get("playerName")
        ]

        if not home_starter and not away_starter and not home_lineup and not away_lineup:
            return None

        return {
            "home_starter": home_starter,
            "away_starter": away_starter,
            "home_lineup": home_lineup,
            "away_lineup": away_lineup,
            "source": "naver_lineup",
        }

    def _parse_preview_data(self, preview: dict) -> Optional[dict]:
        """preview 엔드포인트 응답 파싱 (선발투수 위주)"""
        # Naver preview: awayStarter=원정선발, homeStarter=홈선발
        away_starter_info = preview.get("awayStarter", {}).get("playerInfo", {})
        home_starter_info = preview.get("homeStarter", {}).get("playerInfo", {})

        away_starter = away_starter_info.get("name")
        home_starter = home_starter_info.get("name")

        # preview의 타순은 3명만 있어서 실제 타순으로 사용하지 않음
        home_lineup = []
        away_lineup = []

        if not home_starter and not away_starter:
            return None

        return {
            "home_starter": home_starter,
            "away_starter": away_starter,
            "home_lineup": home_lineup,
            "away_lineup": away_lineup,
            "source": "naver_preview",
        }
