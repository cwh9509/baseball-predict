"use client"
import { useRouter } from "next/navigation"
import { cn } from "@/lib/utils"

interface Props {
  currentLeague: string
  currentDate: string
}

const LEAGUES = [
  { id: "KBO", label: "🇰🇷 KBO" },
  { id: "MLB", label: "🇺🇸 MLB" },
]

export default function LeagueTabs({ currentLeague, currentDate }: Props) {
  const router = useRouter()

  return (
    <div className="flex gap-1 mb-5 border-b border-gray-200">
      {LEAGUES.map((l) => (
        <button
          key={l.id}
          onClick={() => router.push(`/games?league=${l.id}&date=${currentDate}`)}
          className={cn(
            "px-5 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
            currentLeague === l.id
              ? "border-blue-500 text-blue-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          )}
        >
          {l.label}
        </button>
      ))}
    </div>
  )
}
