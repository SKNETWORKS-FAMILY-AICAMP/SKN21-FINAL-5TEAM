FROM node:20-alpine AS build

WORKDIR /app

COPY bilyeo/frontend/package.json bilyeo/frontend/package-lock.json* ./
RUN npm install

ARG VITE_BASE_PATH=/bilyeo/
ARG VITE_API_BASE=/bilyeo/api
ENV VITE_BASE_PATH=${VITE_BASE_PATH}
ENV VITE_API_BASE=${VITE_API_BASE}

COPY bilyeo/frontend/ ./
RUN npm run build

FROM nginx:alpine

COPY docker/SaaS/spa.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
