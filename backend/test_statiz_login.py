"""
statiz.co.kr login test
"""
import sys
import httpx
from bs4 import BeautifulSoup

USERNAME = sys.argv[1] if len(sys.argv) > 1 else ""
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else ""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

def p(s):
    print(s.encode("utf-8", errors="replace").decode("utf-8"))

def diagnose():
    with httpx.Client(timeout=20, follow_redirects=True, headers=HEADERS) as client:

        # 1. 로그인 페이지
        p("=== 1. Login page ===")
        login_url = "https://statiz.co.kr/member/?m=login"
        r = client.get(login_url)
        p(f"  status: {r.status_code}, url: {r.url}")
        soup = BeautifulSoup(r.text, "lxml")

        form = soup.find("form")
        if form:
            p(f"  form action: {form.get('action')}, method: {form.get('method')}")
            for inp in form.find_all("input"):
                p(f"    input name={inp.get('name')!r} type={inp.get('type')!r} value={inp.get('value','')!r}")
        else:
            p("  No form found")
            p(f"  body preview: {soup.get_text()[:300]}")
            return

        # 2. 로그인 POST
        p("\n=== 2. Login POST ===")
        action = form.get("action") or login_url
        if action.startswith("/"):
            action = "https://statiz.co.kr" + action

        hidden = {i["name"]: i.get("value","") for i in form.find_all("input", {"type":"hidden"}) if i.get("name")}
        p(f"  hidden fields: {hidden}")

        # 필드명 후보들 조합
        id_field = None
        pw_field = None
        for inp in form.find_all("input"):
            name = inp.get("name","")
            typ  = inp.get("type","")
            if typ in ("email","text") or "id" in name.lower() or "user" in name.lower() or "email" in name.lower():
                id_field = name
            if typ == "password" or "pass" in name.lower() or "pw" in name.lower():
                pw_field = name

        p(f"  id_field={id_field!r}, pw_field={pw_field!r}")

        payload = {**hidden}
        if id_field:
            payload[id_field] = USERNAME
        if pw_field:
            payload[pw_field] = PASSWORD
        # fallback 필드명도 추가
        payload.setdefault("mb_id", USERNAME)
        payload.setdefault("mb_password", PASSWORD)

        rp = client.post(action, data=payload, headers={**HEADERS, "Referer": login_url})
        p(f"  POST {action} -> {rp.status_code}, url={rp.url}")

        sp = BeautifulSoup(rp.text, "lxml")
        has_logout = bool(sp.find("a", href=lambda h: h and "logout" in (h or "").lower()))
        p(f"  has logout link: {has_logout}")

        if not has_logout:
            err = sp.find(class_=lambda c: c and "error" in (c or "").lower())
            if err:
                p(f"  error msg: {err.get_text(strip=True)[:200]}")
            p(f"  page text preview: {sp.get_text()[:300]}")
            p("  Login FAILED")
            return

        p("  Login SUCCESS")

        # 3. 투수 통계 페이지
        p("\n=== 3. Pitcher stats pages ===")
        stat_urls = [
            "https://statiz.co.kr/stat.php?opt=0&sopt=0&year=2025&pos=1&ipp=100&page=1",
            "https://statiz.co.kr/stat.php?opt=0&year=2025",
            "https://statiz.co.kr/stat.php?opt=0&sopt=0&year=2025",
            "https://statiz.co.kr/record/pitcher/?year=2025",
        ]
        for url in stat_urls:
            rs = client.get(url)
            p(f"  {url}")
            p(f"    status: {rs.status_code}")
            if rs.status_code == 200:
                ss = BeautifulSoup(rs.text, "lxml")
                table = ss.find("table")
                if table:
                    rows = table.find_all("tr")
                    p(f"    table rows: {len(rows)}")
                    if rows:
                        h = [c.get_text(strip=True) for c in rows[0].find_all(["th","td"])]
                        p(f"    headers: {h}")
                    if len(rows) > 1:
                        d = [c.get_text(strip=True) for c in rows[1].find_all(["th","td"])]
                        p(f"    row1: {d}")
                else:
                    p("    no table — links with 'stat':")
                    for a in ss.find_all("a", href=lambda h: h and "stat" in (h or "")):
                        p(f"      {a.get('href')}")

if __name__ == "__main__":
    diagnose()
