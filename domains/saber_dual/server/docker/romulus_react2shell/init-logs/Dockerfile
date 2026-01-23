FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy script
COPY activity_generator.py .

CMD ["python", "activity_generator.py", "--output", "/output", "--hours", "48"]
