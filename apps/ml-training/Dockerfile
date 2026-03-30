FROM rayproject/ray:2.9.0-py310

# Switch to root to install system dependencies if needed
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Switch back to ray user
USER ray

# Explicitly install CPU-only PyTorch and DeepSpeed
# We uninstall existing torch if any to avoid version conflicts
RUN pip uninstall -y torch torchvision torchaudio && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir deepspeed transformers datasets accelerate

# Set up the application directory
WORKDIR /app
COPY --chown=ray:users train_cascade.py /app/
COPY --chown=ray:users deepspeed_config.json /app/

# Entrypoint is already handled by Ray, but we define the default command
CMD ["python", "/app/train_cascade.py"]
