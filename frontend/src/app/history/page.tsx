"use client"
import { useState, useEffect } from "react"
import { getHistory } from "@/lib/api"
import { cn, CONFIDENCE_LABELS } from "@/lib/utils"
import dynamic from "next/dynamic"

const CalendarView = dynamic(() => import("./CalendarView"), { ssr: false })
const TeamTracker = dynamic(() => import("./TeamTracker"), { ssr: false })

type Tab = "list" | "calendar" | "teams" | "backtest"
type League = "KBO" | "MLB"

const TABS: { id: Tab; label: string }[] = [
  { id: "list", label: "📋 리스트" },
  { id: "calendar", label: "📅 캘린더" },
  { id: "teams", label: "🏆 팀별" },
  { id: "backtest", label: "🧪 백테스트" },
]

const LEAGUES: { id: League; label: string }[] = [
  { id: "KBO", label: "🇰🇷 KBO" },
  { id: "MLB", label: "🇺🇸 MLB" },
]

export default function HistoryPage() {
  const [league, setLeague] = useState<League>("KBO")
  const [tab, setTab] = useState<Tab>("list")
  const [page, setPage] = useState(1)
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  // 백테스트 상태
  const currentYear = new Date().getFullYear()
  const [btStart, setBtStart] = useState(`${currentYear - 1}-04-01`)
  const [btEnd, setBtEnd] = useState(`${currentYear - 1}-09-30`)
  const [btData, setBtData] = useState<any>(null)
  const [btLoading, setBtLoading] = useState(false)

  const runBacktest = () => {
    setBtLoading(true)
    setBtData(null)
    getHistory(league, { from_date: btStart, to_date: btEnd, per_page: 1 })
      .then((d) => setBtData(d))
      .finally(() => setBtLoading(false))
  }

  // 리그 변경 시 페이지 초기화
  const handleLeagueChange = (l: League) => {
    setLeague(l)
    setPage(1)
    setData(null)
  }

  useEffect(() => {
    if (tab !== "list") return
    setLoading(true)
    getHistory(league, { page, per_page: 20 })
      .then((d) => setData(d))
      .finally(() => setLoading(false))
  }, [league, page, tab])

  const summary = data?.summary
  const predictions = data?.predictions ?? []
  const pagination = data?.pagination

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">예측 히스토리</h1>
      </div>

      {/* 리그 선택 */}
      <div className="flex gap-2 mb-5">
        {LEAGUES.map((l) => (
          <button
            key={l.id}
            onClick={() => handleLeagueChange(l.id)}
            className={cn(
              "px-4 py-1.5 rounded-full text-sm font-medium border transition-colors",
              league === l.id
                ? "bg-blue-500 text-white border-blue-500"
                : "bg-white text-gray-600 border-gray-300 hover:border-blue-400 hover:text-blue-500"
            )}
          >
            {l.label}
          </button>
        ))}
      </div>

      {/* 콘텐츠 탭 */}
      <div className="flex gap-1 mb-6 border-b border-gray-200">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              tab === t.id
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* List Tab */}
      {tab === "list" && (
        <>
          {summary && (
            <div className="flex gap-3 mb-6 overflow-x-auto">
              <StatCard label="총 예측" value={summary.total_predictions} />
              <StatCard label="적중" value={summary.correct} />
              <StatCard label="정확도" value={`${(summary.accuracy * 100).toFixed(1)}%`} highlight />
              {Object.entries(summary.by_confidence ?? {}).map(([tier, s]: any) => (
                <StatCard
                  key={tier}
                  label={`${CONFIDENCE_LABELS[tier]} 신뢰도`}
                  value={`${(s.accuracy * 100).toFixed(1)}%`}
                  sub={`${s.total}경기`}
                />
              ))}
            </div>
          )}

          <div className="bg-white rounded-xl border shadow-sm overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs">
                <tr>
                  <th className="px-4 py-3 text-left">날짜</th>
                  <th className="px-4 py-3 text-left">경기</th>
                  <th className="px-4 py-3 text-left">예측</th>
                  <th className="px-4 py-3 text-left">실제</th>
                  <th className="px-4 py-3 text-center">예측 스코어</th>
                  <th className="px-4 py-3 text-center">실제 스코어</th>
                  <th className="px-4 py-3 text-center">예측 확률</th>
                  <th className="px-4 py-3 text-center">신뢰도</th>
                  <th className="px-4 py-3 text-center">결과</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr><td colSpan={9} className="text-center py-8 text-gray-400">로딩 중...</td></tr>
                ) : predictions.length === 0 ? (
                  <tr><td colSpan={9} className="text-center py-8 text-gray-400">{league} 데이터 없음</td></tr>
                ) : (
                  predictions.map((p: any) => (
                    <tr key={p.game_id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-500">{p.game_date}</td>
                      <td className="px-4 py-3 font-medium">{p.matchup}</td>
                      <td className="px-4 py-3">{p.predicted_winner}</td>
                      <td className="px-4 py-3 text-gray-500">{p.actual_winner ?? "-"}</td>
                      <td className="px-4 py-3 text-center text-gray-500">
                        {p.predicted_away_score != null && p.predicted_home_score != null
                          ? `${p.predicted_away_score}-${p.predicted_home_score}` : "-"}
                      </td>
                      <td className="px-4 py-3 text-center text-gray-500">
                        {p.away_score != null && p.home_score != null
                          ? `${p.away_score}-${p.home_score}` : "-"}
                      </td>
                      <td className="px-4 py-3 text-center">{((p.predicted_win_prob ?? p.home_win_prob) * 100).toFixed(0)}%</td>
                      <td className="px-4 py-3 text-center">{CONFIDENCE_LABELS[p.confidence_tier]}</td>
                      <td className="px-4 py-3 text-center">
                        {p.was_correct === null ? "—" : p.was_correct ? "✅" : "❌"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {pagination && pagination.pages > 1 && (
            <div className="flex justify-center gap-2 mt-4">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1 border rounded disabled:opacity-40"
              >
                이전
              </button>
              <span className="px-3 py-1 text-sm text-gray-600">
                {page} / {pagination.pages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(pagination.pages, p + 1))}
                disabled={page === pagination.pages}
                className="px-3 py-1 border rounded disabled:opacity-40"
              >
                다음
              </button>
            </div>
          )}
        </>
      )}

      {tab === "calendar" && <CalendarView league={league} />}
      {tab === "teams" && <TeamTracker league={league} />}

      {/* 백테스트 탭 */}
      {tab === "backtest" && (
        <div>
          <p className="text-sm text-gray-500 mb-4">
            과거 기간의 완료된 경기에 대한 모델 적중률을 분석합니다.
            백테스트 실행 전에 <code className="bg-gray-100 px-1 rounded text-xs">/admin/backtest</code>로 해당 기간 예측을 먼저 생성하세요.
          </p>

          {/* 날짜 범위 선택 */}
          <div className="bg-white rounded-xl border shadow-sm p-4 mb-4">
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className="text-xs text-gray-500 block mb-1">시작일</label>
                <input
                  type="date"
                  value={btStart}
                  onChange={(e) => setBtStart(e.target.value)}
                  className="border rounded-lg px-3 py-1.5 text-sm text-gray-700 focus:outline-none focus:border-blue-400"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">종료일</label>
                <input
                  type="date"
                  value={btEnd}
                  onChange={(e) => setBtEnd(e.target.value)}
                  className="border rounded-lg px-3 py-1.5 text-sm text-gray-700 focus:outline-none focus:border-blue-400"
                />
              </div>
              <button
                onClick={runBacktest}
                disabled={btLoading}
                className="px-5 py-1.5 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 disabled:opacity-50"
              >
                {btLoading ? "조회 중..." : "적중률 조회"}
              </button>
            </div>
          </div>

          {/* 결과 */}
          {btData && (
            <>
              <div className="flex gap-3 mb-4 overflow-x-auto">
                <StatCard label="총 예측" value={btData.summary?.total_predictions ?? 0} />
                <StatCard label="적중" value={btData.summary?.correct ?? 0} />
                <StatCard
                  label="전체 적중률"
                  value={btData.summary?.total_predictions > 0
                    ? `${(btData.summary.accuracy * 100).toFixed(1)}%`
                    : "-"}
                  highlight
                />
                {Object.entries(btData.summary?.by_confidence ?? {}).map(([tier, s]: any) => (
                  <StatCard
                    key={tier}
                    label={`${CONFIDENCE_LABELS[tier]} 신뢰도`}
                    value={s.total > 0 ? `${(s.accuracy * 100).toFixed(1)}%` : "-"}
                    sub={`${s.total}경기`}
                  />
                ))}
              </div>
              {btData.summary?.total_predictions === 0 && (
                <div className="text-center py-8 text-gray-400 text-sm bg-white rounded-xl border">
                  해당 기간에 예측 데이터가 없습니다. 먼저 백테스트 엔드포인트를 실행해주세요.
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, sub, highlight }: {
  label: string; value: string | number; sub?: string; highlight?: boolean
}) {
  return (
    <div className="bg-white rounded-xl border shadow-sm p-4 text-center flex-1 min-w-[100px]">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={cn("text-2xl font-bold", highlight ? "text-green-600" : "text-gray-900")}>
        {value}
      </div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}
