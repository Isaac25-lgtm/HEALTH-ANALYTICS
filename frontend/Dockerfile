FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The browser uses the same-origin /api path, so no API hostname is baked into the bundle.
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
# BACKEND_INTERNAL_URL is read by the /api route at request time and must be provided by the
# runtime environment (Compose: http://api:8000; Render: the private service hostport). It is
# intentionally not set here and not needed at build time, so the image is environment-neutral
# and an unset value fails closed with a generic 500 instead of silently using a default.
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "run", "start"]
