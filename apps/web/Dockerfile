FROM node:22-alpine AS dependencies

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder

WORKDIR /app
ARG NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    CURATOR_API_URL=http://127.0.0.1:4173
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
# The Next build evaluates server pages. A tiny local API keeps that build
# deterministic and independent from the Compose network; at runtime the web
# container receives CURATOR_API_URL=http://api:8000 from compose.yaml.
RUN node scripts/build-api-mock.mjs & mock_pid=$!; npm run build; build_status=$?; kill $mock_pid; wait $mock_pid 2>/dev/null || true; exit $build_status

FROM node:22-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]

