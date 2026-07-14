FROM python:3.12-slim

COPY repo/ /app/
COPY capabilities.json /etc/bench/capabilities.json
COPY crucible-semantic /usr/local/bin/crucible-semantic
RUN chmod 0444 /etc/bench/capabilities.json \
    && chmod 0555 /usr/local/bin/crucible-semantic
ENV BENCH_CAPABILITIES_MANIFEST=/etc/bench/capabilities.json
WORKDIR /app
