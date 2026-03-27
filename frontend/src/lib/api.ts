/**
 * 타입 안전 API 클라이언트
 * 서버 컴포넌트: NEXT_PUBLIC_API_URL → 백엔드 직접 호출
 * 클라이언트 컴포넌트: 동일 URL 사용 (CORS 방지용 Next.js API 라우트로 프록시 가능)
 */
import type { GamesListResponse } from "@/types/game"
import type { PredictionDetail } from "@/types/prediction"

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/api/v1${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!res.ok) {
    throw new Error(`API 오류 ${res.status}: ${path}`)
  }
  return res.json()
}

export async function getGamesToday(
  league: string,
  date?: string
): Promise<GamesListResponse> {
  const params = new URLSearchParams({ league })
  if (date) params.set("date", date)
  return apiFetch<GamesListResponse>(`/games/today?${params}`, {
    next: { revalidate: 300 },  // 5분 캐시 (서버 컴포넌트)
  })
}

export async function getPrediction(gameId: number): Promise<PredictionDetail> {
  return apiFetch<PredictionDetail>(`/predict/${gameId}`, {
    next: { revalidate: 1800 },
  })
}

export async function getTeamStats(
  teamId: number,
  season?: number,
  lastN?: number
): Promise<unknown> {
  const params = new URLSearchParams()
  if (season) params.set("season", String(season))
  if (lastN) params.set("last_n", String(lastN))
  return apiFetch(`/team/${teamId}/stats?${params}`, {
    next: { revalidate: 3600 },
  })
}

export async function getHistory(
  league: string,
  params: {
    from_date?: string
    to_date?: string
    page?: number
    per_page?: number
  } = {}
): Promise<unknown> {
  const p = new URLSearchParams({ league, ...Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)])
  )})
  return apiFetch(`/history?${p}`)
}
