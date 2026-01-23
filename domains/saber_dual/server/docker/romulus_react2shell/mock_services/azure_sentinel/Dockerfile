FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir flask requests urllib3 pyyaml

COPY app.py /app/

EXPOSE 5000

# Disable SSL warnings for internal communication
ENV PYTHONWARNINGS="ignore:Unverified HTTPS request"

CMD ["python", "app.py"]
