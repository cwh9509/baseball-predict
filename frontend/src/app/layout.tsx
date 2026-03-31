import type { Metadata } from "next"
import "./globals.css"
import NavLinks from "@/components/layout/NavLinks"
import { version } from "../../package.json"

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
        <header className="bg-gradient-to-r from-[#1e3a5f] to-[#2d5a8e] text-white shadow-lg border-b border-white/10">
          <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
            <a href="/games" className="flex items-center gap-2 group">
              <span className="text-2xl">⚾</span>
              <div className="flex flex-col leading-none">
                <span className="text-lg font-extrabold tracking-tight group-hover:text-yellow-300 transition-colors">야구 예측</span>
                <span className="text-[10px] text-white/50 font-medium tracking-widest uppercase">KBO · v{version}</span>
              </div>
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
