# Local (Compose): no build args; the app calls localhost:10450 and localhost:10401.
# Pilot (one origin behind CloudFront, ADR 0009):
#   docker build --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth -t <registry>/smart-tutor/web:<sha> web
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL
ARG VITE_KEYCLOAK_URL
ARG VITE_KEYCLOAK_REALM
ARG VITE_KEYCLOAK_CLIENT_ID
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
