# AgentCore Runtime runs ARM64 containers that listen on port 8080
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    AGENT_OBSERVABILITY_ENABLED=true \
    OTEL_PYTHON_DISTRO=aws_distro \
    OTEL_PYTHON_CONFIGURATOR=aws_configurator

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY prompts/ ./prompts/
# tool schema is only needed for local/fixture modes; gateway mode lists tools over MCP

RUN useradd -m agent && chown -R agent /app
USER agent
EXPOSE 8080

# opentelemetry-instrument sends traces of every model and tool call to CloudWatch (AgentCore Observability)
CMD ["opentelemetry-instrument", "python", "main.py"]
