"use client"
import { useState, useEffect } from "react"
import { getHistory } from "@/lib/api"
import { cn, CONFIDENCE_LABELS } from "@/lib/utils"
import dynamic from "next/dynamic"

const CalendarView = dynamic(() => import("./CalendarView"), { ssr: false })
const TeamTracker = dynamic(() => import("./TeamTracker"), { ssr: false })
const BettingSimulator = dynamic(() => import("./BettingSimulator"), { ssr: false })

type Tab = "list" | "calendar" | "teams" | "betting"

const TABS: { id: Tab; label: string }[] = [
  { id: "list", label: "📋 리스트" },
  { id: "calendar", label: "📅 캘린더" },
  { id: "teams", label: "🏆 팀별" },
  { id: "betting", label: "💰 베팅 시뮬" },
]

export default function HistoryPage() {
  const league = "KBO"
  const [tab, setTab] = useState<Tab>("list")
  const [page, setPage] = useState(1)
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

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
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">예측 히스토리</h1>
      </div>

      {/* Tabs */}
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
          {/* 요약 카드 */}
          {summary && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
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

          {/* 예측 테이블 */}
          <div className="bg-white rounded-xl border shadow-sm overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs">
                <tr>
                  <th className="px-4 py-3 text-left">날짜</th>
                  <th className="px-4 py-3 text-left">경기</th>
                  <th className="px-4 py-3 text-left">예측</th>
                  <th className="px-4 py-3 text-left">실제</th>
                  <th className="px-4 py-3 text-center">예측 확률</th>
                  <th className="px-4 py-3 text-center">신뢰도</th>
                  <th className="px-4 py-3 text-center">결과</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr><td colSpan={7} className="text-center py-8 text-gray-400">로딩 중...</td></tr>
                ) : predictions.length === 0 ? (
                  <tr><td colSpan={7} className="text-center py-8 text-gray-400">데이터 없음</td></tr>
                ) : (
                  predictions.map((p: any) => (
                    <tr key={p.game_id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-500">{p.game_date}</td>
                      <td className="px-4 py-3 font-medium">{p.matchup}</td>
                      <td className="px-4 py-3">{p.predicted_winner}</td>
                      <td className="px-4 py-3 text-gray-500">{p.actual_winner ?? "-"}</td>
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

          {/* 페이지네이션 */}
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
      {tab === "betting" && <BettingSimulator league={league} />}
    </div>
  )
}

function StatCard({ label, value, sub, highlight }: {
  label: string; value: string | number; sub?: string; highlight?: boolean
}) {
  return (
    <div className="bg-white rounded-xl border shadow-sm p-4 text-center">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={cn("text-2xl font-bold", highlight ? "text-green-600" : "text-gray-900")}>
        {value}
      </div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}
