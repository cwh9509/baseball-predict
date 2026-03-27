"""
NPB (일본 프로야구) 데이터 수집기 — npb.jp 공식 사이트
"""
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.collectors.base_collector import (
    BaseCollector,
    GameLogRaw,
    GameRaw,
    PitcherStatsRaw,
    TeamRaw,
)

logger = logging.getLogger(__name__)

# ─── 팀 데이터 ───────────────────────────────────────────────
NPB_TEAMS: dict[str, dict] = {
    # 센트럴 리그
    "巨人":    {"name": "요미우리 자이언츠",    "city": "도쿄",   "stadium": "도쿄돔",          "lat": 35.7056, "lon": 139.7519, "roof": "dome"},
    "阪神":    {"name": "한신 타이거즈",        "city": "니시노미야", "stadium": "한신 고시엔 구장", "lat": 34.7194, "lon": 135.3625, "roof": "open"},
    "広島":    {"name": "히로시마 도요 카프",   "city": "히로시마", "stadium": "MAZDA Zoom-Zoom 스타디움 히로시마", "lat": 34.3967, "lon": 132.4833, "roof": "open"},
    "DeNA":   {"name": "요코하마 DeNA 베이스타즈", "city": "요코하마", "stadium": "요코하마 스타디움", "lat": 35.4436, "lon": 139.6380, "roof": "open"},
    "ヤクルト": {"name": "도쿄 야쿠르트 스왈로즈", "city": "도쿄",  "stadium": "메이지진구 야구장", "lat": 35.6746, "lon": 139.7167, "roof": "open"},
    "中日":    {"name": "주니치 드래건스",       "city": "나고야", "stadium": "반테린 돔 나고야",  "lat": 35.1858, "lon": 136.9361, "roof": "dome"},
    # 퍼시픽 리그
    "ソフトバンク": {"name": "후쿠오카 소프트뱅크 호크스", "city": "후쿠오카", "stadium": "미즈호 PayPay 돔 후쿠오카", "lat": 33.6063, "lon": 130.3644, "roof": "dome"},
    "楽天":    {"name": "도호쿠 라쿠텐 골든이글스", "city": "센다이", "stadium": "라쿠텐 모바일 파크 미야기", "lat": 38.2580, "lon": 140.9019, "roof": "open"},
    "ロッテ":   {"name": "치바 롯데 마린즈",     "city": "치바",   "stadium": "ZOZO 마린 스타디움", "lat": 35.6450, "lon": 140.0319, "roof": "open"},
    "オリックス": {"name": "오릭스 버팔로즈",    "city": "오사카", "stadium": "교세라 돔 오사카",   "lat": 34.6700, "lon": 135.4936, "roof": "dome"},
    "日本ハム": {"name": "홋카이도 닛폰햄 파이터즈", "city": "기타히로시마", "stadium": "에스콘 필드 홋카이도", "lat": 42.9694, "lon": 141.7375, "roof": "open"},
    "西武":    {"name": "사이타마 세이부 라이온즈", "city": "도코로자와", "stadium": "벨루나 돔",  "lat": 35.7986, "lon": 139.4083, "roof": "dome"},
}

# npb.jp 사이트 팀명 → DB short_name 매핑 (다양한 표기 처리)
NPB_TEAM_NAME_MAP: dict[str, str] = {
    # 센트럴
    "巨人": "巨人", "読売": "巨人", "Giants": "巨人", "G": "巨人",
    "阪神": "阪神", "Tigers": "阪神", "T": "阪神",
    "広島": "広島", "Carp": "広島", "C": "広島",
    "DeNA": "DeNA", "横浜": "DeNA", "BayStars": "DeNA", "DB": "DeNA",
    "ヤクルト": "ヤクルト", "Swallows": "ヤクルト", "S": "ヤクルト",
    "中日": "中日", "Dragons": "中日", "D": "中日",
    # 퍼시픽
    "ソフトバンク": "ソフトバンク", "SoftBank": "ソフトバンク", "Hawks": "ソフトバンク", "H": "ソフトバンク",
    "楽天": "楽天", "Eagles": "楽天", "E": "楽天",
    "ロッテ": "ロッテ", "Marines": "ロッテ", "M": "ロッテ",
    "オリックス": "オリックス", "Buffaloes": "オリックス", "Bs": "オリックス",
    "日本ハム": "日本ハム", "Fighters": "日本ハム", "F": "日本ハム",
    "西武": "西武", "Lions": "西武", "L": "西武",
}

# 리그 평균
NPB_LEAGUE_AVG = {"era": 3.80, "whip": 1.25, "k9": 8.2}

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
    "Referer": "https://npb.jp/",
}


class NPBCollector(BaseCollector):

    def __init__(self):
        pass

    async def fetch_all_teams(self) -> list[TeamRaw]:
        return [
            TeamRaw(
                league="NPB",
                short_name=short,
                name=info["name"],
                city=info["city"],
                stadium_name=info["stadium"],
                stadium_lat=info["lat"],
                stadium_lon=info["lon"],
                roof_type=info["roof"],
            )
            for short, info in NPB_TEAMS.items()
        ]

    async def fetch_schedule(self, target_date: date) -> list[GameRaw]:
        return await asyncio.to_thread(self._fetch_month_sync, target_date, scheduled_only=True)

    async def fetch_game_results(self, target_date: date) -> list[GameRaw]:
        return await asyncio.to_thread(self._fetch_month_sync, target_date, scheduled_only=False)

    def _fetch_month_sync(self, target_date: date, scheduled_only: bool) -> list[GameRaw]:
        """npb.jp 경기 일정/결과 스크래핑

        1차: 영문 일별 스코어 페이지 (bis/eng) — 날짜 정확, 파싱 쉬움
        2차: 일본어 월별 페이지 (schedule_{MM}_detail.html)
        """
        try:
            time.sleep(0.5)

            # 1차: 영문 일별 페이지
            eng_url = (
                f"https://npb.jp/bis/eng/{target_date.year}/games/"
                f"gm{target_date.strftime('%Y%m%d')}.html"
            )
            resp = httpx.get(eng_url, headers=REQUEST_HEADERS, timeout=20, follow_redirects=True)

            if resp.status_code == 200:
                text = resp.content.decode("utf-8", errors="replace")
                games = self._parse_eng_daily(text, target_date, scheduled_only)
                if games:
                    return games
                # 경기 없는 날은 빈 리스트 정상 반환
                return []

            # 2차: 일본어 월별 페이지 (연도는 경로에, 월만 2자리로 파일명에)
            jpn_url = (
                f"https://npb.jp/games/{target_date.year}/"
                f"schedule_{target_date.month:02d}_detail.html"
            )
            resp2 = httpx.get(jpn_url, headers=REQUEST_HEADERS, timeout=20, follow_redirects=True)
            if resp2.status_code == 200:
                try:
                    text2 = resp2.content.decode("utf-8", errors="replace")
                except Exception:
                    text2 = resp2.content.decode("shift_jis", errors="replace")
                return self._parse_schedule_html(text2, target_date, scheduled_only)

            logger.warning(f"NPB 스케줄 HTTP 오류 ({target_date}): eng={resp.status_code}, jpn={resp2.status_code}")
            return []

        except Exception as e:
            logger.error(f"NPB 스케줄 수집 실패 ({target_date}): {e}")
            return []

    def _parse_eng_daily(
        self, html: str, target_date: date, scheduled_only: bool
    ) -> list[GameRaw]:
        """npb.jp 영문 일별 스코어 페이지 파싱
        URL: /bis/eng/{year}/games/gm{YYYYMMDD}.html
        """
        soup = BeautifulSoup(html, "lxml")
        games: list[GameRaw] = []

        # 경기 블록: 각 경기는 보통 table 또는 div.game 단위
        # 팀명은 영문 (Giants, Tigers, ...) 또는 약어
        game_blocks = (
            soup.find_all("table", {"class": re.compile(r"score|game|box", re.I)})
            or soup.find_all("div", {"class": re.compile(r"game|score|box", re.I)})
            or soup.find_all("table")
        )

        seen: set[str] = set()
        for block in game_blocks:
            text = block.get_text()

            # 팀명 추출 (영문 팀명 → short_name)
            teams_found: list[str] = []
            for key, short in NPB_TEAM_NAME_MAP.items():
                if key in text and short not in teams_found:
                    teams_found.append(short)
                if len(teams_found) == 2:
                    break

            if len(teams_found) < 2:
                continue

            # 점수 추출
            scores = re.findall(r"\b(\d{1,2})\b", text)
            status = "scheduled"
            away_score, home_score = None, None
            if len(scores) >= 2:
                try:
                    away_score = int(scores[0])
                    home_score = int(scores[1])
                    status = "final"
                except ValueError:
                    pass

            if scheduled_only and status != "scheduled":
                continue

            away_short, home_short = teams_found[0], teams_found[1]
            ext_id = f"NPB_{target_date.strftime('%Y%m%d')}_{away_short}_{home_short}"
            if ext_id in seen:
                continue
            seen.add(ext_id)

            time_match = re.search(r"(\d{1,2}):(\d{2})", text)
            game_time = f"{int(time_match.group(1)):02d}:{time_match.group(2)}:00" if time_match else None

            games.append(GameRaw(
                league="NPB",
                game_date=target_date,
                game_time_local=game_time,
                home_team_short=home_short,
                away_team_short=away_short,
                venue=NPB_TEAMS.get(home_short, {}).get("stadium", ""),
                status=status,
                home_score=home_score,
                away_score=away_score,
                external_game_id=ext_id,
            ))

        return games

    def _parse_schedule_html(
        self, html: str, target_date: date, scheduled_only: bool
    ) -> list[GameRaw]:
        """npb.jp 스케줄 HTML 파싱"""
        soup = BeautifulSoup(html, "lxml")
        games: list[GameRaw] = []

        # npb.jp 스케줄 표 구조 탐색
        # 날짜별 섹션 또는 테이블로 구성
        schedule_tables = soup.find_all("table", {"class": re.compile(r"schedule|game", re.I)})
        if not schedule_tables:
            schedule_tables = soup.find_all("table")

        current_date: Optional[date] = None

        for table in schedule_tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue

                row_text = row.get_text()

                # 날짜 행 감지 (예: "3月28日", "4/1" 등)
                date_match = re.search(
                    rf"(\d{{1,2}})月(\d{{1,2}})日|{target_date.month}/(\d{{1,2}})",
                    row_text,
                )
                if date_match:
                    try:
                        if date_match.group(1):  # M月D日 형식
                            m, d = int(date_match.group(1)), int(date_match.group(2))
                        else:  # M/D 형식
                            m, d = target_date.month, int(date_match.group(3))
                        current_date = date(target_date.year, m, d)
                    except ValueError:
                        pass
                    continue

                if current_date != target_date:
                    continue

                # 팀명 추출
                teams_found = []
                for cell in cells:
                    cell_text = cell.get_text(strip=True)
                    mapped = self._map_team_name(cell_text)
                    if mapped:
                        teams_found.append(mapped)

                if len(teams_found) < 2:
                    continue

                # 점수 추출
                scores = re.findall(r"\b(\d{1,2})\b", row_text)
                home_score, away_score = None, None
                status = "scheduled"

                if len(scores) >= 2:
                    try:
                        away_score = int(scores[0])
                        home_score = int(scores[1])
                        status = "final"
                    except ValueError:
                        pass

                if scheduled_only and status != "scheduled":
                    continue

                # 경기 시간 추출
                time_match = re.search(r"(\d{2}):(\d{2})", row_text)
                game_time = f"{time_match.group(1)}:{time_match.group(2)}:00" if time_match else None

                # away vs home 판단 (보통 원정 @ 홈 순서)
                away_short = teams_found[0]
                home_short = teams_found[1]
                stadium = NPB_TEAMS.get(home_short, {}).get("stadium", "")

                ext_id = f"NPB_{target_date.strftime('%Y%m%d')}_{away_short}_{home_short}"

                games.append(GameRaw(
                    league="NPB",
                    game_date=current_date,
                    game_time_local=game_time,
                    home_team_short=home_short,
                    away_team_short=away_short,
                    venue=stadium,
                    status=status,
                    home_score=home_score,
                    away_score=away_score,
                    external_game_id=ext_id,
                ))

        if not games:
            logger.debug(f"NPB: {target_date} 스케줄 파싱 결과 0경기 (HTML 구조 확인 필요)")

        return games

    def _map_team_name(self, text: str) -> Optional[str]:
        """텍스트에서 NPB 팀명 추출"""
        text = text.strip()
        if text in NPB_TEAM_NAME_MAP:
            return NPB_TEAM_NAME_MAP[text]
        for key, short in NPB_TEAM_NAME_MAP.items():
            if key in text:
                return short
        return None

    async def fetch_team_game_log(self, team_short: str, n_games: int = 10) -> list[GameLogRaw]:
        logger.warning("NPB fetch_team_game_log not implemented")
        return []

    async def fetch_pitcher_stats(self, external_id: str, season: int) -> Optional[PitcherStatsRaw]:
        all_stats = await self.fetch_pitcher_stats_season(season)
        for s in all_stats:
            if s.external_id == external_id:
                return s
        return None

    async def fetch_pitcher_stats_season(self, season: int) -> list[PitcherStatsRaw]:
        """시즌 전체 투수 통계 스크래핑 (캐시 지원)"""
        return await asyncio.to_thread(self._fetch_pitcher_stats_sync, season)

    def _fetch_pitcher_stats_sync(self, season: int) -> list[PitcherStatsRaw]:
        """npb.jp 투수 통계 스크래핑"""
        cache_path = Path(f"data/raw/npb_pitcher_stats_{season}.json")
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                return [PitcherStatsRaw(**r) for r in cached]
            except Exception:
                cache_path.unlink(missing_ok=True)

        results: list[PitcherStatsRaw] = []

        # npb.jp 투수 성적 페이지 시도
        stat_urls = [
            f"https://npb.jp/bis/players/stats/pitching_{season}.html",
            f"https://npb.jp/statistics/stats/{season}/",
            f"https://npb.jp/games/{season}/stats/pitching.html",
        ]

        for url in stat_urls:
            try:
                resp = httpx.get(url, headers=REQUEST_HEADERS, timeout=20, follow_redirects=True)
                if resp.status_code != 200:
                    continue
                try:
                    text = resp.content.decode("utf-8", errors="replace")
                except Exception:
                    text = resp.content.decode("shift_jis", errors="replace")

                results = self._parse_pitcher_stats_html(text, season)
                if results:
                    logger.info(f"NPB 투수 통계 {len(results)}명 수집 ({season}) from {url}")
                    break
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"NPB 투수 통계 URL 실패 ({url}): {e}")
                continue

        if not results:
            logger.warning(f"NPB 투수 통계 수집 실패 ({season}) — 리그 평균값으로 대체됩니다")

        # 캐시 저장
        if results:
            import dataclasses
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
                logger.warning(f"NPB 투수 통계 캐시 저장 실패: {e}")

        return results

    def _parse_pitcher_stats_html(self, html: str, season: int) -> list[PitcherStatsRaw]:
        """투수 통계 HTML 테이블 파싱"""
        soup = BeautifulSoup(html, "lxml")
        results = []

        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 3:
                continue

            # 헤더 파싱
            header_cells = rows[0].find_all(["th", "td"])
            headers = [h.get_text(strip=True) for h in header_cells]

            # ERA, WHIP, IP 컬럼 인덱스 탐색
            idx = {}
            for i, h in enumerate(headers):
                h_lower = h.lower()
                if h in ("ERA", "防御率") or h_lower == "era":
                    idx["era"] = i
                elif h in ("WHIP",) or h_lower == "whip":
                    idx["whip"] = i
                elif h in ("IP", "投球回", "回") or h_lower in ("ip", "投球回"):
                    idx["ip"] = i
                elif h in ("SO", "K", "奪三振") or h_lower in ("so", "k", "奪三振"):
                    idx["so"] = i
                elif h in ("選手名", "投手名", "選手") or h_lower in ("name", "pitcher"):
                    idx["name"] = i
                elif h in ("チーム", "球団") or h_lower in ("team",):
                    idx["team"] = i

            if "era" not in idx or "ip" not in idx:
                continue

            page_count = 0
            for tr in rows[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if not cells or len(cells) < 5:
                    continue
                try:
                    name = cells[idx.get("name", 1)]
                    team_raw = cells[idx.get("team", 2)]
                    team_short = NPB_TEAM_NAME_MAP.get(team_raw.strip(), team_raw.strip())

                    ip_str = cells[idx["ip"]]
                    era_str = cells[idx["era"]]
                    whip_str = cells.get(idx["whip"]) if "whip" in idx else None
                    so_str = cells[idx.get("so", -1)] if "so" in idx else "0"

                    ip = self._parse_innings(ip_str)
                    if ip < 5:
                        continue

                    era = float(era_str) if era_str and era_str not in ("-", "") else NPB_LEAGUE_AVG["era"]
                    whip = float(whip_str) if whip_str and whip_str not in ("-", "") else NPB_LEAGUE_AVG["whip"]
                    so = float(so_str) if so_str and so_str.replace(".", "").isdigit() else 0
                    k9 = (so / ip * 9) if ip > 0 else NPB_LEAGUE_AVG["k9"]

                    results.append(PitcherStatsRaw(
                        external_id=f"npb_{season}_{team_short}_{name}",
                        name=name,
                        team_short=team_short,
                        season=season,
                        era=era,
                        whip=whip,
                        k9=k9,
                        ip=ip,
                        wins=0,
                        losses=0,
                    ))
                    page_count += 1
                except (IndexError, ValueError, KeyError, TypeError):
                    continue

            if page_count > 0:
                return results  # 성공적으로 파싱한 테이블 사용

        return results

    def _parse_innings(self, ip_str: str) -> float:
        """이닝 파싱 (예: '120.1' → 120.33, '120⅓' → 120.33)"""
        if not ip_str or ip_str in ("-", ""):
            return 0.0
        ip_str = ip_str.strip()
        # ⅓, ⅔ 유니코드 분수 처리
        ip_str = ip_str.replace("⅓", ".1").replace("⅔", ".2")
        try:
            return float(ip_str)
        except ValueError:
            return 0.0

    async def fetch_team_rotation_era(
        self, team_short: str, season: int, min_ip: float = 20.0
    ) -> Optional[float]:
        """팀 로테이션 ERA (IP 기준 상위 5선발 가중 평균)"""
        all_stats = await self.fetch_pitcher_stats_season(season)
        team_pitchers = [p for p in all_stats if p.team_short == team_short and p.ip >= min_ip]
        if not team_pitchers:
            return None
        top5 = sorted(team_pitchers, key=lambda p: p.ip, reverse=True)[:5]
        total_ip = sum(p.ip for p in top5)
        if total_ip == 0:
            return None
        return sum(p.era * p.ip for p in top5) / total_ip
