"""
Claude API를 통한 LLM 해설 생성
지연 생성 전략 — 사용자가 경기 상세 페이지 조회 시에만 호출

비용 절감:
  - Redis 24시간 캐시
  - LLM_EXPLANATIONS_ENABLED=false 시 건너뜀
"""
import json
import logging
from datetime import datetime, timezone

import anthropic

from app.config import settings
from app.core.redis_client import cache_get, cache_set
from app.llm.prompt_templates import build_prompt

logger = logging.getLogger(__name__)

LLM_MODEL = "claude-sonnet-4-6"


class Explainer:

    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate(
        self,
        prediction_id: int,
        home_team: str,
        away_team: str,
        game_date: str,
        home_win_prob: float,
        predicted_winner: str,
        confidence_tier: str,
        snapshot: dict,
    ) -> dict | None:
        """
        LLM 해설 생성 (Redis 캐시 → Claude API 순서)
        Returns: {"summary": ..., "key_factors": [...], "confidence_note": ...} 또는 None
        """
        if not settings.llm_explanations_enabled:
            logger.debug("LLM 해설 비활성화 (LLM_EXPLANATIONS_ENABLED=false)")
            return None

        if not settings.anthropic_api_key:
            logger.warning("ANTHROPIC_API_KEY 미설정 — LLM 해설 건너뜀")
            return None

        # Redis 캐시 확인
        cache_key = f"prediction:explain:{prediction_id}"
        cached = await cache_get(cache_key)
        if cached:
            return cached

        # 프롬프트 생성
        prompt = build_prompt(
            home_team=home_team,
            away_team=away_team,
            game_date=game_date,
            home_win_prob=home_win_prob,
            predicted_winner=predicted_winner,
            confidence_tier=confidence_tier,
            snapshot=snapshot,
        )

        # Claude API 호출
        try:
            message = await self.client.messages.create(
                model=LLM_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = message.content[0].text.strip()

            # 마크다운 코드블록 제거 (```json ... ``` 또는 ``` ... ```)
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```", 2)[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            # JSON 파싱
            explanation = json.loads(raw_text)
            # 필수 키 검증
            if not all(k in explanation for k in ["summary", "key_factors", "confidence_note"]):
                raise ValueError("LLM 응답에 필수 키 누락")

            # Redis 캐시에 저장 (24시간)
            await cache_set(cache_key, explanation, ttl=86400)
            return explanation

        except json.JSONDecodeError as e:
            logger.error(f"LLM 응답 JSON 파싱 실패 (prediction_id={prediction_id}): {e}")
            return None
        except anthropic.RateLimitError:
            logger.warning("Claude API 속도 제한 — 나중에 재시도")
            return None
        except anthropic.APIError as e:
            logger.error(f"Claude API 오류: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM 해설 생성 실패: {e}", exc_info=True)
            return None
