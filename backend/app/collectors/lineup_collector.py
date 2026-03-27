"""
KBO 라인업 수집기
- koreabaseball.com 게임 페이지에서 당일 선발 라인업 스크래핑
- 경기 시작 약 1~2시간 전에 라인업 발표
- 선발투수 확인 + 타순 정보 수집

사용 흐름:
  collector = KBOLineupCollector()
  result = await collector.fetch_lineup(external_game_id)
  # result: {"home": [...], "away": [...], "home_starter": "...", "away_starter": "..."}
"""
import asyncio
import logging
import re
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

KBO_GAME_MAIN_URL = "https://www.koreabaseball.com/Game/Main.aspx"
KBO_LINEUP_WS_URL = "https://www.koreabaseball.com/ws/Game.asmx/GetLineUp"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://www.koreabaseball.com/",
}


class KBOLineupCollector:

    async def fetch_lineup(self, external_game_id: str) -> Optional[dict]:
        """
        KBO 라인업 수집
        Returns:
            {
              "home_starter": "선수명",
              "away_starter": "선수명",
              "home_lineup": [{"order":1,"name":"...","position":"..."},...],
              "away_lineup": [{"order":1,"name":"...","position":"..."},...],
              "source": "kbo_ws" | "kbo_html"
            }
            또는 None (라인업 미발표 / 수집 실패)
        """
        if not external_game_id:
            return None

        # 방법 1: KBO 웹서비스 API 시도
        result = await asyncio.to_thread(self._fetch_from_ws, external_game_id)
        if result:
            return result

        # 방법 2: HTML 파싱 폴백
        result = await asyncio.to_thread(self._fetch_from_html, external_game_id)
        return result

    def _fetch_from_ws(self, game_id: str) -> Optional[dict]:
        """KBO 웹서비스 /ws/Game.asmx/GetLineUp 시도"""
        try:
            time.sleep(0.5)
            resp = httpx.post(
                KBO_LINEUP_WS_URL,
                headers={**REQUEST_HEADERS, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                          "X-Requested-With": "XMLHttpRequest"},
                data={"gameId": game_id},
                timeout=10,
                follow_redirects=True,
            )
            resp.raise_for_status()

            import json
            try:
                text = resp.content.decode("utf-8", errors="replace")
            except Exception:
                text = resp.text

            data = json.loads(text)
            return self._parse_ws_response(data)
        except Exception as e:
            logger.debug(f"KBO 라인업 웹서비스 실패 ({game_id}): {e}")
            return None

    def _parse_ws_response(self, data: dict) -> Optional[dict]:
        """웹서비스 응답 파싱"""
        if not data:
            return None

        home_lineup = []
        away_lineup = []
        home_starter = None
        away_starter = None

        # 응답 구조: {"home": [...], "away": [...]} 또는 {"rows": [...]}
        home_rows = data.get("home") or data.get("homeLineUp") or []
        away_rows = data.get("away") or data.get("awayLineUp") or []

        for i, row in enumerate(home_rows):
            name = row.get("name") or row.get("playerName") or row.get("Name", "")
            pos = row.get("position") or row.get("Position", "")
            order = row.get("order") or row.get("Order") or (i + 1)
            if name:
                home_lineup.append({"order": int(order), "name": name.strip(), "position": pos.strip()})
                if pos.strip() in ("P", "투수"):
                    home_starter = name.strip()

        for i, row in enumerate(away_rows):
            name = row.get("name") or row.get("playerName") or row.get("Name", "")
            pos = row.get("position") or row.get("Position", "")
            order = row.get("order") or row.get("Order") or (i + 1)
            if name:
                away_lineup.append({"order": int(order), "name": name.strip(), "position": pos.strip()})
                if pos.strip() in ("P", "투수"):
                    away_starter = name.strip()

        if not home_lineup and not away_lineup:
            return None

        return {
            "home_starter": home_starter,
            "away_starter": away_starter,
            "home_lineup": home_lineup,
            "away_lineup": away_lineup,
            "source": "kbo_ws",
        }

    def _fetch_from_html(self, game_id: str) -> Optional[dict]:
        """koreabaseball.com 게임 메인 페이지 HTML 파싱"""
        try:
            from bs4 import BeautifulSoup
            time.sleep(0.5)

            url = f"{KBO_GAME_MAIN_URL}?gameId={game_id}"
            resp = httpx.get(url, headers=REQUEST_HEADERS, timeout=15, follow_redirects=True)
            resp.raise_for_status()

            try:
                text = resp.content.decode("utf-8", errors="replace")
            except Exception:
                text = resp.content.decode("cp949", errors="replace")

            soup = BeautifulSoup(text, "lxml")
            return self._parse_html_lineup(soup)
        except Exception as e:
            logger.debug(f"KBO 라인업 HTML 파싱 실패 ({game_id}): {e}")
            return None

    def _parse_html_lineup(self, soup) -> Optional[dict]:
        """HTML에서 타순표 파싱
        코리아베이스볼닷컴 게임 페이지 구조:
        - div.batting_order 또는 table.tBatOrder
        - 홈/원정 두 개의 테이블
        """
        home_lineup = []
        away_lineup = []
        home_starter = None
        away_starter = None

        # 타순표 테이블 탐색 (class 이름은 버전에 따라 다를 수 있음)
        lineup_tables = (
            soup.find_all("table", class_=re.compile(r"bat.*order|lineup|tBat", re.I))
            or soup.find_all("table", id=re.compile(r"tblLineup|tblBat", re.I))
        )

        if len(lineup_tables) >= 2:
            for team_idx, table in enumerate(lineup_tables[:2]):
                lineup = []
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) < 2:
                        continue
                    cell_texts = [c.get_text(strip=True) for c in cells]
                    # 숫자로 시작하는 타순 행만 처리
                    if not cell_texts[0].isdigit():
                        continue
                    order = int(cell_texts[0])
                    name = cell_texts[1] if len(cell_texts) > 1 else ""
                    pos = cell_texts[2] if len(cell_texts) > 2 else ""
                    if name:
                        lineup.append({"order": order, "name": name, "position": pos})
                        if pos in ("P", "투수") and order == 0:
                            pass  # 선발투수는 별도 파싱

                if team_idx == 0:
                    away_lineup = lineup  # 보통 원정팀이 왼쪽
                else:
                    home_lineup = lineup

        # 선발투수 별도 파싱 (투수 이름 div/span)
        pitcher_areas = soup.find_all(class_=re.compile(r"pitcher|sp_name|starter", re.I))
        pitchers = []
        for area in pitcher_areas:
            name = area.get_text(strip=True)
            if name and len(name) >= 2:
                pitchers.append(name)

        if len(pitchers) >= 2:
            away_starter = pitchers[0]
            home_starter = pitchers[1]
        elif len(pitchers) == 1:
            home_starter = pitchers[0]

        if not home_lineup and not away_lineup and not home_starter and not away_starter:
            return None

        return {
            "home_starter": home_starter,
            "away_starter": away_starter,
            "home_lineup": home_lineup,
            "away_lineup": away_lineup,
            "source": "kbo_html",
        }
