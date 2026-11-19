# AgentCore Runtime runs ARM64 containers. Build from the sample root:
#   docker buildx build --platform linux/arm64 -f runtime_server/Dockerfile -t sales-mcp .
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sales_tools.py .
COPY runtime_server/server.py runtime_server/server.py

RUN useradd --uid 10001 --no-create-home appuser
USER appuser

ENV MCP_HOST=0.0.0.0 MCP_PORT=8000
EXPOSE 8000
CMD ["python", "runtime_server/server.py"]
