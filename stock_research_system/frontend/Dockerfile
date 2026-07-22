# FinQuest learner web app - Next.js standalone production server.
#
# `NEXT_PUBLIC_*` variables are baked into the client bundle at BUILD
# time (they must be passed as build args, not just runtime env vars).
# Every other configuration value (FINQUEST_API_INTERNAL_URL,
# FINQUEST_WEB_ORIGIN, AUTH_COOKIE_SECURE) is read at container start by
# server-only code (Route Handlers, middleware) and is safe to set at
# `docker run`/compose time instead.
#
# No secret is ever baked into this image - the only build args are the
# browser-safe, non-secret NEXT_PUBLIC_* values.

FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# `npm ci` is a deterministic install driven entirely by package-lock.json.
RUN npm ci

FROM node:20-slim AS builder
WORKDIR /app
ARG NEXT_PUBLIC_FINQUEST_API_BASE_URL
ARG NEXT_PUBLIC_APP_NAME=FinQuest
ENV NEXT_PUBLIC_FINQUEST_API_BASE_URL=$NEXT_PUBLIC_FINQUEST_API_BASE_URL \
    NEXT_PUBLIC_APP_NAME=$NEXT_PUBLIC_APP_NAME \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN groupadd --system finquest && useradd --system --create-home --gid finquest finquest

# The standalone output is a minimal server bundle with only the
# node_modules actually reachable from the build traced in - never the
# full source tree or devDependencies.
COPY --from=builder --chown=finquest:finquest /app/.next/standalone ./
COPY --from=builder --chown=finquest:finquest /app/.next/static ./.next/static
COPY --from=builder --chown=finquest:finquest /app/public ./public

USER finquest
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
