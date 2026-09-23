FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY src ./src
ENV PORT=8088 ARTIFACTS_DIR=/artifacts
EXPOSE 8088
# Runs as root inside the container only because the identity's private key on the shared volume is root-owned.
CMD ["node", "src/server.js"]
