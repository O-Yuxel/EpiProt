FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*


COPY . .

RUN pip install --no-cache-dir --timeout=300 --retries=10 torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir --timeout=300 --retries=10 -e ".[dev]"

CMD ["pytest", "-v"]
