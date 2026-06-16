# Build context = repository root (monorepo with npm workspaces).
FROM node:20-alpine AS builder
WORKDIR /app

# Install workspace dependencies (needs every workspace's package.json present).
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY apps/presentation/package.json apps/presentation/package.json
RUN npm ci

# Build the product frontend only.
COPY apps/web apps/web
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_USE_MSW=0
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_USE_MSW=$NEXT_PUBLIC_USE_MSW \
    NODE_ENV=production
RUN npm run build -w tg-platform-web

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/apps/web/package.json apps/web/package.json
COPY --from=builder /app/apps/presentation/package.json apps/presentation/package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/apps/web/.next apps/web/.next
COPY --from=builder /app/apps/web/public apps/web/public
COPY --from=builder /app/apps/web/next.config.ts apps/web/next.config.ts

EXPOSE 3000
WORKDIR /app/apps/web
CMD ["npx", "next", "start", "--port", "3000", "--hostname", "0.0.0.0"]
