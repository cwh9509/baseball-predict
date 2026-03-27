/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",  // Docker 멀티스테이지 빌드용
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  },
}

module.exports = nextConfig
