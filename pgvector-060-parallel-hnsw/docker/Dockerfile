# pgvector built from a git tag on a fixed Postgres image, the same way
# pgvector's own Dockerfile does it (make OPTFLAGS=""), so 0.5.1 and 0.6.0
# differ only in the extension.
ARG PG_IMAGE=postgres:16.1-bookworm
FROM ${PG_IMAGE}
ARG PGVECTOR_TAG

RUN apt-get update && \
    apt-mark hold locales && \
    apt-get install -y --no-install-recommends build-essential ca-certificates git postgresql-server-dev-16 && \
    git clone --branch "${PGVECTOR_TAG}" --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector && \
    cd /tmp/pgvector && \
    make clean && \
    make OPTFLAGS="" && \
    make install && \
    rm -rf /tmp/pgvector && \
    apt-get remove -y build-essential git postgresql-server-dev-16 && \
    apt-get autoremove -y && \
    apt-mark unhold locales && \
    rm -rf /var/lib/apt/lists/*
