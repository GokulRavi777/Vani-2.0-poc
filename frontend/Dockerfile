# ==========================================
# VANI 2.0 - Frontend Container (Multi-Stage)
# ==========================================

# Stage 1: Build the React TypeScript application
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Stage 2: Serve with lightweight NGINX
FROM nginx:alpine

# Copy built static files to NGINX root
COPY --from=build /app/dist /usr/share/nginx/html

# Copy custom NGINX configuration with SPA & /api/ reverse proxy
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
