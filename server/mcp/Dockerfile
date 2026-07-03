FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mem0_mcp_bridge ./mem0_mcp_bridge

ENV HOST=0.0.0.0
ENV PORT=8765

CMD ["python", "-m", "mem0_mcp_bridge.server"]
