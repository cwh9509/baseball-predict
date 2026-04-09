"use client"
import { useState } from "react"
import Image from "next/image"
import { getTeamLogoUrl } from "@/lib/utils"

interface Props {
  shortName: string
  league?: string
  size?: number   // px
  className?: string
}

// KBO 팀별 공식 색상 (배경색, 텍스트색)
const KBO_TEAM_COLORS: Record<string, { bg: string; text: string }> = {
  KIA:  { bg: "#CE1141", text: "#fff" },
  삼성:  { bg: "#074CA1", text: "#fff" },
  LG:   { bg: "#C30452", text: "#fff" },
  두산:  { bg: "#131230", text: "#fff" },
  한화:  { bg: "#E85D04", text: "#fff" },
  SSG:  { bg: "#CE2029", text: "#fff" },
  롯데:  { bg: "#002561", text: "#fff" },
  키움:  { bg: "#1A1A1A", text: "#E8001C" },
  NC:   { bg: "#315288", text: "#C4A44A" },
  KT:   { bg: "#231F20", text: "#fff" },
}

// MLB 팀별 공식 색상 (로고 로드 실패 시 폴백)
const MLB_TEAM_COLORS: Record<string, { bg: string; text: string }> = {
  NYY: { bg: "#003087", text: "#fff" }, BOS: { bg: "#BD3039", text: "#fff" },
  LAD: { bg: "#005A9C", text: "#fff" }, CHC: { bg: "#0E3386", text: "#CC3433" },
  SF:  { bg: "#FD5A1E", text: "#27251F" }, HOU: { bg: "#002D62", text: "#EB6E1F" },
  ATL: { bg: "#CE1141", text: "#13274F" }, NYM: { bg: "#002D72", text: "#FF5910" },
  PHI: { bg: "#E81828", text: "#002D72" }, SD:  { bg: "#2F241D", text: "#FFC425" },
  TEX: { bg: "#003278", text: "#C0111F" }, MIN: { bg: "#002B5C", text: "#D31145" },
  CLE: { bg: "#00385D", text: "#E31937" }, SEA: { bg: "#0C2C56", text: "#005C5C" },
  TOR: { bg: "#134A8E", text: "#E8291C" }, BAL: { bg: "#DF4601", text: "#000000" },
  TB:  { bg: "#092C5C", text: "#8FBCE6" }, MIA: { bg: "#00A3E0", text: "#EF3340" },
  DET: { bg: "#0C2340", text: "#FA4616" }, KC:  { bg: "#004687", text: "#C09A5B" },
  CWS: { bg: "#27251F", text: "#C4CED4" }, MIL: { bg: "#FFC52F", text: "#12284B" },
  CIN: { bg: "#C6011F", text: "#000000" }, PIT: { bg: "#FDB827", text: "#27251F" },
  STL: { bg: "#C41E3A", text: "#0C2340" }, CHC_: { bg: "#0E3386", text: "#CC3433" },
  COL: { bg: "#33006F", text: "#C4CED4" }, ARI: { bg: "#A71930", text: "#E3D4AD" },
  LAA: { bg: "#BA0021", text: "#003263" }, OAK: { bg: "#003831", text: "#EFB21E" },
  WSH: { bg: "#AB0003", text: "#14225A" },
}

function TeamBadge({ shortName, league, size, className }: Props) {
  const colors =
    league === "MLB"
      ? MLB_TEAM_COLORS[shortName] ?? { bg: "#374151", text: "#fff" }
      : KBO_TEAM_COLORS[shortName] ?? { bg: "#374151", text: "#fff" }

  const display = shortName.length > 3 ? shortName.slice(0, 2) : shortName

  return (
    <span
      className={`inline-flex items-center justify-center rounded-full font-bold shrink-0 ${className}`}
      style={{
        width: size,
        height: size,
        fontSize: size! * 0.32,
        backgroundColor: colors.bg,
        color: colors.text,
      }}
    >
      {display}
    </span>
  )
}

export default function TeamLogo({ shortName, league, size = 32, className = "" }: Props) {
  const [failed, setFailed] = useState(false)
  const url = getTeamLogoUrl(shortName, league)

  if (!url || failed) {
    return <TeamBadge shortName={shortName} league={league} size={size} className={className} />
  }

  return (
    <Image
      src={url}
      alt={shortName}
      width={size}
      height={size}
      className={`object-contain shrink-0 ${className}`}
      onError={() => setFailed(true)}
      unoptimized
    />
  )
}
