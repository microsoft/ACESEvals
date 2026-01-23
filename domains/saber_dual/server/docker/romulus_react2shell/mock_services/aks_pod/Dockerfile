FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir flask requests pyyaml

COPY app.py /app/

EXPOSE 8080

CMD ["python", "app.py"]
