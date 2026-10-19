FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY apps ./apps
COPY memory ./memory
COPY models ./models
COPY database ./database
COPY workers ./workers
RUN pip install --no-cache-dir --no-deps . && useradd --create-home memory
COPY alembic.ini ./
COPY config ./config
COPY prompts ./prompts
USER memory
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
