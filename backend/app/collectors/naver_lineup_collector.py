"""
네이버 스포츠 KBO 라인업/일정 수집기
- api-gw.sports.naver.com 사용 (서버 IP 차단 없음)
- schedule 엔드포인트: KBO 일정 수집 (statiz 403 폴백용)
- preview 엔드포인트: 선발투수 (경기 전부터 접근 가능)
- lineup 엔드포인트: 타순 (공식 발표 후 접근 가능)

Naver game ID 규칙:
  YYYYMMDD{away_code}{home_code}0{year}
  예: 20260403NCHT02026 (NC 원정, HT 홈)

API 라벨: 실제 홈/원정과 일치
  homeStarter → 실제 홈팀 선발  (game_id[10:12])
  awayStarter → 실제 원정팀 선발 (game_id[8:10])
"""
import asyncio
import logging
import time
from datetime import date
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

NAVER_API_BASE = "https://api-gw.sports.naver.com/schedule/games"
NAVER_SCHEDULE_BASE = "https://api-gw.sports.naver.com/schedule/games"
NAVER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://m.sports.naver.com/",
    "Origin": "https://m.sports.naver.com",
    "Accept": "application/json",
}

# Naver 팀코드 → DB short_name
NAVER_CODE_TO_SHORT: dict[str, str] = {
    "HH": "한화",
    "OB": "두산",
    "SS": "삼성",
    "LG": "LG",
    "SK": "SSG",
    "WO": "키움",
    "KT": "KT",
    "HT": "KIA",
    "LT": "롯데",
    "NC": "NC",
}

# 구장명 매핑 (팀코드 → 홈구장)
NAVER_CODE_TO_VENUE: dict[str, str] = {
    "HH": "한화생명 이글스파크",
    "OB": "잠실야구장",
    "SS": "라이온즈 파크",
    "LG": "잠실야구장",
    "SK": "인천SSG랜더스필드",
    "WO": "고척스카이돔",
    "KT": "수원KT위즈파크",
    "HT": "광주-기아 챔피언스 필드",
    "LT": "사직야구장",
    "NC": "창원NC파크",
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

        # 1) record 엔드포인트 (타순 + 선발투수 전부 있음)
        result = await asyncio.to_thread(self._fetch_record_endpoint, naver_id)
        if result:
            return result

        # 2) lineup API 엔드포인트
        result = await asyncio.to_thread(self._fetch_lineup_endpoint, naver_id)
        if result:
            return result

        # 3) preview 폴백 (선발투수만)
        result = await asyncio.to_thread(self._fetch_preview_endpoint, naver_id)
        return result

    def _fetch_record_endpoint(self, naver_id: str) -> Optional[dict]:
        """record 엔드포인트에서 battersBoxscore + pitchersBoxscore 파싱"""
        try:
            time.sleep(0.3)
            resp = httpx.get(
                f"{NAVER_API_BASE}/{naver_id}/record",
                headers=NAVER_HEADERS,
                timeout=10,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            record = data.get("result", {}).get("recordData", {})
            if not record:
                return None

            pitchers = record.get("pitchersBoxscore", {})
            batters = record.get("battersBoxscore", {})

            away_pitchers = pitchers.get("away") or []
            home_pitchers = pitchers.get("home") or []
            away_batters = batters.get("away") or []
            home_batters = batters.get("home") or []

            away_starter = away_pitchers[0].get("name") if away_pitchers else None
            home_starter = home_pitchers[0].get("name") if home_pitchers else None

            away_lineup = [
                {"order": b.get("batOrder", i + 1), "name": b.get("name", ""), "position": b.get("pos", "")}
                for i, b in enumerate(away_batters) if b.get("name")
            ]
            home_lineup = [
                {"order": b.get("batOrder", i + 1), "name": b.get("name", ""), "position": b.get("pos", "")}
                for i, b in enumerate(home_batters) if b.get("name")
            ]

            if not away_starter and not home_starter and not away_lineup and not home_lineup:
                return None

            logger.info(
                f"Naver record 라인업 수집 ({naver_id}): "
                f"home={home_starter} away={away_starter} "
                f"home_lineup={len(home_lineup)}명 away_lineup={len(away_lineup)}명"
            )
            return {
                "home_starter": home_starter,
                "away_starter": away_starter,
                "home_lineup": home_lineup,
                "away_lineup": away_lineup,
                "source": "naver_record",
            }
        except Exception as e:
            logger.debug(f"Naver record endpoint 실패 ({naver_id}): {e}")
            return None

    def _fetch_mobile_page_lineup(self, naver_id: str) -> Optional[dict]:
        """https://m.sports.naver.com/game/{naver_id}/lineup 스크래핑"""
        try:
            import json
            from bs4 import BeautifulSoup

            url = f"https://m.sports.naver.com/game/{naver_id}/lineup"
            time.sleep(0.3)
            resp = httpx.get(url, headers=NAVER_HEADERS, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                logger.warning(f"Naver mobile lineup HTTP {resp.status_code} ({naver_id})")
                return None

            soup = BeautifulSoup(resp.text, "lxml")

            # __NEXT_DATA__ 시도
            script = soup.find("script", id="__NEXT_DATA__")
            if not script:
                # 다른 인라인 스크립트에서 JSON 데이터 탐색
                for s in soup.find_all("script"):
                    txt = s.string or ""
                    if "lineUp" in txt or "homeBatter" in txt or "startingPitcher" in txt:
                        logger.info(f"Naver mobile 인라인 스크립트 발견 ({naver_id}): {txt[:500]}")
                        break
                else:
                    # 스크립트 목록만 로그
                    script_ids = [s.get("id") or s.get("src","")[:60] for s in soup.find_all("script")]
                    logger.warning(f"Naver mobile 데이터 스크립트 없음 ({naver_id}): scripts={script_ids[:10]}")
                return None

            next_data = json.loads(script.string)
            # 데이터 경로 탐색
            page_props = next_data.get("props", {}).get("pageProps", {})
            lineup_data = (
                page_props.get("lineUpData")
                or page_props.get("lineupData")
                or page_props.get("data", {}).get("lineUpData")
                or page_props.get("data", {}).get("lineupData")
            )

            if not lineup_data:
                # 구조 파악용 로그
                logger.warning(
                    f"Naver mobile lineup 데이터 없음 ({naver_id}): "
                    f"pageProps keys={list(page_props.keys())}"
                )
                return None

            result = self._parse_lineup_data(lineup_data)
            if result:
                result["source"] = "naver_mobile"
                logger.info(
                    f"Naver mobile 라인업 수집 성공 ({naver_id}): "
                    f"home={result.get('home_starter')} away={result.get('away_starter')} "
                    f"home_lineup={len(result.get('home_lineup') or [])}명 "
                    f"away_lineup={len(result.get('away_lineup') or [])}명"
                )
            return result
        except Exception as e:
            logger.warning(f"Naver mobile 스크래핑 실패 ({naver_id}): {e}")
            return None

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
                logger.warning(f"Naver lineup endpoint HTTP {resp.status_code} ({naver_id})")
                return None
            data = resp.json()
            result = data.get("result", {})
            # 응답 키 확인용 로그
            lineup_data = (
                result.get("lineUpData")
                or result.get("lineupData")
                or result.get("lineup")
            )
            if not lineup_data:
                raw = result.get("lineUpData")
                logger.warning(f"Naver lineup endpoint lineUpData 비어있음 ({naver_id}): {repr(raw)[:300]}")
                return None
            return self._parse_lineup_data(lineup_data)
        except Exception as e:
            logger.warning(f"Naver lineup endpoint 실패 ({naver_id}): {e}")
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
        # Naver API 라벨은 실제 홈/원정과 일치 (reversedHomeAway 없음)
        # homeStartingPitcher → 실제 홈팀 선발, awayStartingPitcher → 실제 원정팀 선발
        home_batters = lineup_data.get("homeBatters") or lineup_data.get("homeLineUp") or []
        away_batters = lineup_data.get("awayBatters") or lineup_data.get("awayLineUp") or []
        home_pitcher = lineup_data.get("homeStartingPitcher") or {}
        away_pitcher = lineup_data.get("awayStartingPitcher") or {}

        home_starter = (
            home_pitcher.get("name") or
            home_pitcher.get("playerName") or
            home_pitcher.get("playerInfo", {}).get("name")
        )
        away_starter = (
            away_pitcher.get("name") or
            away_pitcher.get("playerName") or
            away_pitcher.get("playerInfo", {}).get("name")
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
        # Naver API 라벨은 실제 홈/원정과 일치
        # homeStarter → 실제 홈팀 선발, awayStarter → 실제 원정팀 선발
        home_starter_info = preview.get("homeStarter", {}).get("playerInfo", {})
        away_starter_info = preview.get("awayStarter", {}).get("playerInfo", {})

        home_starter = home_starter_info.get("name")
        away_starter = away_starter_info.get("name")

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

    def fetch_schedule_sync(self, target_date: date) -> list[dict]:
        """
        Naver API에서 KBO 일정 수집 (statiz 403 폴백용)

        Returns list of:
          {
            "external_game_id": "20260403NCHT0",
            "home_team_short": "KIA",
            "away_team_short": "NC",
            "game_date": date,
            "game_time": "18:30",
            "status": "scheduled" | "final" | "in_progress",
            "home_score": int | None,
            "away_score": int | None,
            "venue": str,
          }
        """
        date_str = target_date.strftime("%Y%m%d")
        try:
            resp = httpx.get(
                NAVER_SCHEDULE_BASE,
                params={"gameDate": date_str, "categoryId": "kbo"},
                headers=NAVER_HEADERS,
                timeout=10,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                logger.warning(f"Naver 스케줄 API 응답 오류: {resp.status_code}")
                return []
            games = resp.json().get("result", {}).get("games", [])
        except Exception as e:
            logger.warning(f"Naver 스케줄 수집 실패: {e}")
            return []

        results = []
        for g in games:
            game_id = g.get("gameId", "")
            if len(game_id) < 12:
                continue

            # gameId: YYYYMMDD{away_code}{home_code}0{year}
            # position 8-10 = away team code, 10-12 = home team code
            away_code = game_id[8:10]
            home_code = game_id[10:12]
            home_short = NAVER_CODE_TO_SHORT.get(home_code)
            away_short = NAVER_CODE_TO_SHORT.get(away_code)
            if not home_short or not away_short:
                continue

            status_code = g.get("statusCode", "BEFORE")
            if status_code == "BEFORE":
                status = "scheduled"
            elif status_code in ("LIVE", "STARTED"):
                status = "in_progress"
            elif status_code in ("RESULT", "FINAL", "CLOSE"):
                status = "final"
            else:
                status = "scheduled"

            game_dt = g.get("gameDateTime", "")
            game_time = game_dt[11:16] if len(game_dt) >= 16 else None

            # external_game_id: Naver gameId에서 마지막 4자리(연도) 제거
            # 20260403NCHT02026 → 20260403NCHT0
            ext_id = game_id[:12] + "0" if len(game_id) >= 12 else None

            results.append({
                "external_game_id": ext_id,
                "home_team_short": home_short,
                "away_team_short": away_short,
                "game_date": target_date,
                "game_time": game_time,
                "status": status,
                "home_score": g.get("homeTeamScore") if status == "final" else None,
                "away_score": g.get("awayTeamScore") if status == "final" else None,
                "venue": NAVER_CODE_TO_VENUE.get(home_code, ""),
            })

        return results

    async def fetch_schedule(self, target_date: date) -> list[dict]:
        """비동기 래퍼"""
        return await asyncio.to_thread(self.fetch_schedule_sync, target_date)
