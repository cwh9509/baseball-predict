import { getPrediction } from "@/lib/api"
import WinProbabilityBar from "@/components/predictions/WinProbabilityBar"
import LineupCard from "@/components/predictions/LineupCard"
import GameStatsCard from "@/components/predictions/GameStatsCard"
import TeamLogo from "@/components/common/TeamLogo"
import { cn, CONFIDENCE_COLORS, CONFIDENCE_LABELS, formatDate, formatProbability, getTeamDisplayName, getTeamFullKoName } from "@/lib/utils"

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
  const league = backLeague
  const homeShort = getTeamDisplayName(prediction.home_team?.short_name ?? "", prediction.home_team?.name ?? "홈팀", league)
  const awayShort = getTeamDisplayName(prediction.away_team?.short_name ?? "", prediction.away_team?.name ?? "원정팀", league)
  const homeFull = getTeamFullKoName(prediction.home_team?.short_name ?? "", prediction.home_team?.name ?? "홈팀", league)
  const awayFull = getTeamFullKoName(prediction.away_team?.short_name ?? "", prediction.away_team?.name ?? "원정팀", league)
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
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold text-gray-900">경기 예측</h1>
                {!prediction.lineup && (
                  <span className="px-2 py-0.5 rounded-full border text-xs text-amber-600 border-amber-300 bg-amber-50">
                    라인업 확정 전
                  </span>
                )}
              </div>
              <span className={cn(
                "px-3 py-1 rounded-full border text-sm font-medium",
                CONFIDENCE_COLORS[tier]
              )}>
                신뢰도 {CONFIDENCE_LABELS[tier]}
              </span>
            </div>

            {/* 팀 매치업 — 원정(왼쪽) vs 홈(오른쪽) */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex flex-col items-center gap-1">
                <div className="text-xs text-red-400 font-medium">원정</div>
                <TeamLogo shortName={prediction.away_team?.short_name ?? ""} league={league} size={48} />
                <div className="font-bold text-base">{awayShort}</div>
              </div>
              <div className="text-gray-300 text-lg font-light">vs</div>
              <div className="flex flex-col items-center gap-1">
                <div className="text-xs text-blue-500 font-medium">홈</div>
                <TeamLogo shortName={prediction.home_team?.short_name ?? ""} league={league} size={48} />
                <div className="font-bold text-base">{homeShort}</div>
              </div>
            </div>

            {/* 승리 확률 바 */}
            <WinProbabilityBar
              homeProb={prediction.home_win_prob}
              homeTeam={homeShort}
              awayTeam={awayShort}
            />

            {/* 예상 스코어 (원정 – 홈) */}
            {prediction.predicted_home_score != null && prediction.predicted_away_score != null && (
              <div className="mt-3 text-center">
                <p className="text-gray-400 text-xs mb-1">예상 스코어</p>
                <div className="flex items-center justify-center gap-3 text-2xl font-bold text-gray-800">
                  <div className="text-center">
                    <div>{prediction.predicted_away_score}</div>
                    <div className="text-xs text-red-400 font-normal">원정</div>
                  </div>
                  <span className="text-gray-400 text-lg">–</span>
                  <div className="text-center">
                    <div>{prediction.predicted_home_score}</div>
                    <div className="text-xs text-blue-500 font-normal">홈</div>
                  </div>
                </div>
              </div>
            )}

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
              homeTeamName={homeFull}
              awayTeamName={awayFull}
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
          homeTeamName={homeFull}
          awayTeamName={awayFull}
          league={league}
        />
      </div>
    </div>
  )
}
