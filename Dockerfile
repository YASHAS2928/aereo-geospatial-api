FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1
WORKDIR /service
COPY pyproject.toml requirements.lock ./
COPY app ./app
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .
RUN python -c "import fiona, shapely, pyproj"
COPY alembic.ini ./
COPY migrations ./migrations
RUN useradd --create-home api && chown -R api:api /service
USER api
EXPOSE 8000
CMD ["sh", "-c", "python -m alembic upgrade head && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
