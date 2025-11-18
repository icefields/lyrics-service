FROM python:3.11-slim

# install system deps required by asyncpg and httpx
RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential libpq-dev gcc curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

# copy requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# copy app
COPY main.py ./

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

