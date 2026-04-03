"use client"
import { formatProbability } from "@/lib/utils"

interface Props {
  homeProb: number
  homeTeam: string
  awayTeam: string
  awayLeft?: boolean  // true면 원정 vs 홈 순서 (KBO 관례)
}

export default function WinProbabilityBar({ homeProb, homeTeam, awayTeam, awayLeft = false }: Props) {
  const awayProb = 1 - homeProb
  const homePercent = Math.round(homeProb * 100)
  const awayPercent = 100 - homePercent

  const homeColor =
    homeProb >= 0.60 ? "bg-green-500" :
    homeProb >= 0.50 ? "bg-yellow-400" : "bg-gray-400"
  const awayColor =
    awayProb >= 0.60 ? "bg-green-500" :
    awayProb >= 0.50 ? "bg-yellow-400" : "bg-gray-400"

  const leftTeam = awayLeft ? awayTeam : homeTeam
  const rightTeam = awayLeft ? homeTeam : awayTeam
  const leftProb = awayLeft ? awayProb : homeProb
  const rightProb = awayLeft ? homeProb : awayProb
  const leftPercent = awayLeft ? awayPercent : homePercent
  const rightPercent = awayLeft ? homePercent : awayPercent
  const leftColor = awayLeft ? awayColor : homeColor
  const rightColor = awayLeft ? homeColor : awayColor

  return (
    <div className="w-full">
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>{leftTeam}</span>
        <span>{rightTeam}</span>
      </div>
      <div className="flex rounded-full overflow-hidden h-4 bg-gray-200">
        <div
          className={`${leftColor} transition-all duration-500 flex items-center justify-center text-white text-xs font-bold`}
          style={{ width: `${leftPercent}%` }}
        >
          {leftPercent >= 20 && `${leftPercent}%`}
        </div>
        <div
          className={`${rightColor} flex-1 flex items-center justify-end pr-1 text-white text-xs font-bold`}
        >
          {rightPercent >= 20 && `${rightPercent}%`}
        </div>
      </div>
      <div className="flex justify-between text-sm font-semibold mt-1">
        <span className={leftProb >= 0.5 ? "text-green-600" : "text-gray-400"}>
          {formatProbability(leftProb)}
        </span>
        <span className={rightProb >= 0.5 ? "text-green-600" : "text-gray-400"}>
          {formatProbability(rightProb)}
        </span>
      </div>
    </div>
  )
}
