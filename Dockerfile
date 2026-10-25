FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    AKKORD_OUTPUT_DIR=/tmp/akkord_outputs

WORKDIR /app

# Install DejaVu TrueType fonts so ReportLab renders Unicode (Cyrillic, French, symbols) cleanly
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY akkord/ ./akkord/

EXPOSE 8080

CMD ["uvicorn", "akkord.server:app", "--host", "0.0.0.0", "--port", "8080"]
