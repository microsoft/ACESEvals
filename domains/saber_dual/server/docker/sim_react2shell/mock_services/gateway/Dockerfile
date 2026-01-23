FROM python:3.11-alpine

# Install networking tools and iptables
RUN apk add --no-cache \
    iptables \
    iproute2 \
    tcpdump \
    curl \
    bind-tools

# Install Python dependencies
RUN pip install --no-cache-dir flask pyyaml

WORKDIR /app

COPY entrypoint.sh /entrypoint.sh
COPY app.py /app/app.py

RUN chmod +x /entrypoint.sh

# Enable IP forwarding at runtime via entrypoint
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
