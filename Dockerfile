FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/
COPY frontend/ /frontend/
ENV PYTHONPATH=/app

WORKDIR /frontend
EXPOSE 8501
CMD streamlit run streamlit_app.py --server.port ${PORT:-8501} --server.address 0.0.0.0 --server.headless true