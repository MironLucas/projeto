FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN SECRET_KEY=somente-para-o-build DEBUG=False python manage.py collectstatic --noinput

EXPOSE 8000
# Threads: um envio de vídeo grande (ou alguém assistindo) não trava o sistema para os outros.
CMD ["gunicorn", "projeto.wsgi:application", "--bind", "0.0.0.0:8000", "--worker-class", "gthread", "--workers", "3", "--threads", "8", "--timeout", "300"]
