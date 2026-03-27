"use client"

import { useRouter } from "next/navigation"

interface Props {
  currentDate: string  // "YYYY-MM-DD"
  league: string
}

function addDays(dateStr: string, days: number): string {
  const d = new Date(dateStr)
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

export default function DateNavigator({ currentDate, league }: Props) {
  const router = useRouter()

  const go = (date: string) => {
    router.push(`/games?league=${league}&date=${date}`)
  }

  const today = new Date().toISOString().slice(0, 10)
  const isToday = currentDate === today

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => go(addDays(currentDate, -1))}
        className="p-2 rounded-lg border border-gray-300 hover:border-primary hover:text-primary transition-colors text-gray-500"
        title="이전 날"
      >
        ‹
      </button>

      <input
        type="date"
        value={currentDate}
        onChange={(e) => e.target.value && go(e.target.value)}
        className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-primary"
      />

      <button
        onClick={() => go(addDays(currentDate, 1))}
        className="p-2 rounded-lg border border-gray-300 hover:border-primary hover:text-primary transition-colors text-gray-500"
        title="다음 날"
      >
        ›
      </button>

      {!isToday && (
        <button
          onClick={() => go(today)}
          className="px-3 py-1.5 text-sm border border-primary text-primary rounded-lg hover:bg-primary hover:text-white transition-colors"
        >
          오늘
        </button>
      )}
    </div>
  )
}
