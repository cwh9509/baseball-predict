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

        # WS -> (필요 시) HTML 폴백을 동일 httpx.Client 세션에서 처리
        return await asyncio.to_thread(self._fetch_from_ws_then_html, external_game_id)

    def _fetch_from_ws_then_html(self, game_id: str) -> Optional[dict]:
        """
        KBO 라인업 수집을 WS 단독 시도 + 필요 시 HTML 폴백까지
        하나의 httpx.Client(단일 세션)에서 처리합니다.
        """
        try:
            import json

            main_url = f"{KBO_GAME_MAIN_URL}?gameId={game_id}"

            with httpx.Client(
                headers=REQUEST_HEADERS,
                timeout=15,
                follow_redirects=True,
            ) as client:
                # 1) 세션 쿠키 확립
                time.sleep(0.3)
                client.get(main_url)

                # 2) 라인업 웹서비스 호출
                time.sleep(0.3)
                resp = client.post(
                    KBO_LINEUP_WS_URL,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": main_url,
                    },
                    data={"gameId": game_id},
                )

                ct = resp.headers.get("content-type", "") or ""
                logger.info(
                    "KBO WS POST gameId=%s status_code=%s content-type=%r",
                    game_id,
                    resp.status_code,
                    ct,
                )

                # 3) JSON 파싱 가능한 경우 WS 응답 파싱
                fallback_reason: Optional[str] = None

                if resp.status_code in (301, 302, 303, 307, 308):
                    fallback_reason = f"ws status_code={resp.status_code}"
                elif "text/html" in ct.lower():
                    # 302 후 HTML(혹은 리다이렉트된 페이지)로 떨어진 케이스
                    fallback_reason = f"ws returned html content-type={ct!r}"
                else:
                    try:
                        text = resp.content.decode("utf-8", errors="replace")
                        data = json.loads(text)
                        parsed = self._parse_ws_response(data)
                        if parsed:
                            return parsed
                        fallback_reason = "ws json parsed but no lineup"
                    except Exception as e:
                        fallback_reason = f"ws json parse failed ({e.__class__.__name__})"

                # 4) 동일 client로 HTML 폴백
                logger.info(
                    "KBO WS fallback to HTML gameId=%s reason=%s",
                    game_id,
                    fallback_reason,
                )
                from bs4 import BeautifulSoup

                time.sleep(0.5)
                html_resp = client.get(main_url)
                html_resp.raise_for_status()

                try:
                    html_text = html_resp.content.decode("utf-8", errors="replace")
                except Exception:
                    html_text = html_resp.content.decode("cp949", errors="replace")

                soup = BeautifulSoup(html_text, "lxml")
                # HTML이 실제로 파싱 가능한 구조인지 빠르게 확인용
                lineup_tables = (
                    soup.find_all("table", class_=re.compile(r"bat.*order|lineup|tBat", re.I))
                    or soup.find_all("table", id=re.compile(r"tblLineup|tblBat", re.I))
                )
                pitcher_areas = soup.find_all(class_=re.compile(r"pitcher|sp_name|starter", re.I))
                logger.info(
                    "KBO HTML pre-parse gameId=%s lineup_tables=%d pitcher_areas=%d",
                    game_id,
                    len(lineup_tables),
                    len(pitcher_areas),
                )

                parsed = self._parse_html_lineup(soup)
                if parsed:
                    logger.info(
                        "KBO HTML parsed gameId=%s home_starter=%r away_starter=%r home_lineup=%d away_lineup=%d",
                        game_id,
                        parsed.get("home_starter"),
                        parsed.get("away_starter"),
                        len(parsed.get("home_lineup") or []),
                        len(parsed.get("away_lineup") or []),
                    )
                else:
                    logger.warning("KBO HTML parse returned None gameId=%s", game_id)
                return parsed
        except Exception as e:
            logger.warning(f"KBO 라인업 WS+HTML 실패 ({game_id}): {e}")
            return None

    def _fetch_from_ws(self, game_id: str) -> Optional[dict]:
        """KBO 웹서비스 /ws/Game.asmx/GetLineUp 시도.
        세션 쿠키가 필요하므로 먼저 게임 메인 페이지를 GET해 쿠키 확립 후 POST.
        """
        try:
            import json
            with httpx.Client(
                headers=REQUEST_HEADERS,
                timeout=15,
                follow_redirects=True,
            ) as client:
                # 세션 쿠키 확립
                time.sleep(0.3)
                client.get(f"{KBO_GAME_MAIN_URL}?gameId={game_id}")

                # 라인업 웹서비스 호출
                time.sleep(0.3)
                resp = client.post(
                    KBO_LINEUP_WS_URL,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": f"{KBO_GAME_MAIN_URL}?gameId={game_id}",
                    },
                    data={"gameId": game_id},
                )

                # 302 후 HTML 응답이면 실패
                if "text/html" in resp.headers.get("content-type", ""):
                    logger.debug(f"KBO WS 응답이 HTML (세션 미확립): {game_id}")
                    return None

                text = resp.content.decode("utf-8", errors="replace")
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

            url = f"{KBO_GAME_MAIN_URL}?gameId={game_id}"
            with httpx.Client(headers=REQUEST_HEADERS, timeout=15, follow_redirects=True) as client:
                time.sleep(0.5)
                resp = client.get(url)
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
