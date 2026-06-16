# Build context = repository root (monorepo with npm workspaces).
FROM node:20-alpine AS builder
WORKDIR /app

# Install workspace dependencies (needs every workspace's package.json present).
COPY package.json package-lock.json ./
COPY apps/product/package.json apps/product/package.json
COPY apps/presentation/package.json apps/presentation/package.json
RUN npm ci

# Build the product frontend only.
COPY apps/product apps/product
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_USE_MSW=0
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_USE_MSW=$NEXT_PUBLIC_USE_MSW \
    NODE_ENV=production
RUN npm run build -w tg-platform-product

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/apps/product/package.json apps/product/package.json
COPY --from=builder /app/apps/presentation/package.json apps/presentation/package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/apps/product/.next apps/product/.next
COPY --from=builder /app/apps/product/public apps/product/public
COPY --from=builder /app/apps/product/next.config.ts apps/product/next.config.ts

EXPOSE 3000
WORKDIR /app/apps/product
CMD ["npx", "next", "start", "--port", "3000", "--hostname", "0.0.0.0"]
