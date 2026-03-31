export interface TeamBrief {
  id: number
  name: string
  short_name: string
  league: string
}

export interface StarterBrief {
  id: number
  name: string
  era?: number
}

export interface WeatherBrief {
  temperature_c?: number
  weather_main?: string
  wind_speed_ms?: number
  is_raining?: boolean
}

export interface PredictionBrief {
  home_win_prob: number
  predicted_winner: string
  confidence_tier: "high" | "medium" | "low"
  has_explanation: boolean
  predicted_home_score?: number
  predicted_away_score?: number
}

export interface Game {
  id: number
  game_date: string
  game_time?: string
  status: string
  home_team: TeamBrief
  away_team: TeamBrief
  home_starter?: StarterBrief
  away_starter?: StarterBrief
  venue?: string
  prediction?: PredictionBrief
  weather?: WeatherBrief
}

export interface GamesListResponse {
  date: string
  league: string
  games: Game[]
}
