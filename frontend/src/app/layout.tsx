import type { Metadata } from "next"
import "./globals.css"
import NavLinks from "@/components/layout/NavLinks"

export const metadata: Metadata = {
  title: "야구 승리 예측",
  description: "KBO/MLB 경기 승리 확률 예측 및 AI 해설",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="ko">
      <body className="min-h-screen bg-gray-50 text-gray-900">
        <header className="bg-primary text-white shadow-md">
          <div className="max-w-6xl mx-auto px-4 py-3 flex items-center gap-6">
            <a href="/games" className="text-xl font-bold tracking-tight">
              ⚾ 야구 예측
            </a>
            <NavLinks />
          </div>
        </header>
        <main className="max-w-6xl mx-auto px-4 py-6">
          {children}
        </main>
      </body>
    </html>
  )
}
