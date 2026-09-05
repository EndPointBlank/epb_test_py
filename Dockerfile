# python:3.12-slim publishes multi-arch manifests (amd64 + arm64), matching
# the Graviton (arm64) staging host without pinning an arch-specific tag.
# Version matches the Python used in CI (.github/workflows).
FROM python:3.12-slim AS builder

WORKDIR /app

# requirements.txt installs the SDK via `git+https://...`, so pip needs git
# present to clone it. Isolated to the builder stage so it doesn't end up in
# the runtime image.
RUN apt-get update && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer cached separately from source so source edits don't
# invalidate the (slow, network-bound) install step.
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .

# Matches `start`'s default port; overridable at runtime the same way.
ENV PORT=3002
EXPOSE 3002

# `start` prefers .venv/bin/python when present and falls back to python3
# otherwise -- there's no .venv in the image, so it runs on the
# system-installed packages from the builder stage.
CMD ["./start"]
