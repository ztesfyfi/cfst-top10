FROM python:3.12-slim
ARG TARGETARCH
ARG CFST_VERSION=2.3.5
ARG SHA_AMD64=c4c8fc76b4e1bf2bdb5ced8b765956d82dda7bc4eb59df5c04053f0f7db98d90
ARG SHA_ARM64=0ac992fcf24d4684caed33620deb9b83ce82f32d2418dc1f90be490ce5900300
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CFST_DATA_DIR=/data CFST_ENGINE_DIR=/opt/cfst
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl tar tzdata && rm -rf /var/lib/apt/lists/*
RUN set -eux; case "$TARGETARCH" in amd64) arch=amd64; sha="$SHA_AMD64";; arm64) arch=arm64; sha="$SHA_ARM64";; *) exit 1;; esac; url="https://github.com/XIU2/CloudflareSpeedTest/releases/download/v${CFST_VERSION}/cfst_linux_${arch}.tar.gz"; curl -fL --retry 3 "$url" -o /tmp/cfst.tgz; echo "$sha  /tmp/cfst.tgz" | sha256sum -c -; mkdir -p /opt/cfst; tar -xzf /tmp/cfst.tgz -C /opt/cfst; bin="$(find /opt/cfst -type f \( -name cfst -o -name CloudflareST \) -print -quit)"; ipfile="$(find /opt/cfst -type f -name ip.txt -print -quit)"; test -n "$bin"; test -n "$ipfile"; install -m 0755 "$bin" /opt/cfst/cfst; install -m 0644 "$ipfile" /opt/cfst/ip.txt; rm /tmp/cfst.tgz
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY tests ./tests
RUN groupadd -r -g 10001 cfst && useradd -r -u 10001 -g cfst -d /data -M cfst && mkdir -p /data && chown -R cfst:cfst /data /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" || exit 1
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
