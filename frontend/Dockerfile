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
# Server-side proxy target; never exposed to the browser.
ENV BACKEND_INTERNAL_URL=http://api:8000
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "run", "start"]
