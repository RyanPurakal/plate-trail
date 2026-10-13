FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# g++ builds the C++ router (platetrail._fastroute); scikit-build-core fetches cmake and ninja itself.
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml CMakeLists.txt ./
COPY src ./src
COPY platetrail ./platetrail
RUN pip install --no-cache-dir -e ".[dev]"
COPY tests ./tests

EXPOSE 8000
CMD ["uvicorn", "platetrail.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
