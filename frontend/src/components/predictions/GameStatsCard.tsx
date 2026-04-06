"use client"
import type { PredictionDetail } from "@/types/prediction"

interface Props {
  prediction: PredictionDetail
  homeTeamName: string
  awayTeamName: string
}

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

function FormDots({ results }: { results?: boolean[] }) {
  if (!results || results.length === 0) {
    return <div className="flex gap-1">{Array.from({ length: 5 }).map((_, i) => <span key={i} className="w-3 h-3 rounded-full bg-gray-100" />)}</div>
  }
  const ordered = [...results].reverse()
  return (
    <div className="flex gap-1">
      {ordered.map((won, i) => (
        <span key={i} className={`w-3 h-3 rounded-full ${won ? "bg-blue-500" : "bg-red-400"}`} title={won ? "승" : "패"} />
      ))}
    </div>
  )
}

function StatCell({ label, value, sub }: { label: string; value: string | number | null; sub?: string }) {
  return (
    <div className="text-center">
      <div className="text-xs text-gray-400 mb-0.5">{label}</div>
      <div className="font-semibold text-gray-800 text-sm">{value ?? <span className="text-gray-300">-</span>}</div>
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

function fmtMph(v: unknown): string | null {
  if (v === null || v === undefined || (typeof v === "number" && isNaN(v))) return null
  return Number(v).toFixed(1) + " mph"
}

// 투구방향 뱃지
function HandsBadge({ isLhp }: { isLhp: number | undefined | null }) {
  if (isLhp === null || isLhp === undefined || isNaN(Number(isLhp))) {
    return <span className="text-gray-300 text-xs">-</span>
  }
  const lhp = Boolean(Number(isLhp))
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${lhp ? "bg-orange-100 text-orange-700" : "bg-sky-100 text-sky-700"}`}>
      {lhp ? "좌완" : "우완"}
    </span>
  )
}

// 비교 행
function CompareRow({ label, home, away, fmt: fmtFn = fmt, digits, lowerBetter = false, imputed = false }:
  { label: string; home: unknown; away: unknown; fmt?: (v: unknown, d?: number) => string | null; digits?: number; lowerBetter?: boolean; imputed?: boolean }) {
  const h = fmtFn(home, digits)
  const a = fmtFn(away, digits)
  const hNum = Number(home)
  const aNum = Number(away)
  const hBetter = h && a ? (lowerBetter ? hNum < aNum : hNum > aNum) : null
  const aBetter = h && a ? (lowerBetter ? aNum < hNum : aNum > hNum) : null
  return (
    <div className="grid grid-cols-3 gap-2 py-1.5 border-t border-gray-50">
      <div className="text-xs text-gray-400">{label}</div>
      <div className={`text-center text-sm font-medium ${imputed ? "text-orange-400" : hBetter ? "text-blue-600" : "text-gray-800"}`}>{h ?? "-"}</div>
      <div className={`text-center text-sm font-medium ${imputed ? "text-orange-400" : aBetter ? "text-red-600" : "text-gray-800"}`}>{a ?? "-"}</div>
    </div>
  )
}

export default function GameStatsCard({ prediction, homeTeamName, awayTeamName }: Props) {
  const s = prediction.feature_snapshot
  const homeRecent = prediction.home_recent_results
  const awayRecent = prediction.away_recent_results
  const homeImputed = Boolean(s.home_sp_is_imputed)
  const awayImputed = Boolean(s.away_sp_is_imputed)
  const isDome = Boolean(s.is_dome_game)
  const isMLB = s.home_sp_fip !== undefined || s.home_bullpen_era !== undefined

  const homeIlCount = s.home_il_count ?? 0
  const awayIlCount = s.away_il_count ?? 0

  return (
    <div className="space-y-3">

      {/* ── 선발 투수 ─────────────────────────────────── */}
      <div className="bg-white rounded-xl border shadow-sm p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
          ⚾ 선발 투수
          {(homeImputed || awayImputed) && <span className="text-xs text-orange-400 font-normal">* 추정값 포함</span>}
        </h3>
        {/* 헤더 */}
        <div className="grid grid-cols-3 gap-2 mb-1">
          <div />
          <div className="text-center text-xs font-medium text-blue-600">{homeTeamName}</div>
          <div className="text-center text-xs font-medium text-red-600">{awayTeamName}</div>
        </div>

        {/* 투구방향 */}
        <div className="grid grid-cols-3 gap-2 py-1.5 border-t border-gray-50">
          <div className="text-xs text-gray-400">투구방향</div>
          <div className="flex justify-center"><HandsBadge isLhp={s.home_sp_throws_is_lhp} /></div>
          <div className="flex justify-center"><HandsBadge isLhp={s.away_sp_throws_is_lhp} /></div>
        </div>

        <CompareRow label="ERA (시즌)"     home={s.home_sp_era_season}  away={s.away_sp_era_season}  lowerBetter imputed={homeImputed || awayImputed} />
        <CompareRow label="FIP"            home={s.home_sp_fip}          away={s.away_sp_fip}          lowerBetter />
        <CompareRow label="WHIP"           home={s.home_sp_whip_season} away={s.away_sp_whip_season} lowerBetter />
        <CompareRow label="K/9"            home={s.home_sp_k9_season}   away={s.away_sp_k9_season} />
        <CompareRow label="ERA (최근3경기)" home={s.home_sp_era_L3}      away={s.away_sp_era_L3}      lowerBetter />
        {isMLB && (
          <>
            <CompareRow label="ERA (홈/원정)" home={s.home_sp_venue_era} away={s.away_sp_venue_era} lowerBetter />
            <CompareRow label="패스트볼%" home={s.home_sp_fastball_pct} away={s.away_sp_fastball_pct} fmt={(v) => v != null ? (Number(v) * 100).toFixed(1) + "%" : null} />
            <CompareRow label="평균 구속" home={s.home_sp_avg_velocity} away={s.away_sp_avg_velocity} fmt={fmtMph} />
          </>
        )}

        {/* 에이스/피로 */}
        <div className="grid grid-cols-3 gap-2 py-1.5 border-t border-gray-50">
          <div className="text-xs text-gray-400">에이스 / 피로</div>
          <div className="text-center text-xs">
            {s.home_sp_is_ace ? "⭐ 에이스" : ""}{s.home_sp_is_fatigued ? " ⚠️ 피로" : ""}
            {!s.home_sp_is_ace && !s.home_sp_is_fatigued && <span className="text-gray-300">-</span>}
          </div>
          <div className="text-center text-xs">
            {s.away_sp_is_ace ? "⭐ 에이스" : ""}{s.away_sp_is_fatigued ? " ⚠️ 피로" : ""}
            {!s.away_sp_is_ace && !s.away_sp_is_fatigued && <span className="text-gray-300">-</span>}
          </div>
        </div>
      </div>

      {/* ── 팀 불펜 (MLB) ─────────────────────────────── */}
      {isMLB && (s.home_bullpen_era != null || s.away_bullpen_era != null) && (
        <div className="bg-white rounded-xl border shadow-sm p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">🔥 팀 불펜</h3>
          <div className="grid grid-cols-3 gap-2 mb-1">
            <div />
            <div className="text-center text-xs font-medium text-blue-600">{homeTeamName}</div>
            <div className="text-center text-xs font-medium text-red-600">{awayTeamName}</div>
          </div>
          <CompareRow label="불펜 ERA"  home={s.home_bullpen_era}  away={s.away_bullpen_era}  lowerBetter />
          <CompareRow label="불펜 WHIP" home={s.home_bullpen_whip} away={s.away_bullpen_whip} lowerBetter />
        </div>
      )}

      {/* ── 부상자 현황 (MLB) ─────────────────────────── */}
      {isMLB && (homeIlCount > 0 || awayIlCount > 0) && (
        <div className="bg-amber-50 rounded-xl border border-amber-200 p-4">
          <h3 className="text-sm font-semibold text-amber-700 mb-2">🏥 부상자 명단 (IL)</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="text-center">
              <div className="text-xs text-gray-500 mb-1">{homeTeamName}</div>
              <div className={`text-2xl font-bold ${homeIlCount >= 5 ? "text-red-600" : homeIlCount >= 3 ? "text-orange-500" : "text-gray-700"}`}>
                {homeIlCount}명
              </div>
              {s.home_il_impact != null && (
                <div className="text-xs text-gray-400 mt-0.5">영향도 {Number(s.home_il_impact).toFixed(1)}</div>
              )}
            </div>
            <div className="text-center">
              <div className="text-xs text-gray-500 mb-1">{awayTeamName}</div>
              <div className={`text-2xl font-bold ${awayIlCount >= 5 ? "text-red-600" : awayIlCount >= 3 ? "text-orange-500" : "text-gray-700"}`}>
                {awayIlCount}명
              </div>
              {s.away_il_impact != null && (
                <div className="text-xs text-gray-400 mt-0.5">영향도 {Number(s.away_il_impact).toFixed(1)}</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── 팀 타선 ─────────────────────────────────── */}
      <div className="bg-white rounded-xl border shadow-sm p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">🏏 팀 타선</h3>
        <div className="grid grid-cols-3 gap-2 mb-1">
          <div />
          <div className="text-center text-xs font-medium text-blue-600">{homeTeamName}</div>
          <div className="text-center text-xs font-medium text-red-600">{awayTeamName}</div>
        </div>
        <CompareRow label="OPS"     home={s.home_lineup_ops}            away={s.away_lineup_ops} />
        <CompareRow label="유효 OPS (vs 상대투수)" home={s.home_lineup_split_ops ?? s.home_lineup_effective_ops} away={s.away_lineup_split_ops ?? s.away_lineup_effective_ops} />
        <CompareRow label="wRC+"    home={s.home_lineup_wrc_plus}       away={s.away_lineup_wrc_plus}       digits={0} />
        <CompareRow label="삼진율"  home={s.home_lineup_k_rate}         away={s.away_lineup_k_rate}         fmt={(v) => v != null ? (Number(v) * 100).toFixed(1) + "%" : null} lowerBetter />
      </div>

      {/* ── 최근 흐름 ────────────────────────────────── */}
      <div className="bg-white rounded-xl border shadow-sm p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">📈 최근 흐름</h3>
        <div className="grid grid-cols-2 gap-4">
          {[
            { label: homeTeamName, color: "text-blue-600", recent: homeRecent, prefix: "home" },
            { label: awayTeamName, color: "text-red-600",  recent: awayRecent, prefix: "away" },
          ].map(({ label, color, recent, prefix }) => (
            <div key={prefix}>
              <p className={`text-xs font-medium ${color} mb-2`}>{label}</p>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">최근 5경기</span>
                  <div className="flex items-center gap-2">
                    <FormDots results={recent} />
                    <span className="text-xs text-gray-600">{pct((s as any)[`${prefix}_win_rate_L5`])}</span>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">최근 10경기</span>
                  <span className="text-xs font-medium text-gray-700">{pct((s as any)[`${prefix}_win_rate_L10`]) ?? "-"}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">연속</span>
                  <StreakBadge streak={Number((s as any)[`${prefix}_win_streak`] ?? 0)} />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">득실차(10경기)</span>
                  <span className={`text-xs font-medium ${Number((s as any)[`${prefix}_run_diff_L10`]) > 0 ? "text-blue-600" : Number((s as any)[`${prefix}_run_diff_L10`]) < 0 ? "text-red-600" : "text-gray-600"}`}>
                    {(s as any)[`${prefix}_run_diff_L10`] !== undefined
                      ? (Number((s as any)[`${prefix}_run_diff_L10`]) > 0 ? "+" : "") + (s as any)[`${prefix}_run_diff_L10`]
                      : "-"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">피타고리안</span>
                  <span className="text-xs font-medium text-gray-700">{pct((s as any)[`${prefix}_pythagorean_L30`]) ?? "-"}</span>
                </div>
              </div>
            </div>
          ))}
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
            <div className="text-xs text-gray-400">(최근 2년)</div>
            {s.h2h_run_diff_home !== undefined && (
              <div className="mt-1">
                <span className={`text-xs font-medium ${Number(s.h2h_run_diff_home) > 0 ? "text-blue-600" : "text-red-600"}`}>
                  득실차 {Number(s.h2h_run_diff_home) > 0 ? "+" : ""}{Number(s.h2h_run_diff_home).toFixed(1)}
                </span>
              </div>
            )}
          </div>
        </div>

        {!isDome ? (
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
        ) : (
          <div className="bg-blue-50 rounded-xl border border-blue-100 p-4 flex items-center justify-center text-xs text-blue-500 text-center">
            🏠 돔구장<br />날씨 영향 없음
          </div>
        )}
      </div>

    </div>
  )
}
