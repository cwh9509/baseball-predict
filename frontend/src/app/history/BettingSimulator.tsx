"use client"
import { useState, useEffect, useMemo } from "react"
import { getHistoryBetting } from "@/lib/api"
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine, ResponsiveContainer } from "recharts"

interface BetRecord {
  game_date: string
  game_id: number
  predicted_win_prob: number
  was_correct: boolean
  confidence_tier: string
}

// Kelly Criterion: f* = (b*p - q) / b, capped at maxFrac
// Assumes decimal odds = 1.9 (net odds b = 0.9)
const DECIMAL_ODDS = 1.9
const NET_ODDS = DECIMAL_ODDS - 1  // 0.9

function kelliFraction(p: number, maxFrac: number): number {
  const q = 1 - p
  const f = (NET_ODDS * p - q) / NET_ODDS
  return Math.max(0, Math.min(f, maxFrac))
}

function simulate(bets: BetRecord[], minProb: number, kellyMax: number): { data: Array<{ label: string; bankroll: number; idx: number }>; stats: { betsPlaced: number; wins: number; finalBankroll: number; peak: number; drawdown: number } } {
  let bankroll = 100
  let peak = 100
  let maxDrawdown = 0
  let betsPlaced = 0
  let wins = 0
  const data: Array<{ label: string; bankroll: number; idx: number }> = [{ label: "시작", bankroll: 100, idx: 0 }]

  let betIdx = 1
  for (const bet of bets) {
    if (bet.predicted_win_prob < minProb) continue
    const f = kelliFraction(bet.predicted_win_prob, kellyMax)
    if (f <= 0) continue

    const stake = bankroll * f
    betsPlaced++
    if (bet.was_correct) {
      bankroll += stake * NET_ODDS
      wins++
    } else {
      bankroll -= stake
    }
    bankroll = Math.max(bankroll, 0.01)

    if (bankroll > peak) peak = bankroll
    const dd = (peak - bankroll) / peak
    if (dd > maxDrawdown) maxDrawdown = dd

    data.push({ label: bet.game_date.slice(5), bankroll: Math.round(bankroll * 10) / 10, idx: betIdx++ })
  }

  return {
    data,
    stats: {
      betsPlaced,
      wins,
      finalBankroll: Math.round(bankroll * 10) / 10,
      peak: Math.round(peak * 10) / 10,
      drawdown: Math.round(maxDrawdown * 1000) / 10,
    },
  }
}

function StatBox({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="bg-white rounded-xl border shadow-sm p-3 text-center">
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div className={`text-xl font-bold ${color ?? "text-gray-800"}`}>{value}</div>
      {sub && <div className="text-xs text-gray-400">{sub}</div>}
    </div>
  )
}

export default function BettingSimulator({ league }: { league: string }) {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [bets, setBets] = useState<BetRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [minProb, setMinProb] = useState(0.58)
  const [kellyMax, setKellyMax] = useState(0.25)

  useEffect(() => {
    setLoading(true)
    getHistoryBetting(league, year)
      .then((d) => setBets(d.bets))
      .finally(() => setLoading(false))
  }, [league, year])

  const result = useMemo(() => simulate(bets, minProb, kellyMax), [bets, minProb, kellyMax])
  const { data, stats } = result

  const returnPct = (((stats.finalBankroll - 100) / 100) * 100).toFixed(1)
  const returnColor = stats.finalBankroll >= 100 ? "text-green-600" : "text-red-500"
  const winRate = stats.betsPlaced > 0 ? ((stats.wins / stats.betsPlaced) * 100).toFixed(1) : "-"

  return (
    <div>
      {/* Controls */}
      <div className="bg-white rounded-xl border shadow-sm p-4 mb-4">
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="text-xs text-gray-500 block mb-1">연도</label>
            <div className="flex items-center gap-2">
              <button onClick={() => setYear(y => y - 1)} className="px-2 py-1 border rounded text-sm">←</button>
              <span className="font-medium text-sm">{year}</span>
              <button onClick={() => setYear(y => y + 1)} className="px-2 py-1 border rounded text-sm">→</button>
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">최소 예측 확률: {Math.round(minProb * 100)}%</label>
            <input
              type="range" min={52} max={80} step={1}
              value={Math.round(minProb * 100)}
              onChange={(e) => setMinProb(Number(e.target.value) / 100)}
              className="w-full accent-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">켈리 최대 배팅: {Math.round(kellyMax * 100)}%</label>
            <input
              type="range" min={5} max={50} step={5}
              value={Math.round(kellyMax * 100)}
              onChange={(e) => setKellyMax(Number(e.target.value) / 100)}
              className="w-full accent-blue-500"
            />
          </div>
        </div>
        <div className="text-xs text-gray-400 mt-2">
          * 가상 배당률 1.9 적용 | 초기 자본 100 | 켈리 기준(Kelly Criterion) 베팅 전략
        </div>
      </div>

      {loading ? (
        <div className="text-center py-12 text-gray-400 text-sm">로딩 중...</div>
      ) : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <StatBox
              label="최종 수익률"
              value={`${returnPct}%`}
              sub={`${stats.finalBankroll} / 100`}
              color={returnColor}
            />
            <StatBox label="베팅 횟수" value={stats.betsPlaced} sub={`적중 ${stats.wins}번`} />
            <StatBox label="승률" value={`${winRate}%`} sub="베팅 기준" />
            <StatBox label="최대 손실" value={`-${stats.drawdown}%`} sub={`최고점 ${stats.peak}`} />
          </div>

          {/* Chart */}
          <div className="bg-white rounded-xl border shadow-sm p-4">
            <div className="text-sm font-medium text-gray-700 mb-3">자본금 추이 (시작: 100)</div>
            {data.length <= 1 ? (
              <div className="text-center py-8 text-gray-400 text-sm">
                조건에 맞는 베팅 데이터 없음 (최소 확률 낮추거나 연도 확인)
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 10 }}
                    interval={Math.max(1, Math.floor(data.length / 10) - 1)}
                  />
                  <YAxis tick={{ fontSize: 10 }} domain={["auto", "auto"]} />
                  <Tooltip
                    formatter={(v: number) => [`${v}`, "자본금"]}
                    labelFormatter={(l) => `${l}`}
                  />
                  <ReferenceLine y={100} stroke="#9ca3af" strokeDasharray="4 2" />
                  <Line
                    type="monotone"
                    dataKey="bankroll"
                    stroke="#3b82f6"
                    dot={false}
                    strokeWidth={2}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </>
      )}
    </div>
  )
}
