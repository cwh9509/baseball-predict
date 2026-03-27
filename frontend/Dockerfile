# ---- 빌드 스테이지 ----
FROM node:20-alpine AS builder
WORKDIR /app

# NEXT_PUBLIC_API_URL은 빌드 시 번들에 포함됨 (런타임 env X)
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- 런타임 스테이지 ----
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

# standalone 출력 복사
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
