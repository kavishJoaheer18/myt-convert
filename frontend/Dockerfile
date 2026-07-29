FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install


FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# The browser never learns the backend's address — it calls /api on its own
# origin. But Next resolves rewrite destinations at build time, not on each
# request, so where /api points has to be fixed here. It is the compose service
# name, which is stable; override the arg if the backend is somewhere else.
ARG API_ORIGIN=http://api:8000
ENV API_ORIGIN=$API_ORIGIN
RUN npm run build


FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
