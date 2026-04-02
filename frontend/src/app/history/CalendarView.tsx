"use client"
import { useState, useEffect } from "react"
import { getHistoryCalendar } from "@/lib/api"
import { cn } from "@/lib/utils"

interface DayStat { total: number; correct: number }

function dayColor(stat: DayStat | undefined): string {
  if (!stat || stat.total === 0) return "bg-gray-50 text-gray-300"
  const pct = stat.correct / stat.total
  if (pct >= 0.6) return "bg-green-100 text-green-800 border-green-200"
  if (pct >= 0.4) return "bg-yellow-100 text-yellow-800 border-yellow-200"
  return "bg-red-100 text-red-800 border-red-200"
}

const WEEK_DAYS = ["일", "월", "화", "수", "목", "금", "토"]
const MONTHS = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"]

export default function CalendarView({ league }: { league: string }) {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [days, setDays] = useState<Record<string, DayStat>>({})
  const [loading, setLoading] = useState(true)
  const [totalStats, setTotalStats] = useState({ total: 0, correct: 0 })

  useEffect(() => {
    setLoading(true)
    getHistoryCalendar(league, year, month)
      .then((d) => {
        setDays(d.days)
        let t = 0, c = 0
        for (const s of Object.values(d.days)) { t += s.total; c += s.correct }
        setTotalStats({ total: t, correct: c })
      })
      .finally(() => setLoading(false))
  }, [league, year, month])

  function prevMonth() {
    if (month === 1) { setYear(y => y - 1); setMonth(12) }
    else setMonth(m => m - 1)
  }
  function nextMonth() {
    if (month === 12) { setYear(y => y + 1); setMonth(1) }
    else setMonth(m => m + 1)
  }

  // Build calendar grid
  const firstDay = new Date(year, month - 1, 1).getDay()
  const daysInMonth = new Date(year, month, 0).getDate()
  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ]
  // Pad to complete last row
  while (cells.length % 7 !== 0) cells.push(null)

  const monthAccuracy = totalStats.total > 0
    ? ((totalStats.correct / totalStats.total) * 100).toFixed(1)
    : "-"

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <button onClick={prevMonth} className="px-3 py-1 rounded border hover:bg-gray-50 text-sm">← 이전</button>
        <div className="text-center">
          <div className="font-semibold text-lg">{year}년 {MONTHS[month - 1]}</div>
          {totalStats.total > 0 && (
            <div className="text-xs text-gray-400 mt-0.5">
              {totalStats.total}경기 중 {totalStats.correct}적중 ({monthAccuracy}%)
            </div>
          )}
        </div>
        <button onClick={nextMonth} className="px-3 py-1 rounded border hover:bg-gray-50 text-sm">다음 →</button>
      </div>

      {/* Legend */}
      <div className="flex gap-3 justify-end mb-3 text-xs text-gray-500">
        <span><span className="inline-block w-3 h-3 rounded-sm bg-green-100 border border-green-200 mr-1" />60%↑</span>
        <span><span className="inline-block w-3 h-3 rounded-sm bg-yellow-100 border border-yellow-200 mr-1" />40–60%</span>
        <span><span className="inline-block w-3 h-3 rounded-sm bg-red-100 border border-red-200 mr-1" />40%↓</span>
        <span><span className="inline-block w-3 h-3 rounded-sm bg-gray-50 border mr-1" />데이터 없음</span>
      </div>

      {/* Calendar */}
      {loading ? (
        <div className="text-center py-12 text-gray-400 text-sm">로딩 중...</div>
      ) : (
        <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
          {/* Day headers */}
          <div className="grid grid-cols-7 border-b">
            {WEEK_DAYS.map((d, i) => (
              <div key={d} className={cn(
                "py-2 text-center text-xs font-medium",
                i === 0 ? "text-red-400" : i === 6 ? "text-blue-400" : "text-gray-500"
              )}>{d}</div>
            ))}
          </div>
          {/* Cells */}
          <div className="grid grid-cols-7">
            {cells.map((day, idx) => {
              if (!day) return <div key={idx} className="h-12 border-b border-r border-gray-50" />
              const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`
              const stat = days[dateStr]
              const col = dayColor(stat)
              const pct = stat && stat.total > 0 ? Math.round((stat.correct / stat.total) * 100) : null
              return (
                <div
                  key={idx}
                  className={cn(
                    "h-12 border-b border-r border-gray-50 px-1.5 py-1 flex flex-col justify-between cursor-default",
                    col
                  )}
                  title={stat ? `${stat.correct}/${stat.total} 적중` : "경기 없음"}
                >
                  <span className="text-[11px] font-medium leading-none">{day}</span>
                  {pct !== null && (
                    <span className="text-[11px] font-semibold leading-none self-end">{pct}%</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
