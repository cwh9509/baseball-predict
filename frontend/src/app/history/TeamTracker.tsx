"use client"
import { useState, useEffect } from "react"
import { getHistoryTeams } from "@/lib/api"

interface TeamStat {
  team_id: number
  team_name: string
  team_short: string
  total: number
  correct: number
  accuracy: number
}

function AccuracyBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 60 ? "bg-green-500" : pct >= 40 ? "bg-yellow-400" : "bg-red-400"
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm font-semibold w-10 text-right">{pct}%</span>
    </div>
  )
}

export default function TeamTracker({ league }: { league: string }) {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [teams, setTeams] = useState<TeamStat[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    getHistoryTeams(league, year)
      .then((d) => setTeams(d.teams))
      .finally(() => setLoading(false))
  }, [league, year])

  if (loading) return <div className="text-center py-12 text-gray-400 text-sm">로딩 중...</div>
  if (teams.length === 0) return <div className="text-center py-12 text-gray-400 text-sm">데이터 없음</div>

  const overall = teams.reduce((acc, t) => ({ total: acc.total + t.total, correct: acc.correct + t.correct }), { total: 0, correct: 0 })

  return (
    <div>
      {/* Year selector */}
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => setYear(y => y - 1)} className="px-3 py-1 rounded border hover:bg-gray-50 text-sm">←</button>
        <span className="font-semibold">{year}년</span>
        <button onClick={() => setYear(y => y + 1)} className="px-3 py-1 rounded border hover:bg-gray-50 text-sm">→</button>
      </div>

      {/* Overall stat */}
      <div className="bg-white rounded-xl border shadow-sm p-4 mb-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-500">전체 평균 정확도</span>
          <span className="text-2xl font-bold text-green-600">
            {overall.total > 0 ? ((overall.correct / overall.total) * 100).toFixed(1) : "-"}%
          </span>
        </div>
        <div className="text-xs text-gray-400 mt-0.5">{overall.total}경기 분석</div>
      </div>

      {/* Per-team list */}
      <div className="bg-white rounded-xl border shadow-sm divide-y divide-gray-50">
        {teams.map((team, idx) => (
          <div key={team.team_id} className="px-4 py-3 flex items-center gap-3">
            <span className="text-xs text-gray-400 w-5 text-right">{idx + 1}</span>
            <span className="w-16 text-sm font-medium text-gray-800 truncate">{team.team_short || team.team_name}</span>
            <div className="flex-1">
              <AccuracyBar value={team.accuracy} />
            </div>
            <span className="text-xs text-gray-400 w-14 text-right">{team.correct}/{team.total}경기</span>
          </div>
        ))}
      </div>
    </div>
  )
}
