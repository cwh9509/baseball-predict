"use client"
import type { PredictionDetail } from "@/types/prediction"

interface Props {
  prediction: PredictionDetail
  homeTeamName: string
  awayTeamName: string
}

// 연승/연패 뱃지 색상
function StreakBadge({ streak }: { streak: number }) {
  if (streak === 0) return <span className="text-gray-400 text-xs">-</span>
  const n = Math.abs(streak)
  const isWin = streak > 0
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${isWin ? "bg-blue-100 text-blue-700" : "bg-red-100 text-red-700"}`}>
      {n}연{isWin ? "승" : "패"}
    </span>
  )
}

// 최근 5경기 승률 → W/L 점 시각화 (추정)
function FormDots({ winRate, games = 5 }: { winRate: number; games?: number }) {
  const wins = Math.round(winRate * games)
  return (
    <div className="flex gap-1">
      {Array.from({ length: games }).map((_, i) => (
        <span
          key={i}
          className={`w-3 h-3 rounded-full ${i < wins ? "bg-blue-500" : "bg-gray-200"}`}
        />
      ))}
    </div>
  )
}

// 수치 셀
function StatCell({ label, value, sub }: { label: string; value: string | number | null; sub?: string }) {
  return (
    <div className="text-center">
      <div className="text-xs text-gray-400 mb-0.5">{label}</div>
      <div className="font-semibold text-gray-800 text-sm">
        {value ?? <span className="text-gray-300">-</span>}
      </div>
      {sub && <div className="text-xs text-gray-400">{sub}</div>}
    </div>
  )
}

function fmt(v: unknown, digits = 2): string | null {
  if (v === null || v === undefined || (typeof v === "number" && isNaN(v))) return null
  return Number(v).toFixed(digits)
}

function pct(v: unknown): string | null {
  if (v === null || v === undefined) return null
  return (Number(v) * 100).toFixed(0) + "%"
}

export default function GameStatsCard({ prediction, homeTeamName, awayTeamName }: Props) {
  const s = prediction.feature_snapshot
  const homeImputed = Boolean(s.home_sp_is_imputed)
  const awayImputed = Boolean(s.away_sp_is_imputed)
  const isDome = Boolean(s.is_dome_game)

  return (
    <div className="space-y-3">

      {/* ── 투수 ───────────────────────────────────── */}
      <div className="bg-white rounded-xl border shadow-sm p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-1">
          ⚾ 선발 투수
          {(homeImputed || awayImputed) && (
            <span className="text-xs text-orange-400 font-normal ml-1">* 추정값 포함</span>
          )}
        </h3>
        <div className="grid grid-cols-3 gap-2 mb-2">
          <div />
          <div className="text-center text-xs font-medium text-blue-600">{homeTeamName}</div>
          <div className="text-center text-xs font-medium text-red-600">{awayTeamName}</div>
        </div>
        {[
          { label: "ERA (시즌)", home: s.home_sp_era_season, away: s.away_sp_era_season },
          { label: "WHIP", home: s.home_sp_whip_season, away: s.away_sp_whip_season },
          { label: "K/9", home: s.home_sp_k9_season, away: s.away_sp_k9_season },
          { label: "ERA (최근3경기)", home: s.home_sp_era_L3, away: s.away_sp_era_L3 },
        ].map(({ label, home, away }) => (
          <div key={label} className="grid grid-cols-3 gap-2 py-1.5 border-t border-gray-50">
            <div className="text-xs text-gray-400">{label}</div>
            <div className={`text-center text-sm font-medium ${homeImputed ? "text-orange-400" : "text-gray-800"}`}>
              {fmt(home) ?? "-"}
            </div>
            <div className={`text-center text-sm font-medium ${awayImputed ? "text-orange-400" : "text-gray-800"}`}>
              {fmt(away) ?? "-"}
            </div>
          </div>
        ))}
        <div className="grid grid-cols-3 gap-2 py-1.5 border-t border-gray-50">
          <div className="text-xs text-gray-400">에이스 여부</div>
          <div className="text-center text-sm">{s.home_sp_is_ace ? "✅" : "-"}</div>
          <div className="text-center text-sm">{s.away_sp_is_ace ? "✅" : "-"}</div>
        </div>
        <div className="grid grid-cols-3 gap-2 py-1.5 border-t border-gray-50">
          <div className="text-xs text-gray-400">피로도</div>
          <div className="text-center text-sm">{s.home_sp_is_fatigued ? "⚠️ 피로" : "정상"}</div>
          <div className="text-center text-sm">{s.away_sp_is_fatigued ? "⚠️ 피로" : "정상"}</div>
        </div>
      </div>

      {/* ── 팀 타선 ─────────────────────────────────── */}
      <div className="bg-white rounded-xl border shadow-sm p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">🏏 팀 타선</h3>
        <div className="grid grid-cols-3 gap-2 mb-2">
          <div />
          <div className="text-center text-xs font-medium text-blue-600">{homeTeamName}</div>
          <div className="text-center text-xs font-medium text-red-600">{awayTeamName}</div>
        </div>
        {[
          { label: "OPS", home: s.home_lineup_ops, away: s.away_lineup_ops },
          { label: "유효 OPS", home: s.home_lineup_effective_ops, away: s.away_lineup_effective_ops },
          { label: "wRC+", home: s.home_lineup_wrc_plus, away: s.away_lineup_wrc_plus, digits: 0 },
          { label: "삼진율", home: s.home_lineup_k_rate, away: s.away_lineup_k_rate },
        ].map(({ label, home, away, digits }) => (
          <div key={label} className="grid grid-cols-3 gap-2 py-1.5 border-t border-gray-50">
            <div className="text-xs text-gray-400">{label}</div>
            <div className="text-center text-sm font-medium text-gray-800">{fmt(home, digits ?? 3) ?? "-"}</div>
            <div className="text-center text-sm font-medium text-gray-800">{fmt(away, digits ?? 3) ?? "-"}</div>
          </div>
        ))}
      </div>

      {/* ── 최근 흐름 ────────────────────────────────── */}
      <div className="bg-white rounded-xl border shadow-sm p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">📈 최근 흐름</h3>
        <div className="grid grid-cols-2 gap-4">
          {/* 홈팀 */}
          <div>
            <p className="text-xs font-medium text-blue-600 mb-2">{homeTeamName}</p>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">최근 5경기</span>
                <div className="flex items-center gap-2">
                  <FormDots winRate={Number(s.home_win_rate_L5 ?? 0)} />
                  <span className="text-xs text-gray-600">{pct(s.home_win_rate_L5)}</span>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">최근 10경기</span>
                <span className="text-xs font-medium text-gray-700">{pct(s.home_win_rate_L10) ?? "-"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">연속</span>
                <StreakBadge streak={Number(s.home_win_streak ?? 0)} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">득실차(10경기)</span>
                <span className={`text-xs font-medium ${Number(s.home_run_diff_L10) > 0 ? "text-blue-600" : Number(s.home_run_diff_L10) < 0 ? "text-red-600" : "text-gray-600"}`}>
                  {s.home_run_diff_L10 !== undefined ? (Number(s.home_run_diff_L10) > 0 ? "+" : "") + s.home_run_diff_L10 : "-"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">피타고리안</span>
                <span className="text-xs font-medium text-gray-700">{pct(s.home_pythagorean_L30) ?? "-"}</span>
              </div>
            </div>
          </div>
          {/* 원정팀 */}
          <div>
            <p className="text-xs font-medium text-red-600 mb-2">{awayTeamName}</p>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">최근 5경기</span>
                <div className="flex items-center gap-2">
                  <FormDots winRate={Number(s.away_win_rate_L5 ?? 0)} />
                  <span className="text-xs text-gray-600">{pct(s.away_win_rate_L5)}</span>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">최근 10경기</span>
                <span className="text-xs font-medium text-gray-700">{pct(s.away_win_rate_L10) ?? "-"}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">연속</span>
                <StreakBadge streak={Number(s.away_win_streak ?? 0)} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">득실차(10경기)</span>
                <span className={`text-xs font-medium ${Number(s.away_run_diff_L10) > 0 ? "text-blue-600" : Number(s.away_run_diff_L10) < 0 ? "text-red-600" : "text-gray-600"}`}>
                  {s.away_run_diff_L10 !== undefined ? (Number(s.away_run_diff_L10) > 0 ? "+" : "") + s.away_run_diff_L10 : "-"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">피타고리안</span>
                <span className="text-xs font-medium text-gray-700">{pct(s.away_pythagorean_L30) ?? "-"}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── 상대전적 + 날씨 ───────────────────────────── */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-white rounded-xl border shadow-sm p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">🔄 상대전적</h3>
          <div className="text-center">
            <div className="text-2xl font-bold text-gray-800">
              {s.h2h_win_pct_home !== undefined ? pct(s.h2h_win_pct_home) : "-"}
            </div>
            <div className="text-xs text-gray-400 mt-1">{homeTeamName} 홈 승률</div>
            <div className="text-xs text-gray-400">(최근 2년 기준)</div>
            <div className="mt-1">
              {s.h2h_run_diff_home !== undefined && (
                <span className={`text-xs font-medium ${Number(s.h2h_run_diff_home) > 0 ? "text-blue-600" : "text-red-600"}`}>
                  득실차 {Number(s.h2h_run_diff_home) > 0 ? "+" : ""}{Number(s.h2h_run_diff_home).toFixed(1)}
                </span>
              )}
            </div>
          </div>
        </div>

        {!isDome && (
          <div className="bg-white rounded-xl border shadow-sm p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-2">🌤 날씨</h3>
            <div className="grid grid-cols-2 gap-y-2 gap-x-1">
              <StatCell label="기온" value={s.temperature_c !== undefined ? `${s.temperature_c}°C` : null}
                sub={Boolean(s.is_hot) ? "고온" : Boolean(s.is_cold) ? "저온" : undefined} />
              <StatCell label="풍속" value={s.wind_speed_ms !== undefined ? `${Number(s.wind_speed_ms).toFixed(1)}m/s` : null}
                sub={Boolean(s.wind_favor_home) ? "홈 순풍" : Boolean(s.wind_favor_pitcher) ? "투수 유리" : undefined} />
              <StatCell label="습도" value={s.humidity_pct !== undefined ? `${s.humidity_pct}%` : null} />
              <StatCell label="우천" value={Boolean(s.is_raining) ? "☔ 예보" : "없음"} />
            </div>
          </div>
        )}
        {isDome && (
          <div className="bg-blue-50 rounded-xl border border-blue-100 p-4 flex items-center justify-center text-xs text-blue-500">
            🏠 돔구장<br />날씨 영향 없음
          </div>
        )}
      </div>

    </div>
  )
}
