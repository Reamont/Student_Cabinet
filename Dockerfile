FROM python:3.12.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then \
      PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r requirements.lock; \
    else \
      pip install --no-cache-dir -r requirements.lock; \
    fi
COPY . .
# Non-secret build-time value: collectstatic does not connect to production data.
RUN DJANGO_SECRET_KEY=static-build-only-not-a-runtime-secret python manage.py collectstatic --noinput \
    && useradd --create-home --uid 10001 campus \
    && mkdir -p /app/var \
    && chown -R campus:campus /app
USER campus
EXPOSE 8000
CMD ["gunicorn", "campus.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60"]
