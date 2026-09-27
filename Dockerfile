FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/app

WORKDIR /app

COPY requirements.runtime.txt ./
RUN pip install --no-cache-dir -r requirements.runtime.txt \
    && useradd --create-home --uid 10001 app

COPY --chown=app:app app.py ./
COPY --chown=app:app meeting_to_action ./meeting_to_action

USER app
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
