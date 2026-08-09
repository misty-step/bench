"""Generate the frozen Mint reverse gateway and task Compose topology."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harness_census_common import (
    BUN_VERSION,
    CARGO_VERSION,
    GO_IMAGE,
    GO_VERSION,
    NODE_IMAGE,
    RUST_IMAGE,
    RUST_VERSION,
)

MINT_DEFAULT_BASE_URL = "http://mint.tail5f5eb4.ts.net:4949/proxy/https/openrouter.ai/api/v1"
MINT_INTERNAL_BASE_URL = "http://mint-gateway:4949/proxy/https/openrouter.ai/api/v1"
MINT_UPSTREAM_HOST = "mint.tail5f5eb4.ts.net"
MINT_UPSTREAM_PORT = 4949
MINT_API_PATH = "/proxy/https/openrouter.ai/api/v1"
GATEWAY_UID = 10001
GATEWAY_GID = 10001


def gateway_source() -> str:
    return r'''"use strict";

import http from "node:http";

const API_PATH = "/proxy/https/openrouter.ai/api/v1";
const UPSTREAM_HOST = "mint.tail5f5eb4.ts.net";
const UPSTREAM_PORT = 4949;
const LISTEN_PORT = 4949;
const CONTROL = /[\u0000-\u001f\u007f]/;
const ENCODED_UNSAFE = /%(?:2e|2f|5c|0[0-9a-f]|1[0-9a-f]|7f)/i;
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function reject(response, status, message) {
  response.writeHead(status, { "content-type": "text/plain; charset=utf-8", connection: "close" });
  response.end(`${message}\n`);
}

function requestPath(raw) {
  if (!raw || CONTROL.test(raw) || ENCODED_UNSAFE.test(raw) || raw.includes("\\") || raw.includes("#") || /^[a-z][a-z0-9+.-]*:/i.test(raw) || raw.startsWith("//")) {
    return null;
  }
  const query = raw.indexOf("?");
  const path = query < 0 ? raw : raw.slice(0, query);
  if (!path.startsWith("/") || path.includes("//") || path.split("/").some(segment => segment === "." || segment === "..")) {
    return null;
  }
  if (path.includes("%")) {
    try {
      if (decodeURIComponent(path) !== path) return null;
    } catch {
      return null;
    }
  }
  if (path !== API_PATH && !path.startsWith(`${API_PATH}/`)) return null;
  return query < 0 ? path : `${path}${raw.slice(query)}`;
}

function hasUpgrade(request) {
  const connection = request.headers.connection;
  return request.headers.upgrade !== undefined || (typeof connection === "string" && connection.split(",").some(value => value.trim().toLowerCase() === "upgrade"));
}

const server = http.createServer((request, response) => {
  if (hasUpgrade(request)) {
    reject(response, 400, "upgrade not allowed");
    return;
  }
  if (request.method !== "GET" && request.method !== "POST") {
    reject(response, 405, "method not allowed");
    return;
  }
  const path = requestPath(request.url);
  if (path === null) {
    reject(response, 404, "destination not allowed");
    return;
  }

  const headers = {};
  for (const [name, value] of Object.entries(request.headers)) {
    if (name !== "host" && !HOP_BY_HOP.has(name)) headers[name] = value;
  }
  headers.host = `${UPSTREAM_HOST}:${UPSTREAM_PORT}`;
  const upstream = http.request({
    hostname: UPSTREAM_HOST,
    port: UPSTREAM_PORT,
    method: request.method,
    path,
    headers,
  }, (upstreamResponse) => {
    const responseHeaders = {};
    for (const [name, value] of Object.entries(upstreamResponse.headers)) {
      if (!HOP_BY_HOP.has(name)) responseHeaders[name] = value;
    }
    response.writeHead(upstreamResponse.statusCode || 502, responseHeaders);
    upstreamResponse.pipe(response);
  });
  upstream.once("error", () => {
    if (!response.headersSent) reject(response, 502, "upstream unavailable");
    else response.destroy();
  });
  request.pipe(upstream);
});

server.on("connect", (_request, socket) => {
  socket.end("HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n");
});

server.on("upgrade", (_request, socket) => {
  socket.end("HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n");
});

server.listen(LISTEN_PORT, "0.0.0.0");
'''


def gateway_dockerfile() -> str:
    return f'''FROM {NODE_IMAGE}
RUN groupadd --system --gid {GATEWAY_GID} mintgateway \\
 && useradd --system --uid {GATEWAY_UID} --gid {GATEWAY_GID} --home-dir /nonexistent --no-create-home mintgateway
WORKDIR /app
COPY mint-gateway.mjs /app/mint-gateway.mjs
RUN chown {GATEWAY_UID}:{GATEWAY_GID} /app/mint-gateway.mjs \\
 && chmod 0555 /app/mint-gateway.mjs
USER {GATEWAY_UID}:{GATEWAY_GID}
ENTRYPOINT ["node", "/app/mint-gateway.mjs"]
'''


def compose_yaml(*, allow_user_namespaces: bool = False) -> str:
    sandbox_profile = "    security_opt:\n      - seccomp=unconfined\n" if allow_user_namespaces else ""
    return '''services:
  main:
    build:
      context: .
      dockerfile: Dockerfile
    depends_on:
      mint-gateway:
        condition: service_healthy
    networks:
      - internal
''' + sandbox_profile + '''  mint-gateway:
    build:
      context: .
      dockerfile: mint-gateway.Dockerfile
    read_only: true
    user: "10001:10001"
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:4949/').then(r=>process.exit(r.status===404?0:1)).catch(()=>process.exit(1))"]
      interval: 1s
      timeout: 2s
      retries: 15
      start_period: 1s
    networks:
      - internal
      - egress
networks:
  internal:
    internal: true
  egress: {}
'''


def validate_gateway_contract() -> None:
    source = gateway_source()
    required_source = (
        'const API_PATH = "/proxy/https/openrouter.ai/api/v1";',
        'const UPSTREAM_HOST = "mint.tail5f5eb4.ts.net";',
        'const CONTROL = /[\\u0000-\\u001f\\u007f]/;',
        'const ENCODED_UNSAFE = /%(?:2e|2f|5c|0[0-9a-f]|1[0-9a-f]|7f)/i;',
        'decodeURIComponent(path)',
        'path.split("/").some(segment => segment === "." || segment === "..")',
        'server.on("connect"',
        'server.on("upgrade"',
        'request.headers.upgrade !== undefined',
        'request.method !== "GET" && request.method !== "POST"',
        'raw.startsWith("//")',
        'server.listen(LISTEN_PORT, "0.0.0.0")',
    )
    if any(token not in source for token in required_source):
        raise RuntimeError("Mint gateway source contract is incomplete")
    if any(secret in source for secret in ("OPENROUTER_API_KEY", "MINT_API_KEY", "__mint.")):
        raise RuntimeError("Mint gateway source must not contain a secret")
    dockerfile = gateway_dockerfile()
    if f"FROM {NODE_IMAGE}\n" not in dockerfile or "COPY mint-gateway.mjs /app/mint-gateway.mjs" not in dockerfile:
        raise RuntimeError("Mint gateway image contract is incomplete")
    compose = compose_yaml()
    prime_compose = compose_yaml(allow_user_namespaces=True)
    manifest_path = Path(__file__).resolve().parents[1] / "benchmarks" / "harness-census-v0" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_gateway = manifest.get("gateway")
    manifest_toolchains = manifest.get("toolchains")
    expected_gateway = {
        "generator": "scripts/harness_census_gateway.py",
        "default_base_url": MINT_DEFAULT_BASE_URL,
        "internal_base_url": MINT_INTERNAL_BASE_URL,
        "upstream_host": MINT_UPSTREAM_HOST,
        "upstream_port": MINT_UPSTREAM_PORT,
        "api_path": MINT_API_PATH,
        "node_image": NODE_IMAGE,
    }
    expected_toolchains = {
        "go": {"version": GO_VERSION, "image": GO_IMAGE, "mode": "pinned-runtime-offline"},
        "rust": {"rustc": RUST_VERSION, "cargo": CARGO_VERSION, "image": RUST_IMAGE, "mode": "pinned-runtime-offline"},
        "bun": {"version": BUN_VERSION, "mode": "pinned-runtime-offline"},
    }
    if manifest_gateway != expected_gateway or manifest_toolchains != expected_toolchains:
        raise RuntimeError("Mint gateway or toolchain manifest identity is stale")
    if "main:\n" not in compose or "mint-gateway:\n" not in compose:
        raise RuntimeError("Compose topology is missing required services")
    if "    depends_on:\n      mint-gateway:\n        condition: service_healthy" not in compose or "    networks:\n      - internal\n  mint-gateway:" not in compose:
        raise RuntimeError("Compose main service must wait for the gateway on the internal network")
    if "      - internal\n      - egress\nnetworks:" not in compose:
        raise RuntimeError("Compose gateway must use internal and egress networks")
    for marker in ("dockerfile: Dockerfile", "dockerfile: mint-gateway.Dockerfile", "healthcheck:"):
        if marker not in compose:
            raise RuntimeError(f"Compose build contract is incomplete: {marker}")
    for marker in ("read_only: true", 'user: "10001:10001"', "- ALL", "no-new-privileges:true", "internal: true"):
        if marker not in compose:
            raise RuntimeError(f"Compose gateway hardening is incomplete: {marker}")
    if "seccomp=unconfined" in compose or prime_compose.count("      - seccomp=unconfined") != 1:
        raise RuntimeError("Prime Compose sandbox profile must permit only its inner user namespace")
    expected_paths = {
        "environment/mint-gateway.mjs",
        "environment/mint-gateway.Dockerfile",
        "environment/docker-compose.yaml",
    }
    if set(gateway_assets()) != expected_paths:
        raise RuntimeError("Mint gateway asset paths do not match Harbor's environment contract")


def gateway_assets(*, allow_user_namespaces: bool = False) -> dict[str, bytes]:
    return {
        "environment/mint-gateway.mjs": gateway_source().encode("utf-8"),
        "environment/mint-gateway.Dockerfile": gateway_dockerfile().encode("utf-8"),
        "environment/docker-compose.yaml": compose_yaml(allow_user_namespaces=allow_user_namespaces).encode("utf-8"),
    }


def gateway_identity(*, allow_user_namespaces: bool = False) -> dict[str, str]:
    assets = gateway_assets(allow_user_namespaces=allow_user_namespaces)
    return {
        "gateway_digest": hashlib.sha256(assets["environment/mint-gateway.mjs"]).hexdigest(),
        "gateway_dockerfile_digest": hashlib.sha256(assets["environment/mint-gateway.Dockerfile"]).hexdigest(),
        "compose_digest": hashlib.sha256(assets["environment/docker-compose.yaml"]).hexdigest(),
    }


def write_gateway_assets(task_dir: Path, *, allow_user_namespaces: bool = False) -> dict[str, str]:
    assets = gateway_assets(allow_user_namespaces=allow_user_namespaces)
    for relative, value in assets.items():
        path = task_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    observed = {
        relative: hashlib.sha256((task_dir / relative).read_bytes()).hexdigest()
        for relative in assets
    }
    expected = {relative: hashlib.sha256(value).hexdigest() for relative, value in assets.items()}
    if observed != expected:
        raise RuntimeError("Mint gateway assets changed while staging")
    return gateway_identity(allow_user_namespaces=allow_user_namespaces)
