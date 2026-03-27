import type { Config } from "tailwindcss"

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: "#1e3a5f",    // 야구 네이비
        accent: "#e84c3d",     // 빨간색 강조
        "high-conf": "#16a34a",
        "med-conf": "#ca8a04",
        "low-conf": "#6b7280",
      },
    },
  },
  plugins: [],
}

export default config
