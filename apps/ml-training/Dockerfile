FROM python:3.10-slim

# Install necessary system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch for CPU explicitly first
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install DeepSpeed, Ray, and Transformers
RUN pip install --no-cache-dir deepspeed "ray[default]" transformers

# Copy the orchestration script and deepspeed config into the container
WORKDIR /app
COPY train_cascade.py /app/
COPY deepspeed_config.json /app/

# Command is typically overridden by KubeRay/RayJob, but provide a default
CMD ["python", "/app/train_cascade.py"]
