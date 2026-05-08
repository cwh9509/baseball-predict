#!/usr/bin/env python3
"""
KBO 시즌 스탯 수집 및 업로드 스크립트
statiz.co.kr에서 투수/타선/불펜/스플릿 스탯을 수집하고
/api/v1/admin/upload-stats로 업로드합니다.

사용법:
  python upload_stats.py --url https://baseball-predict-production.up.railway.app --season 2026
  python upload_stats.py --url http://localhost:8000 --season 2026

환경변수 필요:
  STATIZ_ID   statiz.co.kr 아이디
  STATIZ_PW   statiz.co.kr 비밀번호
"""
import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

STATIZ_BASE_URL = "https://statiz.co.kr"
STATIZ_LOGIN_URL = f"{STATIZ_BASE_URL}/member/handle.php"
STATIZ_STATS_URL = f"{STATIZ_BASE_URL}/stats/"

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

KBO_TEAM_NAME_TO_SHORT: dict[str, str] = {
    "KIA": "KIA", "기아": "KIA",
    "삼성": "삼성", "LG": "LG", "두산": "두산", "한화": "한화",
    "SSG": "SSG", "SK": "SSG", "롯데": "롯데",
    "키움": "키움", "넥센": "키움", "NC": "NC", "KT": "KT",
}

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": STATIZ_BASE_URL,
}


def statiz_login(client: httpx.Client) -> bool:
    uid = os.environ.get("STATIZ_ID", "")
    pw  = os.environ.get("STATIZ_PW", "")
    if not uid or not pw:
        logger.error("STATIZ_ID / STATIZ_PW 환경변수 미설정")
        return False

    cookie_path = Path("data/raw/statiz_cookies.json")
    if cookie_path.exists():
        try:
            saved = json.loads(cookie_path.read_text())
            for name, value in saved.items():
                client.cookies.set(name, value, domain="statiz.co.kr")
            test = client.get(f"{STATIZ_STATS_URL}?m=main&m2=pitching&year=2025&ipp=10")
            if test.status_code == 200 and "로그인" not in test.text[:500]:
                logger.info("저장된 쿠키로 세션 복원 성공")
                return True
            client.cookies.clear()
        except Exception:
            client.cookies.clear()

    try:
        from bs4 import BeautifulSoup
        client.headers.update(BASE_HEADERS)
        r = client.get(f"{STATIZ_BASE_URL}/member/?m=login")
        soup = BeautifulSoup(r.text, "lxml")
        form = soup.find("form", action=lambda a: a and "handle" in (a or ""))
        if not form:
            logger.error("로그인 폼을 찾을 수 없음")
            return False

        hidden = {
            i["name"]: i.get("value", "")
            for i in form.find_all("input", {"type": "hidden"})
            if i.get("name")
        }
        resp = client.post(
            STATIZ_LOGIN_URL,
            data={**hidden, "userID": uid, "userPassword": pw},
            headers={"Referer": f"{STATIZ_BASE_URL}/member/?m=login",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        has_token = "access_token" in client.cookies or "PHPSESSID" in client.cookies
        if not has_token:
            logger.error(f"로그인 실패 (status={resp.status_code})")
            return False

        test = client.get(f"{STATIZ_STATS_URL}?m=main&m2=pitching&year=2025&ipp=10")
        if test.status_code != 200:
            logger.error(f"로그인 후 접근 실패: {test.status_code}")
            return False

        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        cookie_path.write_text(json.dumps(dict(client.cookies)))
        logger.info("로그인 성공")
        return True
    except Exception as e:
        logger.error(f"로그인 실패: {e}")
        return False


def parse_innings(ip_str: str) -> float:
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


def get_team_short(raw_cells, i_team, text_fallback):
    if i_team < len(raw_cells):
        img = raw_cells[i_team].find("img")
        if img:
            m = re.search(r"/(\d+)\.svg", img.get("src", ""))
            if m:
                return STATIZ_TEAM_CODE_TO_SHORT.get(m.group(1), "")
    return KBO_TEAM_NAME_TO_SHORT.get(text_fallback.strip(), "")


def scrape_pitchers(client: httpx.Client, season: int) -> list[dict]:
    """시즌 투수 스탯 수집 (선발/불펜 구분 포함)"""
    from bs4 import BeautifulSoup
    url = f"{STATIZ_STATS_URL}?m=main&m2=pitching&year={season}&ipp=500"
    time.sleep(0.5)
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table")
    if not table:
        logger.warning(f"투수 테이블 없음 ({season}) — status={resp.status_code} url={url} body_snippet={resp.text[:300]!r}")
        return []

    rows = table.find_all("tr")
    if len(rows) < 3:
        return []

    headers = [h.get_text(strip=True) for h in rows[0].find_all(["th", "td"])]
    idx = {h: i for i, h in enumerate(headers)}

    i_name = idx.get("Name", 1)
    i_team = idx.get("Team", 2)
    i_hand = idx.get("투/타", idx.get("투타", 3))
    i_gs   = idx.get("GS",   5)
    i_ip   = idx.get("IP",  14)
    i_so   = idx.get("SO",  26)
    i_era  = idx.get("ERA", 30)
    i_whip = idx.get("WHIP", 35)
    logger.info(f"투수 컬럼: name={i_name} team={i_team} hand={i_hand} gs={i_gs} ip={i_ip} era={i_era} whip={i_whip}")

    results = []
    for tr in rows[1:]:
        raw_cells = tr.find_all(["td", "th"])
        cells = [td.get_text(strip=True) for td in raw_cells]
        if not cells or cells[0] in ("", "WAR") or not cells[0].isdigit():
            continue
        if len(cells) < max(i_era, i_whip) + 1:
            continue
        try:
            raw_name_cell = raw_cells[i_name] if i_name < len(raw_cells) else None
            # 이름 셀에서 링크 텍스트만 추출 (배지/아이콘 텍스트 제외)
            if raw_name_cell:
                link = raw_name_cell.find("a")
                name = link.get_text(strip=True) if link else cells[i_name]
            else:
                name = cells[i_name]
            team_short = get_team_short(raw_cells, i_team, cells[i_team] if i_team < len(cells) else "")
            if not team_short or not name:
                continue

            ip = parse_innings(cells[i_ip])
            if ip < 1:
                continue

            gs_val = None
            if i_gs < len(cells):
                try:
                    gs_val = int(cells[i_gs])
                except ValueError:
                    gs_val = None

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

            handedness = None
            if i_hand < len(cells) and cells[i_hand]:
                h = cells[i_hand]
                if h.startswith("좌"):
                    handedness = "L"
                elif h.startswith("우"):
                    handedness = "R"

            results.append({
                "name": name,
                "team_short": team_short,
                "era": round(era, 2),
                "whip": round(whip, 3),
                "k9": round(k9, 2),
                "ip": round(ip, 1),
                "gs": gs_val,
                "handedness": handedness,
            })
        except (IndexError, ValueError, KeyError):
            continue

    logger.info(f"투수 {len(results)}명 수집 ({season})")
    if results:
        logger.info(f"투수 샘플 (첫 5명): {[(p['name'], p['team_short']) for p in results[:5]]}")
    return results


def scrape_recent_pitcher_stats(client: httpx.Client, season: int, days: int = 14) -> dict[str, dict]:
    """최근 N일 투수 ERA/WHIP (name+team_short → {recent_era, recent_whip})"""
    from bs4 import BeautifulSoup
    from datetime import date, timedelta
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    sdate = start_date.strftime("%Y-%m-%d")
    edate = end_date.strftime("%Y-%m-%d")

    url = f"{STATIZ_STATS_URL}?m=main&m2=pitching&year={season}&sdate={sdate}&edate={edate}&ipp=500"
    time.sleep(0.5)
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table")
    if not table:
        return {}

    rows = table.find_all("tr")
    if len(rows) < 3:
        return {}

    headers = [h.get_text(strip=True) for h in rows[0].find_all(["th", "td"])]
    idx = {h: i for i, h in enumerate(headers)}
    i_name = idx.get("Name", 1)
    i_team = idx.get("Team", 2)
    i_ip   = idx.get("IP",  14)
    i_era  = idx.get("ERA", 30)
    i_whip = idx.get("WHIP", 35)

    result = {}
    for tr in rows[1:]:
        raw_cells = tr.find_all(["td", "th"])
        cells = [td.get_text(strip=True) for td in raw_cells]
        if not cells or cells[0] in ("", "WAR") or not cells[0].isdigit():
            continue
        if len(cells) < max(i_era, i_whip) + 1:
            continue
        try:
            raw_name_cell = raw_cells[i_name] if i_name < len(raw_cells) else None
            if raw_name_cell:
                link = raw_name_cell.find("a")
                name = link.get_text(strip=True) if link else cells[i_name]
            else:
                name = cells[i_name]
            team_short = get_team_short(raw_cells, i_team, cells[i_team] if i_team < len(cells) else "")
            if not name or not team_short:
                continue
            ip = parse_innings(cells[i_ip])
            if ip < 1:
                continue
            era_s  = cells[i_era]
            whip_s = cells[i_whip]
            era  = float(era_s)  if era_s  and era_s  not in ("-", "") else None
            whip = float(whip_s) if whip_s and whip_s not in ("-", "") else None
            key = f"{name}:{team_short}"
            result[key] = {"recent_era": era, "recent_whip": whip}
        except (IndexError, ValueError):
            continue

    logger.info(f"최근 {days}일 투수 {len(result)}명 수집")
    return result


def scrape_team_batting(client: httpx.Client, season: int) -> list[dict]:
    """팀별 타선 스탯 집계 (개인 타자 데이터에서 팀 평균 계산)"""
    from bs4 import BeautifulSoup
    url = f"{STATIZ_STATS_URL}?m=main&m2=batting&year={season}&ipp=500"
    time.sleep(0.5)
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table")
    if not table:
        logger.warning(f"타선 테이블 없음 ({season})")
        return []

    rows = table.find_all("tr")
    if len(rows) < 3:
        return []

    # statiz 타선 테이블은 헤더가 두 줄 — 합쳐서 인덱스 계산
    headers0 = [h.get_text(strip=True) for h in rows[0].find_all(["th", "td"])]
    headers1 = [h.get_text(strip=True) for h in rows[1].find_all(["th", "td"])]
    headers = headers0 + headers1
    idx = {h: i for i, h in enumerate(headers)}

    i_name = idx.get("Name", 1)
    i_team = idx.get("Team", 2)
    i_pa   = idx.get("PA",   7)
    i_so   = idx.get("SO",   idx.get("K", 22))
    # statiz 타선 테이블 실제 데이터 행: AVG=26, OBP=27, SLG=28, OPS=29, R/ePA=30, wRC+=31, WAR=32
    i_ops  = 29
    i_wrc  = 31
    logger.info(f"타선 컬럼: name={i_name} team={i_team} pa={i_pa} ops={i_ops} so={i_so} wrc={i_wrc}")

    # 팀별 집계 (헤더 두 줄 건너뜀)
    team_data: dict[str, dict] = {}
    for tr in rows[2:]:
        raw_cells = tr.find_all(["td", "th"])
        cells = [td.get_text(strip=True) for td in raw_cells]
        if not cells or cells[0] in ("", "WAR") or not cells[0].isdigit():
            continue
        if len(cells) < i_ops + 1:
            continue
        try:
            team_short = get_team_short(raw_cells, i_team, cells[i_team] if i_team < len(cells) else "")
            if not team_short:
                continue
            pa_s  = cells[i_pa]  if i_pa  < len(cells) else "0"
            ops_s = cells[i_ops] if i_ops < len(cells) else ""
            so_s  = cells[i_so]  if i_so  < len(cells) else "0"
            wrc_s = cells[i_wrc] if i_wrc < len(cells) else ""

            pa  = int(pa_s)  if pa_s  and pa_s  not in ("-", "") else 0
            ops = float(ops_s) if ops_s and ops_s not in ("-", "") else None
            so  = float(so_s)  if so_s  and so_s  not in ("-", "") else 0
            wrc = float(wrc_s) if wrc_s and wrc_s not in ("-", "") else None

            if pa < 3 or ops is None:
                continue

            if team_short not in team_data:
                team_data[team_short] = {"pa_sum": 0, "ops_sum": 0.0, "so_sum": 0.0, "wrc_vals": [], "count": 0}

            d = team_data[team_short]
            d["pa_sum"]    += pa
            d["ops_sum"]   += ops * pa
            d["so_sum"]    += so
            d["count"]     += 1
            if wrc is not None:
                d["wrc_vals"].append(wrc)
        except (IndexError, ValueError):
            continue

    results = []
    for team_short, d in team_data.items():
        if d["pa_sum"] < 10:
            continue
        ops      = d["ops_sum"] / d["pa_sum"]
        wrc_plus = sum(d["wrc_vals"]) / len(d["wrc_vals"]) if d["wrc_vals"] else 100.0
        k_rate   = d["so_sum"] / d["pa_sum"] if d["pa_sum"] > 0 else 0.2
        results.append({
            "team_short": team_short,
            "ops": round(ops, 3),
            "wrc_plus": round(wrc_plus, 1),
            "k_rate": round(k_rate, 3),
        })

    logger.info(f"팀 타선 {len(results)}팀 집계 ({season})")
    return results


def calc_team_bullpen(pitchers: list[dict]) -> list[dict]:
    """개별 투수 데이터에서 팀 불펜 ERA/WHIP 집계 (gs < 5 = 불펜)"""
    team_bullpen: dict[str, list] = {}
    for p in pitchers:
        gs = p.get("gs")
        ip = p.get("ip", 0)
        is_reliever = (gs is not None and gs < 5) or (gs is None and ip < 30)
        if not is_reliever:
            continue
        t = p["team_short"]
        if t not in team_bullpen:
            team_bullpen[t] = []
        team_bullpen[t].append(p)

    results = []
    for team_short, relievers in team_bullpen.items():
        total_ip = sum(r["ip"] for r in relievers)
        if total_ip < 1:
            continue
        bullpen_era  = sum(r["era"]  * r["ip"] for r in relievers) / total_ip
        bullpen_whip = sum(r["whip"] * r["ip"] for r in relievers) / total_ip
        results.append({
            "team_short": team_short,
            "bullpen_era": round(bullpen_era, 2),
            "bullpen_whip": round(bullpen_whip, 3),
            "bullpen_count": len(relievers),
        })

    logger.info(f"팀 불펜 {len(results)}팀 집계")
    return results


def upload(api_url: str, payload: dict) -> bool:
    url = f"{api_url.rstrip('/')}/api/v1/admin/upload-stats"
    try:
        resp = httpx.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"업로드 완료: {data}")
        return True
    except Exception as e:
        logger.error(f"업로드 실패: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="KBO 스탯 수집 및 업로드")
    parser.add_argument("--url", required=True, help="API URL (예: https://baseball-predict-production.up.railway.app)")
    parser.add_argument("--season", type=int, default=2026, help="시즌 연도")
    parser.add_argument("--days", type=int, default=14, help="최근 N일 ERA 수집 범위")
    args = parser.parse_args()

    with httpx.Client(timeout=30, follow_redirects=True, headers=BASE_HEADERS) as client:
        if not statiz_login(client):
            logger.error("statiz 로그인 실패. STATIZ_ID / STATIZ_PW 확인 필요")
            sys.exit(1)

        logger.info("=== 투수 스탯 수집 ===")
        pitchers = scrape_pitchers(client, args.season)
        if not pitchers:
            logger.error("투수 스탯 수집 실패")
            sys.exit(1)

        logger.info("=== 최근 ERA 수집 ===")
        recent_map = scrape_recent_pitcher_stats(client, args.season, args.days)
        # 최근 ERA/WHIP 병합
        for p in pitchers:
            key = f"{p['name']}:{p['team_short']}"
            recent = recent_map.get(key, {})
            p["recent_era"]  = recent.get("recent_era")
            p["recent_whip"] = recent.get("recent_whip")

        logger.info("=== 팀 타선 수집 ===")
        team_batting = scrape_team_batting(client, args.season)

        logger.info("=== 팀 불펜 집계 (개별 투수 기반) ===")
        team_bullpen = calc_team_bullpen(pitchers)

    payload = {
        "season": args.season,
        "pitchers": pitchers,
        "team_batting": team_batting,
        "team_bullpen": team_bullpen,
        "team_batting_splits": [],  # 추후 statiz splits 페이지 추가
    }

    logger.info(f"=== 업로드: 투수 {len(pitchers)}명, 타선 {len(team_batting)}팀, 불펜 {len(team_bullpen)}팀 ===")
    success = upload(args.url, payload)
    if success:
        logger.info("완료! 재학습 트리거:")
        logger.info(f"  curl -X POST '{args.url}/api/v1/admin/retrain'")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
