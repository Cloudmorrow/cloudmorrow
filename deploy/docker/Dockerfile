# syntax=docker/dockerfile:1
# The Cloudmorrow server as one container: what a hosted tenant runs, and a
# way to run it on your own hardware without the installer. Build from the repository root:
#
#   docker build -f deploy/docker/Dockerfile -t cloudmorrow .
#
# The version is the nearest git tag on an installed server; an image has no
# git, so it is given one at build time (`--build-arg VERSION=0.9.0`).

FROM python:3.12-slim AS build
ARG VERSION=0.0.0
# hatch-vcs reads this in place of a git tag.
ENV SETUPTOOLS_SCM_PRETEND_VERSION=$VERSION
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --quiet build \
 && python -m build --wheel --outdir /wheels .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    # Two volumes: the data, and the key that seals it. A copy of one
    # without the other opens nothing, which is the point of keeping
    # them apart. Both can be overridden, like every config key, with
    # CLOUDMORROW_* variables.
    CLOUDMORROW_DATA_DIR=/data \
    CLOUDMORROW_NOTES_DIR=/data/notes \
    CLOUDMORROW_KEY_FILE=/keys/cloudmorrow.key \
    CLOUDMORROW_HOST=0.0.0.0 \
    CLOUDMORROW_PORT=8787 \
    # A container is updated by replacing the image, not by pulling git
    # into it, so the API deploy is off.
    CLOUDMORROW_ALLOW_API_UPDATE=false \
    # The reverse proxy is another container, not the loopback, so uvicorn
    # must believe its X-Forwarded-Proto or every request behind TLS would
    # be refused as plain http.
    FORWARDED_ALLOW_IPS=*

RUN useradd --system --uid 1000 --home-dir /data --shell /usr/sbin/nologin cloudmorrow \
 && mkdir -p /data /keys /opt/cloudmorrow/dist \
 && chown -R cloudmorrow:cloudmorrow /data /keys

# The wheel is installed, and also kept: it is what /install.sh hands to
# the machines that install the client from this server.
COPY --from=build /wheels/*.whl /opt/cloudmorrow/dist/
RUN pip install --no-cache-dir "cloudmorrow[server,agent] @ file://$(ls /opt/cloudmorrow/dist/*.whl)"

COPY deploy/docker/entrypoint.sh /usr/local/bin/cloudmorrow-entrypoint
RUN chmod 755 /usr/local/bin/cloudmorrow-entrypoint

USER cloudmorrow
VOLUME ["/data", "/keys"]
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=4)"

ENTRYPOINT ["cloudmorrow-entrypoint"]
CMD ["cloudmorrow-server", "serve"]
