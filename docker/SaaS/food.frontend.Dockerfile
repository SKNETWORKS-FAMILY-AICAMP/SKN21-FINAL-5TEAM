FROM node:20-alpine AS build

WORKDIR /app

COPY food/frontend/package.json food/frontend/package-lock.json* ./
RUN npm install

ARG PUBLIC_URL=/food
ARG REACT_APP_API_URL=/food
ENV PUBLIC_URL=${PUBLIC_URL}
ENV REACT_APP_API_URL=${REACT_APP_API_URL}

COPY food/frontend/ ./
RUN npm run build

FROM nginx:alpine

COPY docker/SaaS/spa.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80
