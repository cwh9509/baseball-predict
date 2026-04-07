"use client"
import { useState } from "react"
import { getTeamLogoUrl } from "@/lib/utils"

interface Props {
  shortName: string
  league?: string
  size?: number   // px
  className?: string
}

export default function TeamLogo({ shortName, league, size = 32, className = "" }: Props) {
  const [failed, setFailed] = useState(false)
  const url = getTeamLogoUrl(shortName, league)

  if (!url || failed) {
    return (
      <span
        className={`inline-flex items-center justify-center rounded-full bg-gray-100 text-gray-600 font-bold text-xs shrink-0 ${className}`}
        style={{ width: size, height: size, fontSize: size * 0.35 }}
      >
        {shortName.slice(0, 3)}
      </span>
    )
  }

  return (
    <img
      src={url}
      alt={shortName}
      width={size}
      height={size}
      className={`object-contain shrink-0 ${className}`}
      onError={() => setFailed(true)}
    />
  )
}
