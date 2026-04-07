import Link from "next/link"
import type { Game } from "@/types/game"
import { cn, CONFIDENCE_COLORS, CONFIDENCE_LABELS, getTeamDisplayName, getTeamFullKoName } from "@/lib/utils"
import WinProbabilityBar from "@/components/predictions/WinProbabilityBar"

interface Props {
  game: Game
  currentDate?: string
  league?: string
}

const BORDER_COLOR: Record<string, string> = {
  high: "border-green-300",
  medium: "border-yellow-200",
  low: "border-gray-200",
}

export default function GameCard({ game, currentDate, league }: Props) {
  const tier = game.prediction?.confidence_tier ?? "low"
  const params = new URLSearchParams()
  if (currentDate) params.set("date", currentDate)
  if (league) params.set("league", league)
  const detailUrl = `/games/${game.id}?${params.toString()}`

  const homeShort = getTeamDisplayName(game.home_team.short_name, game.home_team.name, league)
  const awayShort = getTeamDisplayName(game.away_team.short_name, game.away_team.name, league)
  const homeFull = getTeamFullKoName(game.home_team.short_name, game.home_team.name, league)
  const awayFull = getTeamFullKoName(game.away_team.short_name, game.away_team.name, league)

  return (
    <Link href={detailUrl}>
      <div className={cn(
        "bg-white rounded-xl border-2 shadow-sm p-4 hover:shadow-md transition-shadow cursor-pointer",
        BORDER_COLOR[tier]
      )}>
        {/* 팀 매치업 — 홈(왼쪽) vs 원정(오른쪽) */}
        <div className="flex items-center justify-between mb-3">
          <div className="text-center flex-1">
            <div className="text-xs text-blue-500 font-medium mb-0.5">홈</div>
            <div className="font-bold text-lg">{homeShort}</div>
            <div className="text-xs text-gray-500 truncate max-w-24">{homeFull}</div>
          </div>
          <div className="px-3 text-gray-400 font-light text-sm">vs</div>
          <div className="text-center flex-1">
            <div className="text-xs text-red-400 font-medium mb-0.5">원정</div>
            <div className="font-bold text-lg">{awayShort}</div>
            <div className="text-xs text-gray-500 truncate max-w-24">{awayFull}</div>
          </div>
        </div>

        {/* 승률 바 (홈 왼쪽) */}
        {game.prediction && (
          <WinProbabilityBar
            homeProb={game.prediction.home_win_prob}
            homeTeam={homeShort}
            awayTeam={awayShort}
          />
        )}

        {/* 예상 스코어 (홈 – 원정) */}
        {game.prediction?.predicted_home_score != null && game.prediction?.predicted_away_score != null && (
          <div className="flex justify-center mt-2 mb-1">
            <span className="text-sm font-semibold text-gray-600 bg-gray-50 px-3 py-0.5 rounded-full border">
              예상 {game.prediction.predicted_home_score} – {game.prediction.predicted_away_score}
            </span>
          </div>
        )}

        {/* 하단 정보 */}
        <div className="flex items-center justify-between mt-3 text-xs">
          <span className="text-gray-400">
            {game.game_time
              ? `${game.game_time.slice(0, 5)} ${league === "MLB" ? "ET" : "KST"}`
              : "시간 미정"}
            {game.venue && ` · ${game.venue}`}
          </span>
          <div className="flex items-center gap-1">
            {!game.lineup_locked && game.prediction && (
              <span className="px-2 py-0.5 rounded-full border text-xs text-gray-400 border-gray-200">
                라인업 미확정
              </span>
            )}
            {game.prediction && (
              <span className={cn(
                "px-2 py-0.5 rounded-full border text-xs font-medium",
                CONFIDENCE_COLORS[tier]
              )}>
                신뢰도 {CONFIDENCE_LABELS[tier]}
              </span>
            )}
          </div>
        </div>

        {/* 날씨 */}
        {game.weather && (
          <div className="mt-2 text-xs text-gray-400 flex gap-2">
            {game.weather.temperature_c !== undefined && (
              <span>🌡 {Math.round(game.weather.temperature_c)}°C</span>
            )}
            {game.weather.weather_main && <span>{game.weather.weather_main}</span>}
            {game.weather.is_raining && <span className="text-blue-400">☔ 우천</span>}
          </div>
        )}
      </div>
    </Link>
  )
}
