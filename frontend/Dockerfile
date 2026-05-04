# syntax=docker/dockerfile:1.7
# PlugTrack frontend container.
#
# Stage 1 builds the SPA with Vite. Stage 2 serves the static bundle
# through nginx, which also reverse-proxies /api/* to the backend
# container on the docker bridge network.

FROM node:20-alpine AS builder

WORKDIR /app

# Install deps first so Docker can cache the layer when only source
# changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src

RUN npm run build


FROM nginx:alpine AS runtime

# Drop the stock site config so our SPA fallback / proxy block is the
# only one in /etc/nginx/conf.d.
RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
