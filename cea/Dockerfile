FROM node:22-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        gfortran \
        ninja-build \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY rocket/ceav3/source /opt/cea-source
RUN python3 -m venv /opt/cea-venv \
    && /opt/cea-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/cea-venv/bin/pip install --no-cache-dir /opt/cea-source

ENV CEA_PYTHON=/opt/cea-venv/bin/python \
    NODE_ENV=production

COPY lab/cea/package.json lab/cea/package-lock.json ./
RUN npm ci --include=dev --no-audit --no-fund

COPY lab/cea/ ./
RUN npm run build

EXPOSE 4173

CMD ["node", "dist/server/server.js"]
