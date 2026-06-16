# Build context = repository root (monorepo with npm workspaces).
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package.json
RUN npm ci

COPY frontend frontend
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_USE_MSW=0
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_USE_MSW=$NEXT_PUBLIC_USE_MSW \
    NODE_ENV=production
RUN npm run build -w tg-platform-frontend

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/frontend/package.json frontend/package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/frontend/.next frontend/.next
COPY --from=builder /app/frontend/public frontend/public
COPY --from=builder /app/frontend/next.config.ts frontend/next.config.ts

EXPOSE 3000
WORKDIR /app/frontend
CMD ["npx", "next", "start", "--port", "3000", "--hostname", "0.0.0.0"]
