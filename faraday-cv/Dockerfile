# Public deployment: the browser tracks the magnet, this server only turns
# the resulting numbers into physics and figures -- no OpenCV, no ffmpeg.
# For the OpenCV-backed local/CLI pipeline, see README.md instead; that one
# is meant to run on your own machine, not in a container like this.
FROM python:3.12-slim

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY faradaycv/ faradaycv/
COPY static/ static/
COPY templates/ templates/
COPY wsgi.py .

ENV FARADAYCV_LOCAL_MODE=0
EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "60", "wsgi:app"]
