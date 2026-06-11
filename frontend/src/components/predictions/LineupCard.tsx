import type { Lineup } from "@/types/prediction"

interface Props {
  lineup: Lineup
  homeTeamName: string
  awayTeamName: string
}

const POSITION_KO: Record<string, string> = {
  P: "투", C: "포", "1B": "1루", "2B": "2루", "3B": "3루",
  SS: "유", LF: "좌", CF: "중", RF: "우", DH: "지", PH: "대타",
}

function posLabel(pos: string) {
  return POSITION_KO[pos?.toUpperCase()] ?? pos ?? "-"
}

export default function LineupCard({ lineup, homeTeamName, awayTeamName }: Props) {
  const hasLineup = lineup.home_lineup.length > 0 || lineup.away_lineup.length > 0
  const hasFullLineup = lineup.home_lineup.length >= 9 && lineup.away_lineup.length >= 9
  const hasStarters = Boolean(lineup.home_starter || lineup.away_starter)

  return (
    <div className="bg-white rounded-xl border shadow-sm p-4 mt-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-700 text-sm">선발 라인업</h3>
        {lineup.lineup_locked || hasFullLineup ? (
          <span className="text-xs text-green-600 bg-green-50 px-2 py-0.5 rounded-full border border-green-200">확정</span>
        ) : hasStarters ? (
          <span className="text-xs text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200">선발 확정</span>
        ) : (
          <span className="text-xs text-gray-400 bg-gray-50 px-2 py-0.5 rounded-full border">미발표</span>
        )}
      </div>

      {/* 선발투수 — 원정 왼쪽, 홈 오른쪽 */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div className="bg-red-50 rounded-lg p-3 text-center">
          <p className="text-xs text-gray-400 mb-1">원정 선발</p>
          <p className="font-semibold text-gray-800 text-sm">{lineup.away_starter ?? "미정"}</p>
          <p className="text-xs text-red-600 mt-0.5">{awayTeamName}</p>
        </div>
        <div className="bg-blue-50 rounded-lg p-3 text-center">
          <p className="text-xs text-gray-400 mb-1">홈 선발</p>
          <p className="font-semibold text-gray-800 text-sm">{lineup.home_starter ?? "미정"}</p>
          <p className="text-xs text-blue-600 mt-0.5">{homeTeamName}</p>
        </div>
      </div>

      {/* 타순 — 원정 왼쪽, 홈 오른쪽 */}
      {hasLineup && (
        <div className="grid grid-cols-2 gap-3">
          {/* 원정 타순 */}
          <div>
            <p className="text-xs font-medium text-red-600 mb-1.5">{awayTeamName} 타순</p>
            <div className="space-y-1">
              {lineup.away_lineup.map((p) => (
                <div key={p.order} className="flex items-center gap-2 text-xs">
                  <span className="w-4 text-gray-400 text-right shrink-0">{p.order}</span>
                  <span className="w-6 text-center bg-gray-100 rounded text-gray-500 shrink-0">{posLabel(p.position)}</span>
                  <span className="text-gray-800 truncate">{p.name}</span>
                </div>
              ))}
            </div>
          </div>
          {/* 홈 타순 */}
          <div>
            <p className="text-xs font-medium text-blue-600 mb-1.5">{homeTeamName} 타순</p>
            <div className="space-y-1">
              {lineup.home_lineup.map((p) => (
                <div key={p.order} className="flex items-center gap-2 text-xs">
                  <span className="w-4 text-gray-400 text-right shrink-0">{p.order}</span>
                  <span className="w-6 text-center bg-gray-100 rounded text-gray-500 shrink-0">{posLabel(p.position)}</span>
                  <span className="text-gray-800 truncate">{p.name}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {!hasLineup && hasStarters && (
        <p className="text-xs text-gray-400 text-center py-2">
          타순은 경기 시작 1~2시간 전 자동으로 업데이트됩니다
        </p>
      )}
      {!hasLineup && !hasStarters && (
        <p className="text-xs text-gray-400 text-center py-2">
          경기 시작 1~2시간 전 자동으로 업데이트됩니다
        </p>
      )}
    </div>
  )
}
