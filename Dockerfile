# mnemodex — optional container image.
#
# mnemodex itself has zero dependencies and does NOT require Docker to run
# (that's the whole point). This image is for teams that want the CLI + MCP
# server packaged for CI runners, Kubernetes jobs or a shared dev box.
#
#   docker build -t mnemodex .
#   docker run --rm -it -v "$PWD:/repo" -w /repo mnemodex init
#   docker run --rm -it -v "$PWD:/repo" -w /repo mnemodex index
#   docker run --rm -p 127.0.0.1:8766:8766 -v "$PWD:/repo" -w /repo mnemodex serve --transport sse

FROM python:3.12-slim

# no apt packages, no build tools — the stdlib is enough
WORKDIR /opt/mnemodex
COPY mnemodex/ mnemodex/
COPY pyproject.toml bin/ Makefile ./

# expose the CLI without a pip install so the image stays dependency-free:
ENV PYTHONPATH=/opt/mnemodex
ENTRYPOINT ["python", "-m", "mnemodex"]
CMD ["--help"]

# MCP SSE default port (mnemodex serve --transport sse)
EXPOSE 8766