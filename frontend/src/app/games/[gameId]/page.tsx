import { getPrediction } from "@/lib/api"
import WinProbabilityBar from "@/components/predictions/WinProbabilityBar"
import LineupCard from "@/components/predictions/LineupCard"
import GameStatsCard from "@/components/predictions/GameStatsCard"
import { cn, CONFIDENCE_COLORS, CONFIDENCE_LABELS, formatDate, formatProbability } from "@/lib/utils"

export const revalidate = 1800

interface PageProps {
  params: { gameId: string }
  searchParams: { date?: string; league?: string }
}

export async function generateMetadata({ params }: PageProps) {
  return {
    title: `경기 예측 #${params.gameId} | 야구 승리 예측`,
  }
}

export default async function GameDetailPage({ params, searchParams }: PageProps) {
  const gameId = parseInt(params.gameId)
  const backLeague = searchParams.league ?? "KBO"
  // searchParams.date 없으면 prediction의 game_date 사용 (항상 경기 날짜로 돌아감)
  const resolvedDate = searchParams.date ?? null
  const backUrl = resolvedDate
    ? `/games?league=${backLeague}&date=${resolvedDate}`
    : `/games?league=${backLeague}`

  let prediction = null

  try {
    prediction = await getPrediction(gameId)
  } catch {
    return (
      <div className="text-center py-16 text-gray-400">
        <p>예측 데이터를 불러올 수 없습니다.</p>
        <a href={backUrl} className="text-primary underline mt-2 block">← 경기 목록으로</a>
      </div>
    )
  }

  const homeWin = prediction.home_win_prob >= 0.5
  const tier = prediction.confidence_tier
  // prediction.game_date 우선 사용 (searchParams.date 없을 때도 경기 날짜로 돌아감)
  const finalBackDate = resolvedDate ?? prediction.game_date
  const finalBackUrl = finalBackDate
    ? `/games?league=${backLeague}&date=${finalBackDate}`
    : backUrl

  return (
    <div className="max-w-5xl mx-auto">
      <a href={finalBackUrl} className="text-primary text-sm hover:underline mb-4 inline-block">
        ← 경기 목록
      </a>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {/* 좌측: 경기 예측 + 라인업 */}
        <div>
          {/* 예측 결과 카드 */}
          <div className={cn(
            "bg-white rounded-xl border-2 shadow p-6 mb-4",
            tier === "high" ? "border-green-300" : tier === "medium" ? "border-yellow-200" : "border-gray-200"
          )}>
            <div className="flex items-center justify-between mb-4">
              <h1 className="text-xl font-bold text-gray-900">경기 예측</h1>
              <span className={cn(
                "px-3 py-1 rounded-full border text-sm font-medium",
                CONFIDENCE_COLORS[tier]
              )}>
                신뢰도 {CONFIDENCE_LABELS[tier]}
              </span>
            </div>

            {/* 승리 확률 바 */}
            <WinProbabilityBar
              homeProb={prediction.home_win_prob}
              homeTeam="홈팀"
              awayTeam="원정팀"
            />

            <div className="mt-4 text-center">
              <p className="text-gray-500 text-sm">예측 승자</p>
              <p className="text-lg font-bold text-primary mt-1">
                {prediction.predicted_winner.name}
              </p>
            </div>

            <div className="text-xs text-gray-400 text-center mt-2">
              모델: {prediction.model_version} · {new Date(prediction.predicted_at).toLocaleString("ko-KR")}
            </div>
          </div>

          {/* 라인업 */}
          {prediction.lineup && (
            <LineupCard
              lineup={prediction.lineup}
              homeTeamName={prediction.predicted_winner.name}
              awayTeamName="원정팀"
            />
          )}
          {!prediction.lineup && (
            <div className="bg-white rounded-xl border shadow-sm p-4 text-center text-sm text-gray-400">
              선발 라인업 미발표 — 경기 시작 1~2시간 전 자동 업데이트
            </div>
          )}
        </div>

        {/* 우측: 팀 스탯 */}
        <GameStatsCard
          prediction={prediction}
          homeTeamName={prediction.home_team?.name ?? "홈팀"}
          awayTeamName={prediction.away_team?.name ?? "원정팀"}
        />
      </div>
    </div>
  )
}
