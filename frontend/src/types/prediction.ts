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

export interface FeatureSnapshot {
  // 선발 투수
  home_sp_era_season?: number | null
  away_sp_era_season?: number | null
  home_sp_whip_season?: number | null
  away_sp_whip_season?: number | null
  home_sp_k9_season?: number | null
  away_sp_k9_season?: number | null
  home_sp_fip?: number | null
  away_sp_fip?: number | null
  home_sp_ip_season?: number | null
  away_sp_ip_season?: number | null
  home_sp_era_L3?: number | null
  away_sp_era_L3?: number | null
  home_sp_is_imputed?: number | boolean | null
  away_sp_is_imputed?: number | boolean | null
  home_sp_throws_is_lhp?: number | null
  away_sp_throws_is_lhp?: number | null
  home_sp_venue_era?: number | null
  away_sp_venue_era?: number | null
  home_sp_fastball_pct?: number | null
  away_sp_fastball_pct?: number | null
  home_sp_avg_velocity?: number | null
  away_sp_avg_velocity?: number | null
  // 불펜
  home_bullpen_era?: number | null
  away_bullpen_era?: number | null
  home_bullpen_whip?: number | null
  away_bullpen_whip?: number | null
  // 타선
  home_team_ops?: number | null
  away_team_ops?: number | null
  home_lineup_ops?: number | null
  away_lineup_ops?: number | null
  home_lineup_split_ops?: number | null
  away_lineup_split_ops?: number | null
  // IL (부상자)
  home_il_count?: number | null
  away_il_count?: number | null
  home_il_impact?: number | null
  away_il_impact?: number | null
  // 날씨/구장
  weather_temp?: number | null
  weather_wind_speed?: number | null
  is_dome_game?: number | boolean | null
  park_factor?: number | null
  // 최근 폼
  home_streak?: number | null
  away_streak?: number | null
  home_win_rate_L10?: number | null
  away_win_rate_L10?: number | null
  [key: string]: unknown
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
  feature_snapshot: FeatureSnapshot
  predicted_home_score?: number
  predicted_away_score?: number
  explanation?: Explanation
  lineup?: Lineup
  home_recent_results?: boolean[]
  away_recent_results?: boolean[]
}
