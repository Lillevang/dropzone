FROM python:3.14-slim@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151

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
