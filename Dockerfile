# ==========================================
# Stage 1: Build the React Application
# ==========================================
FROM node:20-alpine AS builder

WORKDIR /app

# ติดตั้ง Dependencies
COPY package.json package-lock.json* ./
RUN npm install

# คัดลอกโค้ดและทำการ Build (Vite)
COPY . .
RUN npm run build

# ==========================================
# Stage 2: Serve with Nginx
# ==========================================
FROM nginx:alpine

# นำไฟล์ที่ Build เสร็จแล้วไปใส่ใน Nginx
COPY --from=builder /app/dist /usr/share/nginx/html

# คัดลอกไฟล์ Nginx Configuration เพื่อรองรับ React Router
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
