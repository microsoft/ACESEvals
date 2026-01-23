FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir flask

COPY app.py /app/

EXPOSE 7071

CMD ["python", "app.py"]
