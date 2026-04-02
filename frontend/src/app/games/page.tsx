import { Suspense } from "react"
import { getGamesToday } from "@/lib/api"
import GameCard from "@/components/games/GameCard"
import DateNavigator from "@/components/games/DateNavigator"
import { formatDate } from "@/lib/utils"

// 5분마다 서버에서 재검증
export const revalidate = 300

interface PageProps {
  searchParams: { league?: string; date?: string }
}

export default async function GamesPage({ searchParams }: PageProps) {
  const league = "KBO"
  const date = searchParams.date
  const today = date ?? new Date().toISOString().slice(0, 10)

  let data
  try {
    data = await getGamesToday(league, today)
  } catch {
    data = null
  }

  return (
    <div>
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">오늘의 경기</h1>
          <p className="text-gray-500 text-sm mt-1">{formatDate(today)}</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {/* 날짜 네비게이터 */}
          <DateNavigator currentDate={today} league={league} />
        </div>
      </div>

      {/* 경기 목록 */}
      {!data || data.games.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <div className="text-4xl mb-3">⚾</div>
          <p>오늘 예정된 경기가 없습니다.</p>
          <p className="text-sm mt-1">리그 시즌 중에 다시 확인하세요.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.games.map((game) => (
            <GameCard key={game.id} game={game} currentDate={today} league={league} />
          ))}
        </div>
      )}
    </div>
  )
}
