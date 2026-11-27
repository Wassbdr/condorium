# docker build -t condorium . && docker run --rm -it condorium            -> offline replay
# docker run --rm -p 7860:7860 condorium panel ui                          -> web UI
# docker run --rm -e CONDORIUM_MODEL=... -e <PROVIDER>_API_KEY=... condorium panel eval "..."
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY agents ./agents
COPY fixtures/demo ./fixtures/demo
RUN pip install --no-cache-dir ".[ui]"
WORKDIR /work
ENV COLUMNS=120
EXPOSE 7860
CMD ["panel", "demo"]
