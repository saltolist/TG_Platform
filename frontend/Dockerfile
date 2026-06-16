# Build context = repository root (monorepo with npm workspaces).
FROM node:20-alpine AS builder
WORKDIR /app

# Install workspace dependencies (needs every workspace's package.json present).
COPY package.json package-lock.json ./
COPY frontends/product/package.json frontends/product/package.json
COPY frontends/presentation/package.json frontends/presentation/package.json
RUN npm ci

# Build the product frontend only.
COPY frontends/product frontends/product
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
COPY --from=builder /app/frontends/product/package.json frontends/product/package.json
COPY --from=builder /app/frontends/presentation/package.json frontends/presentation/package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/frontends/product/.next frontends/product/.next
COPY --from=builder /app/frontends/product/public frontends/product/public
COPY --from=builder /app/frontends/product/next.config.ts frontends/product/next.config.ts

EXPOSE 3000
WORKDIR /app/frontends/product
CMD ["npx", "next", "start", "--port", "3000", "--hostname", "0.0.0.0"]
