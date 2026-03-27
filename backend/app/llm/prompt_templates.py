"""
LLM 해설 생성용 Jinja2 프롬프트 템플릿
피처 스냅샷 + 예측 확률 → 자연어 분석 코멘트
"""
from jinja2 import Template

EXPLANATION_PROMPT = Template("""
당신은 야구 전문 분석가입니다. 아래 데이터를 바탕으로 경기 예측 근거를 한국어로 설명하세요.

## 경기 정보
- 홈팀: {{ home_team }}
- 원정팀: {{ away_team }}
- 경기일: {{ game_date }}

## 예측 결과
- 홈팀 승리 확률: {{ (home_win_prob * 100)|round(1) }}%
- 원정팀 승리 확률: {{ ((1 - home_win_prob) * 100)|round(1) }}%
- 예측 승자: {{ predicted_winner }}
- 신뢰도: {{ confidence_tier_ko }}

## 주요 데이터
**팀 최근 폼**
- 홈팀 최근 10경기 승률: {{ (home_win_rate_L10 * 100)|round(1) if home_win_rate_L10 else "N/A" }}%
- 원정팀 최근 10경기 승률: {{ (away_win_rate_L10 * 100)|round(1) if away_win_rate_L10 else "N/A" }}%
- 홈팀 연속 결과: {{ home_streak_text }}
- 원정팀 연속 결과: {{ away_streak_text }}

**선발투수**
- 홈팀 선발: ERA {{ home_sp_era }}{% if home_sp_imputed %} (추정값){% endif %}
- 원정팀 선발: ERA {{ away_sp_era }}{% if away_sp_imputed %} (추정값){% endif %}

**날씨** ({{ "돔구장" if is_dome else "야외" }})
{% if not is_dome %}
- 기온: {{ temperature_c }}°C{% if is_hot %} (고온 — 공이 더 날아감){% elif is_cold %} (저온 — 투수 불리){% endif %}
- 풍속: {{ wind_speed_ms }}m/s{% if wind_favor_home %} (홈 방향 순풍){% elif wind_favor_pitcher %} (투수 유리 역풍){% endif %}
{% if is_raining %}- ⚠️ 우천 예보 있음{% endif %}
{% else %}
- 실내 구장 — 날씨 영향 없음
{% endif %}

**구장 팩터**: {{ park_factor }} (1.0 = 중립, >1.0 = 타자 유리)

## 요청 형식
다음 JSON 형식으로만 응답하세요:
{
  "summary": "1~2문장 요약",
  "key_factors": [
    {"factor": "요인명", "detail": "설명 (구체적 수치 포함)", "impact": "positive|negative|neutral"},
    {"factor": "요인명", "detail": "설명", "impact": "positive|negative|neutral"},
    {"factor": "요인명", "detail": "설명", "impact": "positive|negative|neutral"}
  ],
  "confidence_note": "신뢰도 설명 (과거 유사 신뢰도 등급의 적중률 언급)"
}

응답은 반드시 유효한 JSON만 출력하세요. 추가 설명 없이.
""")


def build_prompt(
    home_team: str,
    away_team: str,
    game_date: str,
    home_win_prob: float,
    predicted_winner: str,
    confidence_tier: str,
    snapshot: dict,
) -> str:
    """프롬프트 렌더링"""
    tier_ko = {"high": "높음", "medium": "중간", "low": "낮음"}.get(confidence_tier, "중간")

    streak = snapshot.get("home_win_streak", 0) or 0
    home_streak = f"{abs(int(streak))}연{'승' if streak > 0 else '패'}" if streak != 0 else "없음"

    streak_a = snapshot.get("away_win_streak", 0) or 0
    away_streak = f"{abs(int(streak_a))}연{'승' if streak_a > 0 else '패'}" if streak_a != 0 else "없음"

    return EXPLANATION_PROMPT.render(
        home_team=home_team,
        away_team=away_team,
        game_date=game_date,
        home_win_prob=home_win_prob,
        predicted_winner=predicted_winner,
        confidence_tier_ko=tier_ko,
        home_win_rate_L10=snapshot.get("home_win_rate_L10"),
        away_win_rate_L10=snapshot.get("away_win_rate_L10"),
        home_streak_text=home_streak,
        away_streak_text=away_streak,
        home_sp_era=f"{snapshot.get('home_sp_era_season', 'N/A'):.2f}" if snapshot.get("home_sp_era_season") else "N/A",
        away_sp_era=f"{snapshot.get('away_sp_era_season', 'N/A'):.2f}" if snapshot.get("away_sp_era_season") else "N/A",
        home_sp_imputed=bool(snapshot.get("home_sp_is_imputed")),
        away_sp_imputed=bool(snapshot.get("away_sp_is_imputed")),
        is_dome=bool(snapshot.get("is_dome_game")),
        temperature_c=snapshot.get("temperature_c", "N/A"),
        is_hot=bool(snapshot.get("is_hot")),
        is_cold=bool(snapshot.get("is_cold")),
        wind_speed_ms=snapshot.get("wind_speed_ms", "N/A"),
        wind_favor_home=bool(snapshot.get("wind_favor_home")),
        wind_favor_pitcher=bool(snapshot.get("wind_favor_pitcher")),
        is_raining=bool(snapshot.get("is_raining")),
        park_factor=snapshot.get("park_factor", 1.0),
    )
