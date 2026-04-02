"""
오늘 라인업 수동 입력 스크립트
사용: python manual_lineup.py --url https://baseball-predict-production.up.railway.app

DB game_id 기준 (collect 재실행 후 home/away 교정된 상태):
  61: LG(홈) vs KIA(원정)
  65: 한화(홈) vs KT(원정)
  64: NC(홈) vs 롯데(원정)
  63: 삼성(홈) vs 두산(원정)
  62: SSG(홈) vs 키움(원정)
"""
import argparse
import httpx

# collect?force=true 실행 후 home/away가 교정된 상태 기준
# home_starter = 홈팀 선발, away_starter = 원정팀 선발
GAMES = [
    # game 61: LG(홈) vs KIA(원정)
    {
        "game_id": 61,
        "home_starter": "웰스",
        "away_starter": "김태형",
        "home_lineup": [
            {"order": 1, "name": "홍창기", "position": ""},
            {"order": 2, "name": "신민재", "position": ""},
            {"order": 3, "name": "오스틴", "position": ""},
            {"order": 4, "name": "문보경", "position": ""},
            {"order": 5, "name": "박동원", "position": ""},
            {"order": 6, "name": "문성주", "position": ""},
            {"order": 7, "name": "천성호", "position": ""},
            {"order": 8, "name": "구본혁", "position": ""},
            {"order": 9, "name": "박해민", "position": ""},
        ],
        "away_lineup": [
            {"order": 1, "name": "김호령", "position": ""},
            {"order": 2, "name": "카스트로", "position": ""},
            {"order": 3, "name": "김도영", "position": ""},
            {"order": 4, "name": "나성범", "position": ""},
            {"order": 5, "name": "김선빈", "position": ""},
            {"order": 6, "name": "오선우", "position": ""},
            {"order": 7, "name": "데일", "position": ""},
            {"order": 8, "name": "김태군", "position": ""},
            {"order": 9, "name": "박민", "position": ""},
        ],
    },
    # game 65: 한화(홈) vs KT(원정)
    {
        "game_id": 65,
        "home_starter": "문동주",
        "away_starter": "오원석",
        "home_lineup": [
            {"order": 1, "name": "오재원", "position": ""},
            {"order": 2, "name": "페라자", "position": ""},
            {"order": 3, "name": "문현빈", "position": ""},
            {"order": 4, "name": "노시환", "position": ""},
            {"order": 5, "name": "강백호", "position": ""},
            {"order": 6, "name": "채은성", "position": ""},
            {"order": 7, "name": "하주석", "position": ""},
            {"order": 8, "name": "허인서", "position": ""},
            {"order": 9, "name": "심우준", "position": ""},
        ],
        "away_lineup": [
            {"order": 1, "name": "최원준", "position": ""},
            {"order": 2, "name": "김현수", "position": ""},
            {"order": 3, "name": "안현민", "position": ""},
            {"order": 4, "name": "힐리어드", "position": ""},
            {"order": 5, "name": "장성우", "position": ""},
            {"order": 6, "name": "오윤석", "position": ""},
            {"order": 7, "name": "류현인", "position": ""},
            {"order": 8, "name": "김상수", "position": ""},
            {"order": 9, "name": "이강민", "position": ""},
        ],
    },
    # game 64: NC(홈) vs 롯데(원정)
    {
        "game_id": 64,
        "home_starter": "버하겐",
        "away_starter": "김진욱",
        "home_lineup": [
            {"order": 1, "name": "김주원", "position": ""},
            {"order": 2, "name": "박민우", "position": ""},
            {"order": 3, "name": "데이비스", "position": ""},
            {"order": 4, "name": "박건우", "position": ""},
            {"order": 5, "name": "김휘집", "position": ""},
            {"order": 6, "name": "김형준", "position": ""},
            {"order": 7, "name": "이우성", "position": ""},
            {"order": 8, "name": "천재환", "position": ""},
            {"order": 9, "name": "최정원", "position": ""},
        ],
        "away_lineup": [
            {"order": 1, "name": "레이예스", "position": ""},
            {"order": 2, "name": "노진혁", "position": ""},
            {"order": 3, "name": "윤동희", "position": ""},
            {"order": 4, "name": "전준우", "position": ""},
            {"order": 5, "name": "손호영", "position": ""},
            {"order": 6, "name": "한동희", "position": ""},
            {"order": 7, "name": "유강남", "position": ""},
            {"order": 8, "name": "한태양", "position": ""},
            {"order": 9, "name": "전민재", "position": ""},
        ],
    },
    # game 63: 삼성(홈) vs 두산(원정)
    {
        "game_id": 63,
        "home_starter": "이승현",
        "away_starter": "최민석",
        "home_lineup": [
            {"order": 1, "name": "김지찬", "position": ""},
            {"order": 2, "name": "김성윤", "position": ""},
            {"order": 3, "name": "구자욱", "position": ""},
            {"order": 4, "name": "디아즈", "position": ""},
            {"order": 5, "name": "최형우", "position": ""},
            {"order": 6, "name": "류지혁", "position": ""},
            {"order": 7, "name": "김영웅", "position": ""},
            {"order": 8, "name": "이재현", "position": ""},
            {"order": 9, "name": "박세혁", "position": ""},
        ],
        "away_lineup": [
            {"order": 1, "name": "박찬호", "position": ""},
            {"order": 2, "name": "정수빈", "position": ""},
            {"order": 3, "name": "양석환", "position": ""},
            {"order": 4, "name": "양의지", "position": ""},
            {"order": 5, "name": "카메론", "position": ""},
            {"order": 6, "name": "안재석", "position": ""},
            {"order": 7, "name": "강승호", "position": ""},
            {"order": 8, "name": "이유찬", "position": ""},
            {"order": 9, "name": "박지훈", "position": ""},
        ],
    },
    # game 62: SSG(홈) vs 키움(원정)
    {
        "game_id": 62,
        "home_starter": "최민준",
        "away_starter": "정현우",
        "home_lineup": [
            {"order": 1, "name": "박성한", "position": ""},
            {"order": 2, "name": "에레디아", "position": ""},
            {"order": 3, "name": "최정", "position": ""},
            {"order": 4, "name": "김재환", "position": ""},
            {"order": 5, "name": "고명준", "position": ""},
            {"order": 6, "name": "한유섬", "position": ""},
            {"order": 7, "name": "안상현", "position": ""},
            {"order": 8, "name": "최지훈", "position": ""},
            {"order": 9, "name": "이지영", "position": ""},
        ],
        "away_lineup": [
            {"order": 1, "name": "브룩스", "position": ""},
            {"order": 2, "name": "이주형", "position": ""},
            {"order": 3, "name": "안치홍", "position": ""},
            {"order": 4, "name": "최주환", "position": ""},
            {"order": 5, "name": "김건희", "position": ""},
            {"order": 6, "name": "박찬혁", "position": ""},
            {"order": 7, "name": "어준서", "position": ""},
            {"order": 8, "name": "박한결", "position": ""},
            {"order": 9, "name": "최재형", "position": ""},
        ],
    },
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://baseball-predict-production.up.railway.app")
    args = parser.parse_args()

    endpoint = f"{args.url.rstrip('/')}/api/v1/admin/lineup/manual"
    print(f"전송: {endpoint}")

    resp = httpx.post(endpoint, json={"games": GAMES}, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    print("\n결과:")
    for r in data["results"]:
        print(f"  game_id={r['game_id']}: {r.get('away_starter','?')} vs {r.get('home_starter','?')} → {r['status']}")


if __name__ == "__main__":
    main()
