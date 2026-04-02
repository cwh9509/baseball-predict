export interface KeyFactor {
  factor: string
  detail: string
  impact: "positive" | "negative" | "neutral"
}

export interface Explanation {
  summary: string
  key_factors: KeyFactor[]
  confidence_note: string
}

export interface LineupEntry {
  order: number
  name: string
  position: string
}

export interface Lineup {
  home_starter: string | null
  away_starter: string | null
  home_lineup: LineupEntry[]
  away_lineup: LineupEntry[]
  lineup_locked: boolean
}

export interface PredictionDetail {
  game_id: number
  game_date?: string
  home_team?: { id: number; name: string; short_name: string }
  away_team?: { id: number; name: string; short_name: string }
  model_version: string
  predicted_at: string
  home_win_prob: number
  away_win_prob: number
  predicted_winner: { id: number; name: string }
  confidence_tier: "high" | "medium" | "low"
  feature_snapshot: Record<string, unknown>
  predicted_home_score?: number
  predicted_away_score?: number
  explanation?: Explanation
  lineup?: Lineup
  home_recent_results?: boolean[]
  away_recent_results?: boolean[]
}
