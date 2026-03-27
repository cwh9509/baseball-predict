"use client"
import type { Explanation } from "@/types/prediction"
import { IMPACT_COLORS, IMPACT_ICONS } from "@/lib/utils"

interface Props {
  explanation?: Explanation
  isLoading?: boolean
}

export default function LLMExplanationCard({ explanation, isLoading }: Props) {
  if (isLoading) {
    return (
      <div className="border rounded-lg p-4 bg-white animate-pulse">
        <div className="h-4 bg-gray-200 rounded w-3/4 mb-3" />
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-3 bg-gray-100 rounded w-full" />
          ))}
        </div>
      </div>
    )
  }

  if (!explanation) {
    return (
      <div className="border rounded-lg p-4 bg-white text-gray-400 text-sm text-center">
        AI 해설을 생성하는 중입니다...
      </div>
    )
  }

  return (
    <div className="border rounded-lg p-4 bg-white shadow-sm">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-lg">🤖</span>
        <h3 className="font-semibold text-gray-700 text-sm">AI 분석 코멘트</h3>
        <span className="text-xs text-gray-400 ml-auto">Claude 제공</span>
      </div>

      <p className="text-gray-800 text-sm mb-4 leading-relaxed">
        {explanation.summary}
      </p>

      <div className="space-y-2 mb-4">
        {explanation.key_factors.map((f, i) => (
          <div key={i} className="flex gap-2 text-sm">
            <span className={`${IMPACT_COLORS[f.impact]} font-bold mt-0.5 flex-shrink-0`}>
              {IMPACT_ICONS[f.impact]}
            </span>
            <div>
              <span className="font-medium text-gray-700">{f.factor}: </span>
              <span className="text-gray-600">{f.detail}</span>
            </div>
          </div>
        ))}
      </div>

      <p className="text-xs text-gray-400 border-t pt-2">{explanation.confidence_note}</p>
    </div>
  )
}
