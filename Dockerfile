FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d

# Create non-root user
RUN useradd -m -u 10001 appuser

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./main.py

# Default envs (override at run)
ENV HOST=0.0.0.0 \
    PORT=8080 \
    DEST_DIR=/data/uploads

# Create writeable mount point
RUN mkdir -p /data/uploads && chown -R appuser:appuser /data
USER appuser

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).getcode()==200 else sys.exit(1)"
