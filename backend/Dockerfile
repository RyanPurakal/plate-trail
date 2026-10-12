FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY platetrail ./platetrail
RUN pip install --no-cache-dir -e ".[dev]"
COPY tests ./tests

EXPOSE 8000
CMD ["uvicorn", "platetrail.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
