FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy script
COPY seeder.py .

# Copy templates (values generated dynamically at runtime)
COPY seed_manifest.template.yaml .
COPY base_infrastructure.template.yaml .

CMD ["python", "seeder.py"]
