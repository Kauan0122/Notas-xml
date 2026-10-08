FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Sao_Paulo

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 notaxml \
    && mkdir /dados && chown notaxml /dados

WORKDIR /app
COPY pyproject.toml README.md ./
COPY notaxml ./notaxml
RUN pip install .

USER notaxml

# Configuração, certificado, banco e XMLs ficam todos aqui.
VOLUME /dados
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/saude', timeout=3).read() == b'notaxml' else 1)"

CMD ["notaxml", "-c", "/dados/config.toml", "web", "--host", "0.0.0.0", "--porta", "8000", "--sem-navegador"]
