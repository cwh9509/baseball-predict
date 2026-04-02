"""
KBO data collector — koreabaseball.com official schedule API
"""
import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import httpx

from app.collectors.base_collector import (
    BaseCollector,
    GameLogRaw,
    GameRaw,
    PitcherStatsRaw,
    TeamRaw,
)

logger = logging.getLogger(__name__)

# KBO game ID code → DB short_name mapping
GAMEID_CODE_TO_SHORT: dict[str, str] = {
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

# statiz.co.kr 내부 팀 코드 → DB short_name 매핑
STATIZ_TEAM_CODE_TO_SHORT: dict[str, str] = {
    "1001":  "삼성",
    "2002":  "KIA",
    "3001":  "롯데",
    "5002":  "LG",
    "6002":  "두산",
    "7002":  "한화",
    "9002":  "SSG",
    "10001": "키움",
    "11001": "NC",
    "12001": "KT",
}

KBO_TEAMS: dict[str, dict] = {
    "KIA": {"name": "KIA 타이거즈", "city": "광주", "stadium": "광주-기아 챔피언스 필드",
             "lat": 35.1685, "lon": 126.8889, "roof": "open"},
    "삼성": {"name": "삼성 라이온즈", "city": "대구", "stadium": "라이온즈 파크",
             "lat": 35.8413, "lon": 128.6817, "roof": "open"},
    "LG": {"name": "LG 트윈스", "city": "서울", "stadium": "잠실야구장",
            "lat": 37.5122, "lon": 127.0717, "roof": "open"},
    "두산": {"name": "두산 베어스", "city": "서울", "stadium": "잠실야구장",
             "lat": 37.5122, "lon": 127.0717, "roof": "open"},
    "한화": {"name": "한화 이글스", "city": "대전", "stadium": "한화생명 이글스파크",
             "lat": 36.3172, "lon": 127.4295, "roof": "open"},
    "SSG": {"name": "SSG 랜더스", "city": "인천", "stadium": "인천SSG랜더스필드",
             "lat": 37.4370, "lon": 126.6931, "roof": "open"},
    "롯데": {"name": "롯데 자이언츠", "city": "부산", "stadium": "사직야구장",
             "lat": 35.1939, "lon": 129.0614, "roof": "open"},
    "키움": {"name": "키움 히어로즈", "city": "서울", "stadium": "고척스카이돔",
             "lat": 37.4982, "lon": 126.8670, "roof": "dome"},
    "NC":  {"name": "NC 다이노스", "city": "창원", "stadium": "창원NC파크",
             "lat": 35.2225, "lon": 128.5817, "roof": "open"},
    "KT":  {"name": "KT 위즈", "city": "수원", "stadium": "수원KT위즈파크",
             "lat": 37.2998, "lon": 127.0097, "roof": "open"},
}

KBO_API_URL = "https://www.koreabaseball.com/ws/Schedule.asmx/GetScheduleList"
STATIZ_BASE_URL = "https://statiz.co.kr"
STATIZ_LOGIN_URL = f"{STATIZ_BASE_URL}/member/handle.php"
STATIZ_STATS_URL = f"{STATIZ_BASE_URL}/stats/"

# 웹사이트 팀명 → DB short_name 매핑
KBO_TEAM_NAME_TO_SHORT: dict[str, str] = {
    "KIA": "KIA", "기아": "KIA",
    "삼성": "삼성",
    "LG": "LG",
    "두산": "두산",
    "한화": "한화",
    "SSG": "SSG", "SK": "SSG",
    "롯데": "롯데",
    "키움": "키움", "넥센": "키움", "히어로즈": "키움",
    "NC": "NC",
    "KT": "KT",
}
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.koreabaseball.com/Schedule/Schedule.aspx",
}


class KBOCollector(BaseCollector):

    def __init__(self):
        pass

    async def fetch_all_teams(self) -> list[TeamRaw]:
        return [
            TeamRaw(
                league="KBO",
                short_name=short,
                name=info["name"],
                city=info["city"],
                stadium_name=info["stadium"],
                stadium_lat=info["lat"],
                stadium_lon=info["lon"],
                roof_type=info["roof"],
            )
            for short, info in KBO_TEAMS.items()
        ]

    async def fetch_schedule(self, target_date: date) -> list[GameRaw]:
        return await asyncio.to_thread(self._fetch_month_sync, target_date, scheduled_only=True)

    async def fetch_game_results(self, target_date: date) -> list[GameRaw]:
        return await asyncio.to_thread(self._fetch_month_sync, target_date, scheduled_only=False)

    def _fetch_month_sync(self, target_date: date, scheduled_only: bool) -> list[GameRaw]:
        try:
            time.sleep(0.5)
            resp = httpx.post(
                KBO_API_URL,
                headers=REQUEST_HEADERS,
                data={
                    "leId": "1",
                    "srIdList": "0,1,3,4,5",
                    "seasonId": str(target_date.year),
                    "gameMonth": str(target_date.month),
                    "teamId": "",
                },
                timeout=15,
                follow_redirects=True,
            )
            resp.raise_for_status()
            text = resp.content.decode("cp949", errors="replace")
            import json
            data = json.loads(text)
            rows = data.get("rows", [])
            return self._parse_rows(rows, target_date, scheduled_only)
        except Exception as e:
            logger.error(f"KBO schedule fetch failed: {e}")
            return []

    def _parse_rows(self, rows: list, target_date: date, scheduled_only: bool) -> list[GameRaw]:
        games: list[GameRaw] = []
        current_date: Optional[date] = None

        for row in rows:
            cells = row.get("row", [])
            if not cells:
                continue

            # Detect if first cell is a date cell (has RowSpan)
            has_date_cell = cells[0].get("RowSpan") not in (None, "1", "0")

            if has_date_cell:
                date_text = re.sub(r"<[^>]+>", "", cells[0]["Text"])
                current_date = self._parse_date(date_text, target_date.year)
                time_text = re.sub(r"<[^>]+>", "", cells[1]["Text"]).strip()
                play_text = cells[2]["Text"]
                link_text = cells[3]["Text"]
                pitcher_text = re.sub(r"<[^>]+>", "", cells[4]["Text"]).strip() if len(cells) > 4 else ""
            else:
                time_text = re.sub(r"<[^>]+>", "", cells[0]["Text"]).strip()
                play_text = cells[1]["Text"]
                link_text = cells[2]["Text"]
                pitcher_text = re.sub(r"<[^>]+>", "", cells[3]["Text"]).strip() if len(cells) > 3 else ""

            if current_date != target_date:
                continue

            # Extract gameId from link cell
            game_id_match = re.search(r"gameId=([A-Z0-9]+)", link_text)
            if not game_id_match:
                continue
            game_id = game_id_match.group(1)

            home_code = game_id[8:10]
            away_code = game_id[10:12]
            home_short = GAMEID_CODE_TO_SHORT.get(home_code)
            away_short = GAMEID_CODE_TO_SHORT.get(away_code)

            if not home_short or not away_short:
                logger.warning(f"Unknown team codes: {home_code}, {away_code} in {game_id}")
                continue

            # Parse status and scores
            status, home_score, away_score = self._parse_play_cell(play_text)

            if scheduled_only and status != "scheduled":
                continue

            # Parse game time
            game_time = self._parse_time(time_text)

            # 선발투수 파싱 (형식: "홈선발 vs 원정선발" 또는 "-")
            home_starter_name, away_starter_name = self._parse_pitcher_cell(pitcher_text)

            games.append(GameRaw(
                league="KBO",
                game_date=current_date,
                game_time_local=game_time,
                home_team_short=home_short,
                away_team_short=away_short,
                venue=KBO_TEAMS.get(home_short, {}).get("stadium"),
                status=status,
                home_score=home_score,
                away_score=away_score,
                external_game_id=game_id,
                home_starter_name=home_starter_name,
                away_starter_name=away_starter_name,
            ))

        return games

    def _parse_pitcher_cell(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """선발투수 셀 파싱 → (홈선발, 원정선발)
        형식: "류현진 vs 원종현" 또는 "-" 또는 빈 문자열
        """
        if not text or text in ("-", "vs", "VS"):
            return None, None
        # "홈선발 vs 원정선발" 형식
        parts = re.split(r"\s+vs\s+", text, flags=re.IGNORECASE)
        if len(parts) == 2:
            home = parts[0].strip() or None
            away = parts[1].strip() or None
            return home, away
        return None, None

    def _parse_date(self, text: str, year: int) -> Optional[date]:
        # e.g. "03.28" or "03.28(토)"
        m = re.search(r"(\d{2})\.(\d{2})", text)
        if m:
            try:
                return date(year, int(m.group(1)), int(m.group(2)))
            except ValueError:
                pass
        return None

    def _parse_time(self, text: str) -> Optional[str]:
        # e.g. "14:00" or "18:30"
        m = re.search(r"(\d{1,2}):(\d{2})", text)
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}:00"
        return None

    def _parse_play_cell(self, play_text: str) -> tuple[str, Optional[int], Optional[int]]:
        """Returns (status, home_score, away_score)"""
        if "win" in play_text or "lose" in play_text:
            # Completed game
            scores = re.findall(r'class="(?:win|lose|same)">(\d+)<', play_text)
            if len(scores) >= 2:
                home_score, away_score = int(scores[0]), int(scores[1])
                return "final", home_score, away_score
            return "final", None, None
        elif "same" in play_text:
            # Tie
            scores = re.findall(r'class="same">(\d+)<', play_text)
            if len(scores) >= 2:
                return "final", int(scores[0]), int(scores[1])
            return "final", None, None
        else:
            return "scheduled", None, None

    async def fetch_team_game_log(self, team_short: str, n_games: int = 10) -> list[GameLogRaw]:
        logger.warning("KBO fetch_team_game_log not implemented")
        return []

    async def fetch_pitcher_stats(self, external_id: str, season: int) -> Optional[PitcherStatsRaw]:
        """개별 투수 통계 (팀 로테이션 캐시에서 조회)"""
        all_stats = await self.fetch_pitcher_stats_season(season)
        for stats in all_stats:
            if stats.external_id == external_id:
                return stats
        return None

    async def fetch_pitcher_stats_season(self, season: int) -> list[PitcherStatsRaw]:
        """시즌 전체 투수 통계 스크래핑 (캐시 지원)"""
        return await asyncio.to_thread(self._fetch_pitcher_stats_sync, season)

    def _statiz_login(self, client: httpx.Client) -> bool:
        """statiz.co.kr 로그인 → 쿠키 설정. 성공 시 True 반환."""
        import json
        from pathlib import Path
        from app.config import settings as app_settings

        uid = getattr(app_settings, "statiz_id", "")
        pw  = getattr(app_settings, "statiz_pw", "")
        if not uid or not pw:
            logger.warning("STATIZ_ID / STATIZ_PW 환경변수 미설정 — 로그인 스킵")
            return False

        # 저장된 쿠키가 있으면 먼저 시도
        cookie_path = Path("data/raw/statiz_cookies.json")
        if cookie_path.exists():
            try:
                saved = json.loads(cookie_path.read_text())
                for name, value in saved.items():
                    client.cookies.set(name, value, domain="statiz.co.kr")
                # 실제 접근 가능한지 확인
                test = client.get(f"{STATIZ_STATS_URL}?m=main&m2=pitching&year=2025&ipp=10")
                if test.status_code == 200 and "로그인" not in test.text[:500]:
                    logger.info("statiz 저장 쿠키로 세션 복원 성공")
                    return True
                logger.info("statiz 저장 쿠키 만료 — 재로그인 시도")
                client.cookies.clear()
            except Exception:
                client.cookies.clear()

        try:
            from bs4 import BeautifulSoup

            browser_headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
            }
            client.headers.update(browser_headers)

            login_page_url = f"{STATIZ_BASE_URL}/member/?m=login"
            r = client.get(login_page_url)
            soup = BeautifulSoup(r.text, "lxml")
            form = soup.find("form", action=lambda a: a and "handle" in (a or ""))
            if not form:
                logger.warning("statiz 로그인 폼을 찾을 수 없음")
                return False

            hidden = {
                i["name"]: i.get("value", "")
                for i in form.find_all("input", {"type": "hidden"})
                if i.get("name")
            }

            resp = client.post(
                STATIZ_LOGIN_URL,
                data={**hidden, "userID": uid, "userPassword": pw},
                headers={"Referer": login_page_url, "Content-Type": "application/x-www-form-urlencoded"},
            )

            # 로그인 성공 여부 확인 (쿠키 또는 응답 내용으로)
            has_token = "access_token" in client.cookies or "PHPSESSID" in client.cookies
            if not has_token:
                logger.warning(f"statiz 로그인 응답 쿠키 없음 (status={resp.status_code})")
                return False

            # 실제 접근 테스트
            test = client.get(f"{STATIZ_STATS_URL}?m=main&m2=pitching&year=2025&ipp=10")
            if test.status_code != 200:
                logger.warning(f"statiz 로그인 후 접근 실패: {test.status_code}")
                return False

            # 쿠키 저장
            try:
                cookie_path.parent.mkdir(parents=True, exist_ok=True)
                cookie_path.write_text(json.dumps(dict(client.cookies)))
            except Exception:
                pass

            logger.info("statiz 로그인 성공")
            return True

        except Exception as e:
            logger.warning(f"statiz 로그인 실패: {e}")
            return False

    def _fetch_pitcher_stats_sync(self, season: int) -> list[PitcherStatsRaw]:
        """statiz.co.kr 로그인 후 KBO 시즌 투수 통계 스크래핑
        URL: /stats/?m=main&m2=pitching&year={season}&ipp=500
        컬럼 순서 (헤더 기준):
          0=Rank, 1=Name, 2=Team, 3=WAR_sort, 4=G, 5=GS, 14=IP,
          26=SO, 30=ERA, 35=WHIP, 36=WAR
        """
        import dataclasses
        import json
        from pathlib import Path
        from bs4 import BeautifulSoup

        import time
        cache_path = Path(f"data/raw/kbo_pitcher_stats_{season}.json")
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        current_year = time.localtime().tm_year
        # 현재 시즌은 7일, 과거 시즌은 영구 캐시
        cache_ttl_seconds = 7 * 24 * 3600 if season >= current_year else None

        if cache_path.exists():
            expired = (
                cache_ttl_seconds is not None
                and (time.time() - cache_path.stat().st_mtime) > cache_ttl_seconds
            )
            if expired:
                logger.info(f"statiz 캐시 만료 — 재수집 ({season})")
                cache_path.unlink(missing_ok=True)
            else:
                try:
                    cached = json.loads(cache_path.read_text(encoding="utf-8"))
                    return [PitcherStatsRaw(**r) for r in cached]
                except Exception:
                    cache_path.unlink(missing_ok=True)

        results: list[PitcherStatsRaw] = []
        base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": STATIZ_BASE_URL,
        }

        try:
            with httpx.Client(timeout=30, follow_redirects=True, headers=base_headers) as client:
                if not self._statiz_login(client):
                    logger.warning(f"statiz 로그인 실패 — {season} 투수 통계 수집 불가")
                    return []

                # ipp=500으로 한 페이지에 최대한 많이 가져오기
                url = (
                    f"{STATIZ_STATS_URL}?m=main&m2=pitching"
                    f"&year={season}&ipp=500"
                )
                resp = client.get(url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                table = soup.find("table")
                if not table:
                    logger.warning(f"statiz: 투수 통계 테이블 없음 ({season})")
                    return []

                rows = table.find_all("tr")
                if len(rows) < 3:
                    logger.warning(f"statiz: 행 부족 ({len(rows)}행, {season})")
                    return []

                # 헤더로 컬럼 인덱스 확인
                header_cells = rows[0].find_all(["th", "td"])
                headers = [h.get_text(strip=True) for h in header_cells]
                idx: dict[str, int] = {h: i for i, h in enumerate(headers)}

                # 컬럼 인덱스 (헤더명 우선, 위치 폴백)
                i_name  = idx.get("Name",  1)
                i_team  = idx.get("Team",  2)
                i_hand  = idx.get("투/타", idx.get("투타", 3))   # 투구방향: 좌우
                i_ip    = idx.get("IP",   14)
                i_so    = idx.get("SO",   26)
                i_era   = idx.get("ERA",  30)
                i_whip  = idx.get("WHIP", 35)

                logger.info(
                    f"statiz 컬럼 인덱스: name={i_name} team={i_team} "
                    f"hand={i_hand} ip={i_ip} so={i_so} era={i_era} whip={i_whip}"
                )

                for tr in rows[1:]:  # rows[1] = WAR sub-header, rows[2+] = data
                    raw_cells = tr.find_all(["td", "th"])
                    cells = [td.get_text(strip=True) for td in raw_cells]
                    if not cells or len(cells) < max(i_era, i_whip) + 1:
                        continue
                    # WAR 서브헤더 행 스킵
                    if cells[0] in ("", "WAR") or not cells[0].isdigit():
                        continue

                    try:
                        name = cells[i_name]

                        # 팀: SVG 이미지 URL에서 statiz 팀 코드 추출
                        team_short = ""
                        if i_team < len(raw_cells):
                            img = raw_cells[i_team].find("img")
                            if img:
                                m = re.search(r"/(\d+)\.svg", img.get("src", ""))
                                if m:
                                    team_short = STATIZ_TEAM_CODE_TO_SHORT.get(m.group(1), "")
                        if not team_short:
                            team_short = KBO_TEAM_NAME_TO_SHORT.get(cells[i_team].strip(), "")

                        ip   = self._parse_innings(cells[i_ip])
                        if ip < 1:   # 1이닝 미만 제외 (시즌 초 대응)
                            continue

                        era_s  = cells[i_era]
                        whip_s = cells[i_whip]
                        so_s   = cells[i_so] if i_so < len(cells) else "0"

                        era  = float(era_s)  if era_s  and era_s  not in ("-", "") else 4.50
                        whip = float(whip_s) if whip_s and whip_s not in ("-", "") else 1.35
                        try:
                            so = float(so_s)
                        except ValueError:
                            so = 0.0
                        k9 = (so / ip * 9) if ip > 0 else 7.5

                        # 투구 방향 파싱: "우우"→R, "좌우"→L, "우좌"→R 등 (첫 글자=투구손)
                        handedness = None
                        if i_hand < len(cells) and cells[i_hand]:
                            h = cells[i_hand]
                            if h.startswith("좌"):
                                handedness = "L"
                            elif h.startswith("우"):
                                handedness = "R"

                        results.append(PitcherStatsRaw(
                            external_id=f"kbo_{season}_{team_short}_{name}",
                            name=name,
                            team_short=team_short,
                            season=season,
                            era=era,
                            whip=whip,
                            k9=k9,
                            ip=ip,
                            wins=0,
                            losses=0,
                            handedness=handedness,
                        ))
                    except (IndexError, ValueError, KeyError):
                        continue

        except Exception as e:
            logger.error(f"KBO 투수 통계 스크래핑 실패 ({season}): {e}")

        if results:
            logger.info(f"statiz: {len(results)}명 수집 완료 ({season})")
            try:
                cache_path.write_text(
                    json.dumps(
                        [dataclasses.asdict(r) for r in results],
                        ensure_ascii=False,
                        default=str,
                    ),
                    encoding="utf-8",
                )
            except Exception as e:
                logger.warning(f"캐시 저장 실패: {e}")

        return results

    def _parse_innings(self, ip_str: str) -> float:
        """이닝 문자열 파싱 (예: '120.1' → 120.33, '98 1/3' → 98.33)"""
        if not ip_str or ip_str in ("-", ""):
            return 0.0
        try:
            ip_str = ip_str.strip()
            if " " in ip_str:
                parts = ip_str.split()
                whole = float(parts[0])
                frac = float(parts[1].split("/")[0]) / float(parts[1].split("/")[1])
                return whole + frac
            return float(ip_str)
        except (ValueError, ZeroDivisionError):
            return 0.0

    async def fetch_batting_stats_season(self, season: int) -> list[dict]:
        """시즌 전체 타자 통계 스크래핑 (캐시 지원)"""
        return await asyncio.to_thread(self._fetch_batting_stats_sync, season)

    def _fetch_batting_stats_sync(self, season: int) -> list[dict]:
        """statiz.co.kr KBO 시즌 타자 통계 스크래핑
        URL: /stats/?m=main&m2=batting&year={season}&ipp=500
        """
        import dataclasses
        import json
        from pathlib import Path
        from bs4 import BeautifulSoup

        cache_path = Path(f"data/raw/kbo_batting_stats_{season}.json")
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        current_year = time.localtime().tm_year
        cache_ttl_seconds = 7 * 24 * 3600 if season >= current_year else None

        if cache_path.exists():
            expired = (
                cache_ttl_seconds is not None
                and (time.time() - cache_path.stat().st_mtime) > cache_ttl_seconds
            )
            if not expired:
                try:
                    return json.loads(cache_path.read_text(encoding="utf-8"))
                except Exception:
                    cache_path.unlink(missing_ok=True)

        results: list[dict] = []
        base_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9",
        }

        try:
            with httpx.Client(timeout=30, follow_redirects=True, headers=base_headers) as client:
                if not self._statiz_login(client):
                    logger.warning(f"statiz 로그인 실패 — {season} 타자 통계 수집 불가")
                    return []

                url = f"{STATIZ_STATS_URL}?m=main&m2=batting&year={season}&ipp=500"
                resp = client.get(url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                table = soup.find("table")
                if not table:
                    logger.warning(f"statiz: 타자 통계 테이블 없음 ({season})")
                    return []

                rows = table.find_all("tr")
                if len(rows) < 3:
                    return []

                header_cells = rows[0].find_all(["th", "td"])
                headers = [h.get_text(strip=True) for h in header_cells]
                idx: dict[str, int] = {h: i for i, h in enumerate(headers)}

                # statiz 타자 테이블: '비율' 헤더 이후에 AVG/OBP/SLG/OPS/wOBA/wRC+ 순서
                i_name = idx.get("Name", 1)
                i_team = idx.get("Team", 2)
                i_pa   = idx.get("PA", 7)
                i_so   = idx.get("SO", 22)
                # '비율' 헤더 위치 기준으로 OPS(+3), wRC+(+5) 계산
                i_biyul = idx.get("비율", 26)
                i_ops   = i_biyul + 3   # AVG, OBP, SLG, OPS 순
                i_wrc   = i_biyul + 5   # AVG, OBP, SLG, OPS, wOBA, wRC+

                for tr in rows[1:]:
                    raw_cells = tr.find_all(["td", "th"])
                    cells = [td.get_text(strip=True) for td in raw_cells]
                    if not cells or cells[0] in ("", "WAR") or not cells[0].isdigit():
                        continue
                    if len(cells) < i_wrc + 1:
                        continue

                    try:
                        name = cells[i_name]

                        # 팀: SVG img src에서 코드 추출
                        team_short = ""
                        if i_team < len(raw_cells):
                            img = raw_cells[i_team].find("img")
                            if img:
                                m = re.search(r"/(\d+)\.svg", img.get("src", ""))
                                if m:
                                    team_short = STATIZ_TEAM_CODE_TO_SHORT.get(m.group(1), "")
                        if not team_short:
                            # 텍스트에서 숫자/포지션 제거 후 팀명 매핑
                            raw_text = re.sub(r"[\d]+[A-Z]+", "", cells[i_team]).strip()
                            team_short = KBO_TEAM_NAME_TO_SHORT.get(raw_text, "")

                        pa_s  = cells[i_pa]
                        so_s  = cells[i_so]
                        ops_s = cells[i_ops]
                        wrc_s = cells[i_wrc]

                        pa = int(pa_s) if pa_s.isdigit() else 0
                        if pa < 5:  # 5타석 미만만 제외 (시즌 초반 대응)
                            continue

                        ops    = float(ops_s) if ops_s and ops_s not in ("-", "") else 0.740
                        wrc    = float(wrc_s) if wrc_s and wrc_s not in ("-", "") else 100.0
                        so     = float(so_s)  if so_s  and so_s  not in ("-", "") else 0.0
                        k_rate = (so / pa)    if pa > 0 else 0.200

                        results.append({
                            "name":      name,
                            "team_short": team_short,
                            "season":    season,
                            "pa":        pa,
                            "ops":       ops,
                            "wrc_plus":  wrc,
                            "k_rate":    k_rate,
                        })
                    except (IndexError, ValueError):
                        continue

        except Exception as e:
            logger.error(f"KBO 타자 통계 스크래핑 실패 ({season}): {e}")

        if results:
            logger.info(f"statiz: 타자 {len(results)}명 수집 완료 ({season})")
            try:
                cache_path.write_text(
                    json.dumps(results, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception as e:
                logger.warning(f"타자 캐시 저장 실패: {e}")

        return results

    async def fetch_team_batting_stats(self, team_short: str, season: int) -> Optional[dict]:
        """팀 타선 집계 (OPS/wRC+/K% 평균, PA 가중)"""
        all_stats = await self.fetch_batting_stats_season(season)
        team_batters = [b for b in all_stats if b["team_short"] == team_short]
        if not team_batters:
            return None

        total_pa = sum(b["pa"] for b in team_batters)
        if total_pa == 0:
            return None

        weighted_ops   = sum(b["ops"]      * b["pa"] for b in team_batters) / total_pa
        weighted_wrc   = sum(b["wrc_plus"] * b["pa"] for b in team_batters) / total_pa
        weighted_krate = sum(b["k_rate"]   * b["pa"] for b in team_batters) / total_pa

        return {
            "ops":      round(weighted_ops,   3),
            "wrc_plus": round(weighted_wrc,   1),
            "k_rate":   round(weighted_krate, 3),
        }

    async def fetch_team_rotation_era(self, team_short: str, season: int, min_ip: float = 20.0) -> Optional[float]:
        """팀 로테이션 ERA (IP 기준 상위 5선발 가중 평균)"""
        all_stats = await self.fetch_pitcher_stats_season(season)
        team_pitchers = [p for p in all_stats if p.team_short == team_short and p.ip >= min_ip]
        if not team_pitchers:
            return None
        # IP 기준 상위 5명
        top5 = sorted(team_pitchers, key=lambda p: p.ip, reverse=True)[:5]
        total_ip = sum(p.ip for p in top5)
        if total_ip == 0:
            return None
        return sum(p.era * p.ip for p in top5) / total_ip

    async def fetch_team_bullpen_stats(self, team_short: str, season: int) -> Optional[dict]:
        """팀 불펜 스탯 (GR > GS 투수들의 IP 가중 평균 ERA/WHIP)"""
        return await asyncio.to_thread(self._fetch_team_bullpen_sync, team_short, season)

    def _fetch_team_bullpen_sync(self, team_short: str, season: int) -> Optional[dict]:
        from bs4 import BeautifulSoup
        from pathlib import Path
        import json, time

        cache_path = Path(f"data/raw/kbo_bullpen_stats_{season}.json")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_ttl = 7 * 24 * 3600

        # 캐시 로드
        all_bullpen: dict = {}
        if cache_path.exists():
            expired = (time.time() - cache_path.stat().st_mtime) > cache_ttl
            if not expired:
                try:
                    all_bullpen = json.loads(cache_path.read_text(encoding="utf-8"))
                    return all_bullpen.get(team_short)
                except Exception:
                    cache_path.unlink(missing_ok=True)

        base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }

        try:
            with httpx.Client(timeout=30, follow_redirects=True, headers=base_headers) as client:
                if not self._statiz_login(client):
                    return None

                resp = client.get(f"{STATIZ_STATS_URL}?m=main&m2=pitching&year={season}&ipp=500")
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                table = soup.find("table")
                if not table:
                    return None

                rows = table.find_all("tr")
                if len(rows) < 3:
                    return None

                header_cells = rows[0].find_all(["th", "td"])
                headers = [h.get_text(strip=True) for h in header_cells]
                idx = {h: i for i, h in enumerate(headers)}

                i_name  = idx.get("Name", 1)
                i_team  = idx.get("Team", 2)
                i_gs    = idx.get("GS",   5)
                i_gr    = idx.get("GR",   6)
                i_ip    = idx.get("IP",  14)
                i_era   = idx.get("ERA", 30)
                i_whip  = idx.get("WHIP",35)

                # 팀별 불펜 투수 수집
                team_relievers: dict[str, list] = {}

                for tr in rows[1:]:
                    raw_cells = tr.find_all(["td", "th"])
                    cells = [td.get_text(strip=True) for td in raw_cells]
                    if not cells or not cells[0].isdigit():
                        continue
                    if len(cells) < max(i_era, i_whip) + 1:
                        continue

                    try:
                        gs = int(cells[i_gs] or 0)
                        gr = int(cells[i_gr] or 0)
                        if gr <= gs:  # 선발이 더 많으면 스킵
                            continue

                        ip = self._parse_innings(cells[i_ip])
                        if ip < 0.1:
                            continue

                        # 팀 코드 추출
                        t_short = ""
                        if i_team < len(raw_cells):
                            img = raw_cells[i_team].find("img")
                            if img:
                                m = re.search(r"/(\d+)\.svg", img.get("src", ""))
                                if m:
                                    t_short = STATIZ_TEAM_CODE_TO_SHORT.get(m.group(1), "")
                        if not t_short:
                            t_short = KBO_TEAM_NAME_TO_SHORT.get(cells[i_team].strip(), "")
                        if not t_short:
                            continue

                        era_s  = cells[i_era]
                        whip_s = cells[i_whip]
                        era  = float(era_s)  if era_s  not in ("-", "", None) else 4.50
                        whip = float(whip_s) if whip_s not in ("-", "", None) else 1.35

                        team_relievers.setdefault(t_short, []).append({"era": era, "whip": whip, "ip": ip})
                    except (ValueError, IndexError):
                        continue

                # 팀별 IP 가중 평균
                for t, relievers in team_relievers.items():
                    total_ip = sum(r["ip"] for r in relievers)
                    if total_ip > 0:
                        all_bullpen[t] = {
                            "bullpen_era":  round(sum(r["era"]  * r["ip"] for r in relievers) / total_ip, 2),
                            "bullpen_whip": round(sum(r["whip"] * r["ip"] for r in relievers) / total_ip, 2),
                            "bullpen_count": len(relievers),
                        }

                # 캐시 저장
                cache_path.write_text(json.dumps(all_bullpen, ensure_ascii=False), encoding="utf-8")
                return all_bullpen.get(team_short)

        except Exception as e:
            logger.error(f"KBO 불펜 스탯 수집 실패 ({team_short}, {season}): {e}")
            return None

    async def fetch_team_batting_split_stats(self, season: int) -> dict:
        """팀별 vs LHP / vs RHP 타선 OPS 수집
        statiz split 파라미터: ph=1(좌완 상대), ph=2(우완 상대)
        반환: {"삼성": {"vs_lhp": {"ops": 0.710, "pa": 350}, "vs_rhp": {...}}, ...}
        """
        return await asyncio.to_thread(self._fetch_batting_split_sync, season)

    def _fetch_batting_split_sync(self, season: int) -> dict:
        from bs4 import BeautifulSoup
        from pathlib import Path
        import json, time

        cache_path = Path(f"data/raw/kbo_batting_split_{season}.json")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_ttl = 7 * 24 * 3600

        if cache_path.exists():
            if (time.time() - cache_path.stat().st_mtime) < cache_ttl:
                try:
                    return json.loads(cache_path.read_text(encoding="utf-8"))
                except Exception:
                    cache_path.unlink(missing_ok=True)

        base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }

        all_splits: dict = {}

        # ph=1: vs 좌완, ph=2: vs 우완
        split_map = {"vs_lhp": "1", "vs_rhp": "2"}

        try:
            with httpx.Client(timeout=30, follow_redirects=True, headers=base_headers) as client:
                if not self._statiz_login(client):
                    logger.warning("statiz 로그인 실패 — 타선 스플릿 수집 불가")
                    return {}

                for split_key, ph_val in split_map.items():
                    url = (
                        f"{STATIZ_STATS_URL}?m=main&m2=batting"
                        f"&year={season}&ipp=500&ph={ph_val}"
                    )
                    try:
                        resp = client.get(url)
                        resp.raise_for_status()
                    except Exception as e:
                        logger.warning(f"타선 스플릿 수집 실패 ({split_key}): {e}")
                        continue

                    soup = BeautifulSoup(resp.text, "lxml")
                    table = soup.find("table")
                    if not table:
                        logger.warning(f"statiz: 타선 스플릿 테이블 없음 ({split_key})")
                        continue

                    rows = table.find_all("tr")
                    if len(rows) < 3:
                        continue

                    header_cells = rows[0].find_all(["th", "td"])
                    headers = [h.get_text(strip=True) for h in header_cells]
                    idx = {h: i for i, h in enumerate(headers)}

                    i_name = idx.get("Name", 1)
                    i_team = idx.get("Team", 2)
                    i_pa   = idx.get("PA", 7)
                    i_biyul = idx.get("비율", 26)
                    i_ops = i_biyul + 3

                    # 팀별 PA 가중 OPS 집계
                    team_data: dict[str, dict] = {}
                    for tr in rows[1:]:
                        raw_cells = tr.find_all(["td", "th"])
                        cells = [td.get_text(strip=True) for td in raw_cells]
                        if not cells or not cells[0].isdigit():
                            continue
                        if len(cells) < i_ops + 1:
                            continue
                        try:
                            team_short = ""
                            if i_team < len(raw_cells):
                                img = raw_cells[i_team].find("img")
                                if img:
                                    m = re.search(r"/(\d+)\.svg", img.get("src", ""))
                                    if m:
                                        team_short = STATIZ_TEAM_CODE_TO_SHORT.get(m.group(1), "")
                            if not team_short:
                                team_short = KBO_TEAM_NAME_TO_SHORT.get(cells[i_team].strip(), "")
                            if not team_short:
                                continue

                            pa_s  = cells[i_pa]
                            ops_s = cells[i_ops]
                            pa  = int(pa_s)  if pa_s.isdigit() else 0
                            ops = float(ops_s) if ops_s and ops_s not in ("-", "") else None
                            if pa < 5 or ops is None:
                                continue

                            if team_short not in team_data:
                                team_data[team_short] = {"ops_sum": 0.0, "pa_total": 0}
                            team_data[team_short]["ops_sum"] += ops * pa
                            team_data[team_short]["pa_total"] += pa
                        except (ValueError, IndexError):
                            continue

                    for t_short, d in team_data.items():
                        if d["pa_total"] == 0:
                            continue
                        if t_short not in all_splits:
                            all_splits[t_short] = {}
                        all_splits[t_short][split_key] = {
                            "ops": round(d["ops_sum"] / d["pa_total"], 3),
                            "pa": d["pa_total"],
                        }
                    logger.info(f"타선 스플릿 수집 완료: {split_key} → {len(team_data)}팀")

        except Exception as e:
            logger.error(f"KBO 타선 스플릿 수집 실패 ({season}): {e}")

        if all_splits:
            cache_path.write_text(json.dumps(all_splits, ensure_ascii=False), encoding="utf-8")

        return all_splits
