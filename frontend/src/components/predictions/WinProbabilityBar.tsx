"use client"
import { formatProbability } from "@/lib/utils"

interface Props {
  homeProb: number
  homeTeam: string
  awayTeam: string
}

export default function WinProbabilityBar({ homeProb, homeTeam, awayTeam }: Props) {
  const awayProb = 1 - homeProb
  const homePercent = Math.round(homeProb * 100)

  // 색상: 홈팀 기준
  const homeColor =
    homeProb >= 0.60 ? "bg-green-500" :
    homeProb >= 0.50 ? "bg-yellow-400" : "bg-gray-400"
  const awayColor =
    awayProb >= 0.60 ? "bg-green-500" :
    awayProb >= 0.50 ? "bg-yellow-400" : "bg-gray-400"

  return (
    <div className="w-full">
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>{homeTeam}</span>
        <span>{awayTeam}</span>
      </div>
      <div className="flex rounded-full overflow-hidden h-4 bg-gray-200">
        <div
          className={`${homeColor} transition-all duration-500 flex items-center justify-center text-white text-xs font-bold`}
          style={{ width: `${homePercent}%` }}
        >
          {homePercent >= 20 && `${homePercent}%`}
        </div>
        <div
          className={`${awayColor} flex-1 flex items-center justify-end pr-1 text-white text-xs font-bold`}
        >
          {(100 - homePercent) >= 20 && `${100 - homePercent}%`}
        </div>
      </div>
      <div className="flex justify-between text-sm font-semibold mt-1">
        <span className={homeProb >= 0.5 ? "text-green-600" : "text-gray-400"}>
          {formatProbability(homeProb)}
        </span>
        <span className={awayProb >= 0.5 ? "text-green-600" : "text-gray-400"}>
          {formatProbability(awayProb)}
        </span>
      </div>
    </div>
  )
}
