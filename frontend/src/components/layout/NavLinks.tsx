"use client"
import { usePathname } from "next/navigation"

export default function NavLinks() {
  const pathname = usePathname()

  return (
    <nav className="flex gap-4 text-sm">
      <a
        href="/games"
        className={pathname.startsWith("/games") ? "text-yellow-300 font-medium" : "hover:text-yellow-300 transition-colors"}
      >
        오늘의 경기
      </a>
      <a
        href="/history"
        className={pathname.startsWith("/history") ? "text-yellow-300 font-medium" : "hover:text-yellow-300 transition-colors"}
      >
        예측 히스토리
      </a>
    </nav>
  )
}
