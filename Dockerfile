FROM python:3.11-slim

RUN useradd --create-home --uid 1000 app && mkdir -p /data/index && chown -R app /data
WORKDIR /app

COPY pyproject.toml requirements.txt ./
COPY clausecheck/ clausecheck/
COPY scripts/ scripts/
COPY data/*.csv data/
RUN pip install --no-cache-dir -e . -r requirements.txt sentence-transformers==6.2.0 \
    && chown -R app /app

USER app
ENV HOME=/home/app INDEX_DIR=/data/index SQLITE_PATH=/data/index/clausecheck.db
# the re-ranker is baked into the image so the first question does not wait for a download
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

EXPOSE 7860
CMD ["sh", "-c", "python scripts/bootstrap.py && uvicorn clausecheck.api.main:get_app --factory --host 0.0.0.0 --port 7860"]
