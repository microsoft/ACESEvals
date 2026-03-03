# CTI Realm base environment
# Extends base SABER sandbox with CTI analysis tools (no domain data COPYs)
FROM saber/sandbox:latest

# Switch to root to install domain-specific packages
USER root

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Azure CLI
RUN curl -sL https://aka.ms/InstallAzureCLIDeb | bash

# CTI-specific Python packages (requests already in base image)
RUN uv pip install --system --no-cache \
    azure-kusto-data \
    azure-kusto-ingest \
    azure-identity \
    pysigma \
    httpx \
    pyyaml \
    jsonschema
