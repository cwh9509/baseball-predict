import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "short",
  })
}

export function formatProbability(prob: number): string {
  return `${(prob * 100).toFixed(1)}%`
}

export const CONFIDENCE_LABELS: Record<string, string> = {
  high: "높음",
  medium: "중간",
  low: "낮음",
}

export const CONFIDENCE_COLORS: Record<string, string> = {
  high: "text-green-600 bg-green-50 border-green-200",
  medium: "text-yellow-600 bg-yellow-50 border-yellow-200",
  low: "text-gray-500 bg-gray-50 border-gray-200",
}

// MLB 팀 한글 이름 매핑
export const MLB_TEAM_KO: Record<string, string> = {
  // AL East
  NYY: "뉴욕 양키스", BOS: "보스턴 레드삭스", TOR: "토론토 블루제이스",
  TB: "탬파베이 레이스", BAL: "볼티모어 오리올스",
  // AL Central
  CLE: "클리블랜드 가디언스", MIN: "미네소타 트윈스", CWS: "시카고 화이트삭스",
  KC: "캔자스시티 로열스", DET: "디트로이트 타이거스",
  // AL West
  HOU: "휴스턴 애스트로스", SEA: "시애틀 매리너스", LAA: "로스앤젤레스 에인절스",
  OAK: "오클랜드 애슬레틱스", TEX: "텍사스 레인저스",
  // NL East
  ATL: "애틀랜타 브레이브스", NYM: "뉴욕 메츠", PHI: "필라델피아 필리스",
  MIA: "마이애미 말린스", WSH: "워싱턴 내셔널스",
  // NL Central
  MIL: "밀워키 브루어스", STL: "세인트루이스 카디널스", CHC: "시카고 컵스",
  CIN: "신시내티 레즈", PIT: "피츠버그 파이리츠",
  // NL West
  LAD: "LA 다저스", SF: "샌프란시스코 자이언츠", SD: "샌디에이고 파드리스",
  COL: "콜로라도 로키스", ARI: "애리조나 다이아몬드백스",
}

// MLB 팀 단축 한글 이름 (카드용)
export const MLB_TEAM_SHORT_KO: Record<string, string> = {
  NYY: "양키스", BOS: "레드삭스", TOR: "블루제이스", TB: "레이스", BAL: "오리올스",
  CLE: "가디언스", MIN: "트윈스", CWS: "화이트삭스", KC: "로열스", DET: "타이거스",
  HOU: "애스트로스", SEA: "매리너스", LAA: "에인절스", OAK: "애슬레틱스", TEX: "레인저스",
  ATL: "브레이브스", NYM: "메츠", PHI: "필리스", MIA: "말린스", WSH: "내셔널스",
  MIL: "브루어스", STL: "카디널스", CHC: "컵스", CIN: "레즈", PIT: "파이리츠",
  LAD: "다저스", SF: "자이언츠", SD: "파드리스", COL: "로키스", ARI: "다이아몬드백스",
}

export function getTeamDisplayName(shortName: string, fullName: string, league?: string): string {
  if (league === "MLB") return MLB_TEAM_SHORT_KO[shortName] ?? shortName
  return shortName
}

export function getTeamFullKoName(shortName: string, fullName: string, league?: string): string {
  if (league === "MLB") return MLB_TEAM_KO[shortName] ?? fullName
  return fullName
}

// MLB 팀 ID (statsapi) → 로고 URL용
export const MLB_TEAM_ID: Record<string, number> = {
  ARI: 109, ATL: 144, BAL: 110, BOS: 111, CHC: 112,
  CWS: 145, CIN: 113, CLE: 114, COL: 115, DET: 116,
  HOU: 117, KC: 118, LAA: 108, LAD: 119, MIA: 146,
  MIL: 158, MIN: 142, NYM: 121, NYY: 147, OAK: 133,
  PHI: 143, PIT: 134, SD: 135, SF: 137, SEA: 136,
  STL: 138, TB: 139, TEX: 140, TOR: 141, WSH: 120,
}

// KBO 팀 로고 URL (KBO 공식 CDN)
export const KBO_TEAM_LOGO: Record<string, string> = {
  KIA: "https://www.koreabaseball.com/files/AboutUs/Sponsor/ci_kia.png",
  삼성: "https://www.koreabaseball.com/files/AboutUs/Sponsor/ci_samsung.png",
  LG: "https://www.koreabaseball.com/files/AboutUs/Sponsor/ci_lg.png",
  두산: "https://www.koreabaseball.com/files/AboutUs/Sponsor/ci_doosan.png",
  KT: "https://www.koreabaseball.com/files/AboutUs/Sponsor/ci_kt.png",
  SSG: "https://www.koreabaseball.com/files/AboutUs/Sponsor/ci_ssg.png",
  롯데: "https://www.koreabaseball.com/files/AboutUs/Sponsor/ci_lotte.png",
  한화: "https://www.koreabaseball.com/files/AboutUs/Sponsor/ci_hanwha.png",
  NC: "https://www.koreabaseball.com/files/AboutUs/Sponsor/ci_nc.png",
  키움: "https://www.koreabaseball.com/files/AboutUs/Sponsor/ci_kiwoom.png",
}

export function getTeamLogoUrl(shortName: string, league?: string): string | null {
  if (league === "MLB") {
    const id = MLB_TEAM_ID[shortName]
    return id ? `https://www.mlbstatic.com/team-logos/${id}.svg` : null
  }
  // KBO: shortName이 한글(두산, LG 등)이거나 영문(KIA, SSG 등)일 수 있음
  return KBO_TEAM_LOGO[shortName] ?? null
}

export const IMPACT_ICONS: Record<string, string> = {
  positive: "▲",
  negative: "▼",
  neutral: "●",
}

export const IMPACT_COLORS: Record<string, string> = {
  positive: "text-green-600",
  negative: "text-red-500",
  neutral: "text-gray-500",
}
