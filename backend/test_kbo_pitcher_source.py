"""
KBO 투수 통계 소스 진단 스크립트
다양한 URL/방법으로 KBO 투수 통계 접근 가능 여부를 테스트합니다.
"""
import httpx
from bs4 import BeautifulSoup
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def test_koreabaseball_asp(season: int = 2025):
    """koreabaseball.com BasicOld.aspx - ViewState 처리 후 연도 선택"""
    print(f"\n=== koreabaseball.com BasicOld.aspx (season={season}) ===")
    url = "https://www.koreabaseball.com/Record/Player/PitcherBasic/BasicOld.aspx"

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        # 1단계: GET으로 ViewState 추출
        resp = client.get(url, headers=HEADERS)
        print(f"GET status: {resp.status_code}")
        try:
            text = resp.content.decode("cp949", errors="replace")
        except Exception:
            text = resp.text
        soup = BeautifulSoup(text, "lxml")

        # ViewState 확인
        vs = soup.find("input", {"name": "__VIEWSTATE"})
        ev = soup.find("input", {"name": "__EVENTVALIDATION"})
        vsg = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})
        print(f"  __VIEWSTATE: {'있음 (길이=' + str(len(vs['value'])) + ')' if vs else '없음'}")
        print(f"  __EVENTVALIDATION: {'있음' if ev else '없음'}")

        # 시즌 드롭다운 찾기
        selects = soup.find_all("select")
        for sel in selects:
            sel_id = sel.get("id", "")
            sel_name = sel.get("name", "")
            options = [o.get("value", o.text.strip()) for o in sel.find_all("option")]
            print(f"  SELECT id={sel_id!r} name={sel_name!r} options={options[:5]}...")

        # 현재 테이블 확인
        table = soup.find("table", {"class": lambda c: c and "record" in c.lower()}) or soup.find("table")
        if table:
            rows = table.find_all("tr")
            print(f"  현재 테이블 행 수: {len(rows)}")
            if len(rows) > 1:
                # 헤더
                headers_row = rows[0]
                headers_text = [th.get_text(strip=True) for th in headers_row.find_all(["th", "td"])]
                print(f"  헤더: {headers_text}")
                # 첫 번째 데이터 행
                if len(rows) > 1:
                    first_row = [td.get_text(strip=True) for td in rows[1].find_all(["td", "th"])]
                    print(f"  첫 행: {first_row}")
        else:
            print("  테이블 없음")

        # hidden input 전체 목록
        hidden_inputs = soup.find_all("input", {"type": "hidden"})
        print(f"  Hidden inputs ({len(hidden_inputs)}개):")
        for hi in hidden_inputs[:10]:
            name = hi.get("name", "")
            val = hi.get("value", "")
            if name and "__VIEW" not in name and "__EVENT" not in name:
                print(f"    {name} = {val!r}")

        if not vs:
            print("  ViewState 없음 - POST 불가")
            return

        # 2단계: 연도 선택 POST
        season_control = None
        for sel in selects:
            options = sel.find_all("option")
            for opt in options:
                if opt.get("value", "").strip() == str(season) or opt.text.strip() == str(season):
                    season_control = sel.get("name", "")
                    break

        if not season_control:
            # 이름 추측
            for sel in selects:
                if "season" in sel.get("id", "").lower() or "year" in sel.get("id", "").lower():
                    season_control = sel.get("name", "")
                    break

        print(f"  연도 컨트롤 이름: {season_control!r}")

        if season_control:
            post_data = {
                "__VIEWSTATE": vs.get("value", ""),
                "__VIEWSTATEGENERATOR": vsg.get("value", "") if vsg else "",
                "__EVENTVALIDATION": ev.get("value", "") if ev else "",
                "__EVENTTARGET": season_control,
                "__EVENTARGUMENT": "",
                season_control: str(season),
            }
            resp2 = client.post(url, data=post_data, headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": url,
            })
            print(f"  POST status: {resp2.status_code}")
            try:
                text2 = resp2.content.decode("cp949", errors="replace")
            except Exception:
                text2 = resp2.text
            soup2 = BeautifulSoup(text2, "lxml")
            table2 = soup2.find("table", {"class": lambda c: c and "record" in c.lower()}) or soup2.find("table")
            if table2:
                rows2 = table2.find_all("tr")
                print(f"  POST 후 테이블 행 수: {len(rows2)}")
                if len(rows2) > 2:
                    # 헤더
                    h = [th.get_text(strip=True) for th in rows2[0].find_all(["th", "td"])]
                    print(f"  헤더: {h}")
                    # 처음 3명
                    for r in rows2[1:4]:
                        cells = [td.get_text(strip=True) for td in r.find_all(["td", "th"])]
                        print(f"  데이터: {cells}")
            else:
                print("  POST 후 테이블 없음")
                # 에러 메시지 확인
                body = soup2.find("body")
                if body:
                    print(f"  페이지 내용 (앞 300자): {body.get_text()[:300]}")


def test_eng_koreabaseball(season: int = 2025):
    """eng.koreabaseball.com PitchingLeaders.aspx"""
    print(f"\n=== eng.koreabaseball.com PitchingLeaders.aspx (season={season}) ===")
    url = "https://eng.koreabaseball.com/stats/PitchingLeaders.aspx"

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(url, headers=HEADERS)
        print(f"GET status: {resp.status_code}")
        if resp.status_code != 200:
            return

        text = resp.text
        soup = BeautifulSoup(text, "lxml")

        # 시즌 드롭다운
        selects = soup.find_all("select")
        for sel in selects:
            options = [o.get("value", o.text.strip()) for o in sel.find_all("option")]
            print(f"  SELECT id={sel.get('id')!r} options={options[:5]}...")

        # 테이블
        table = soup.find("table")
        if table:
            rows = table.find_all("tr")
            print(f"  테이블 행 수: {len(rows)}")
            if rows:
                h = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
                print(f"  헤더: {h}")
                if len(rows) > 1:
                    d = [td.get_text(strip=True) for td in rows[1].find_all(["td", "th"])]
                    print(f"  첫 행: {d}")
        else:
            print("  테이블 없음")

        # hidden inputs
        vs = soup.find("input", {"name": "__VIEWSTATE"})
        ev = soup.find("input", {"name": "__EVENTVALIDATION"})
        print(f"  ViewState: {'있음' if vs else '없음'}, EventValidation: {'있음' if ev else '없음'}")

        # year control
        year_control = None
        for sel in selects:
            opts = sel.find_all("option")
            for opt in opts:
                if opt.get("value", "").strip() == str(season):
                    year_control = sel.get("name", "")
                    break

        print(f"  연도 컨트롤: {year_control!r}")

        if vs and year_control:
            vsg = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})
            post_data = {
                "__VIEWSTATE": vs.get("value", ""),
                "__VIEWSTATEGENERATOR": vsg.get("value", "") if vsg else "",
                "__EVENTVALIDATION": ev.get("value", "") if ev else "",
                "__EVENTTARGET": year_control,
                "__EVENTARGUMENT": "",
                year_control: str(season),
            }
            resp2 = client.post(url, data=post_data, headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": url,
            })
            print(f"  POST status: {resp2.status_code}")
            soup2 = BeautifulSoup(resp2.text, "lxml")
            table2 = soup2.find("table")
            if table2:
                rows2 = table2.find_all("tr")
                print(f"  POST 후 행 수: {len(rows2)}")
                for r in rows2[:4]:
                    d = [td.get_text(strip=True) for td in r.find_all(["td", "th"])]
                    print(f"  {d}")


def test_koreabaseball_mobile(season: int = 2025):
    """모바일 사이트 TOP 투수"""
    print(f"\n=== m.koreabaseball.com/Kbo/Top/Pitcher.aspx?seasonId={season} ===")
    url = f"https://m.koreabaseball.com/Kbo/Top/Pitcher.aspx?seasonId={season}"
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        resp = client.get(url, headers=HEADERS)
        print(f"GET status: {resp.status_code}, size: {len(resp.content)}")
        try:
            text = resp.content.decode("utf-8", errors="replace")
        except Exception:
            text = resp.text
        soup = BeautifulSoup(text, "lxml")
        # 리스트 아이템 확인
        items = soup.find_all("li", {"class": lambda c: c and "pitcher" in c.lower()}) or \
                soup.find_all("div", {"class": lambda c: c and "item" in c.lower()})
        print(f"  아이템 수: {len(items)}")
        if items:
            print(f"  첫 번째: {items[0].get_text(strip=True)[:100]}")
        table = soup.find("table")
        if table:
            rows = table.find_all("tr")
            print(f"  테이블 행 수: {len(rows)}")
            for r in rows[:3]:
                print(f"  {[td.get_text(strip=True) for td in r.find_all(['td','th'])]}")


if __name__ == "__main__":
    print("KBO 투수 통계 소스 진단 시작...\n")
    test_koreabaseball_asp(season=2025)
    test_eng_koreabaseball(season=2025)
    test_koreabaseball_mobile(season=2025)
    print("\n\n진단 완료.")
