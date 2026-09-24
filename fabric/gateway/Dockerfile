FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY src ./src
ENV PORT=8088 ARTIFACTS_DIR=/artifacts
EXPOSE 8088
# Unprivileged; fabric/scripts/bootstrap.sh hands this user (uid 1000) the signing identity on the shared volume.
USER node
CMD ["node", "src/server.js"]
