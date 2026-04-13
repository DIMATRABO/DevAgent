FROM python:3.12-slim

# Install Node.js (required for Claude CLI) + git + gh CLI
RUN apt-get update && apt-get install -y curl git && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
    dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | \
    tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && apt-get install -y gh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Create non-root user (uid=1000 matches host ubuntu user so volume permissions align)
RUN useradd -m -u 1000 devagent

# Install Python dependencies
COPY telegram/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code (build context is DevAgent root)
COPY telegram/bot.py /app/bot.py
COPY core/ /app/core/
COPY agents/ /app/agents/
COPY mcp/ /app/mcp/

ENV PYTHONPATH=/app

WORKDIR /workspace

USER devagent

CMD ["python", "/app/bot.py"]
