FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY index.js ./
COPY lib ./lib

ENV CHAINCODE_SERVER_ADDRESS=0.0.0.0:9999
EXPOSE 9999
# The chaincode id is the installed package id, which bootstrap.sh writes to the shared volume.
CMD ["sh", "-c", "while [ ! -s /artifacts/anchor.ccid ]; do echo waiting for the chaincode package id; sleep 2; done; export CHAINCODE_ID=$(cat /artifacts/anchor.ccid); echo serving $CHAINCODE_ID; exec npx fabric-chaincode-node server --chaincode-address=$CHAINCODE_SERVER_ADDRESS --chaincode-id=$CHAINCODE_ID"]
