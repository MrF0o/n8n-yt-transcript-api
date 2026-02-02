FROM python:3.12-slim

WORKDIR /app

# Install system dependencies including ffmpeg for video/audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
# Note: Whisper will download models on first use (~150MB for base model)
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create directories for model cache and temp files
RUN mkdir -p /app/.cache /tmp/whisper

# Set environment variables for model caching
ENV WHISPER_CACHE_DIR=/app/.cache
ENV TORCH_HOME=/app/.cache
ENV HF_HOME=/app/.cache

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /tmp/whisper
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application with increased timeout for video processing
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "300"]
