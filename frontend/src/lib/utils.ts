import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "short",
  })
}

export function formatProbability(prob: number): string {
  return `${(prob * 100).toFixed(1)}%`
}

export const CONFIDENCE_LABELS: Record<string, string> = {
  high: "높음",
  medium: "중간",
  low: "낮음",
}

export const CONFIDENCE_COLORS: Record<string, string> = {
  high: "text-green-600 bg-green-50 border-green-200",
  medium: "text-yellow-600 bg-yellow-50 border-yellow-200",
  low: "text-gray-500 bg-gray-50 border-gray-200",
}

export const IMPACT_ICONS: Record<string, string> = {
  positive: "▲",
  negative: "▼",
  neutral: "●",
}

export const IMPACT_COLORS: Record<string, string> = {
  positive: "text-green-600",
  negative: "text-red-500",
  neutral: "text-gray-500",
}
