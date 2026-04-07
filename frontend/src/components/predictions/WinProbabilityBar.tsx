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
  const awayPercent = 100 - homePercent

  const homeColor =
    homeProb >= 0.60 ? "bg-blue-500" :
    homeProb >= 0.50 ? "bg-blue-400" : "bg-gray-300"
  const awayColor =
    awayProb >= 0.60 ? "bg-red-500" :
    awayProb >= 0.50 ? "bg-red-400" : "bg-gray-300"

  return (
    <div className="w-full">
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span className="text-blue-600 font-medium">{homeTeam}</span>
        <span className="text-red-500 font-medium">{awayTeam}</span>
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
          {awayPercent >= 20 && `${awayPercent}%`}
        </div>
      </div>
      <div className="flex justify-between text-sm font-semibold mt-1">
        <span className={homeProb >= 0.5 ? "text-blue-600" : "text-gray-400"}>
          {formatProbability(homeProb)}
        </span>
        <span className={awayProb >= 0.5 ? "text-red-500" : "text-gray-400"}>
          {formatProbability(awayProb)}
        </span>
      </div>
    </div>
  )
}
