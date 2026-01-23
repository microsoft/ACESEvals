FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir flask pyyaml pyjwt pyopenssl

COPY app.py /app/

EXPOSE 443

CMD ["python", "app.py"]
