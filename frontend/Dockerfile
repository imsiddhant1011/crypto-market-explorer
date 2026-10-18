# React + Vite frontend for the Crypto Market Data Explorer.
#
# The dashboard is built once at image build time and then served as static
# files. The API URL is compiled into the bundle here, because browsers run the
# JavaScript (not the container), so it points at the host port of the backend.
FROM node:22-alpine

WORKDIR /app

# Install dependencies first so Docker can cache this layer.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

EXPOSE 5173

# Serve the freshly built files (no file watching, so the demo stays stable).
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"]
