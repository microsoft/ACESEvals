FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir flask pyyaml requests

COPY app.py /app/
COPY waf_rules.yaml /app/

EXPOSE 8080

CMD ["python", "app.py"]
