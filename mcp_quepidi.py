#!/usr/bin/env python3
import os, sys, re, textwrap
from typing import Any, Dict, List, Optional, Tuple

import httpx
import mcp.server.stdio as stdio
from mcp.server.fastmcp import FastMCP

# =========================
# Config via env
# =========================
OPENAPI_URL   = os.getenv("OPENAPI_URL")          # e.g. http://localhost:8081/api/openapi.json
BASE_URL      = os.getenv("NINJA_BASE_URL")       # fallback if spec.servers missing
TIMEOUT_S     = float(os.getenv("NINJA_TIMEOUT", "20"))

BEARER        = os.getenv("NINJA_BEARER")
API_KEY_NAME  = os.getenv("NINJA_API_KEY_NAME")
API_KEY_VALUE = os.getenv("NINJA_API_KEY_VALUE")

ENABLE_RESP_VALIDATION = os.getenv("VALIDATE_RESPONSES", "0") == "1"

HTTP_METHODS = {"get","post","put","delete","patch","head","options"}

# =========================
# Utilities
# =========================
def _default_headers() -> Dict[str, str]:
    h: Dict[str, str] = {}
    if BEARER: h["Authorization"] = f"Bearer {BEARER}"
    if API_KEY_NAME and API_KEY_VALUE: h[API_KEY_NAME] = API_KEY_VALUE
    return h

def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")

def join_url(base: str, path: str) -> str:
    if base.endswith("/"): base = base[:-1]
    if not path.startswith("/"): path = "/" + path
    return base + path

def pick_server(op: Dict[str, Any], spec: Dict[str, Any]) -> Optional[str]:
    servers = op.get("servers") or spec.get("servers") or []
    if servers:
        url = servers[0].get("url")
        if url and not url.startswith("http"):
            return join_url(BASE_URL, url) if BASE_URL else url
        return url
    return BASE_URL

# =========================
# Builder
# =========================
def build_tools_from_openapi(server: FastMCP, spec: Dict[str, Any], client: httpx.Client) -> int:
    paths: Dict[str, Any] = spec.get("paths") or {}
    print(f"[debug] spec version: {spec.get('openapi') or spec.get('swagger')}", file=sys.stderr)
    print(f"[debug] servers: {spec.get('servers')}", file=sys.stderr)
    print(f"[debug] paths count: {len(paths)}", file=sys.stderr)

    registered = 0

    if not paths:
        print("[warn] spec has no 'paths' — double-check OPENAPI_URL", file=sys.stderr)

    for raw_path, path_item in paths.items():
        if not isinstance(path_item, dict):
            print(f"[warn] path item not a dict for {raw_path}: {type(path_item)}", file=sys.stderr)
            continue

        keys = list(path_item.keys())
        print(f"[debug] path {raw_path} keys: {keys}", file=sys.stderr)

        any_methods = False
        for method, op in path_item.items():
            mlow = method.lower()
            if mlow not in HTTP_METHODS:
                # skip non-method keys like 'parameters', 'summary', etc.
                continue
            any_methods = True
            if not isinstance(op, dict):
                print(f"[warn] op not a dict for {mlow} {raw_path}: {type(op)}", file=sys.stderr)
                continue

            op_id = op.get("operationId") or slugify(f"{mlow}_{raw_path}")
            name  = slugify(op_id)
            base  = pick_server(op, spec)
            summary = (op.get("summary") or op.get("description") or f"{mlow.upper()} {raw_path}").strip()

            if not base and not BASE_URL:
                print(f"[skip] {name}: no server/base URL available", file=sys.stderr)
                continue

            print(f"[mcp] registering tool: {name} → {mlow.upper()} {raw_path}", file=sys.stderr)

            def make_tool(_name=name, _method=mlow.upper(), _raw_path=raw_path, _base=base, _summary=summary):
                @server.tool(name=_name)
                def _tool(**kwargs) -> Any:
                    """
                    Auto-generated from OpenAPI. For body JSON, pass `body={...}`.
                    Path variables are substituted by name if present in the path.
                    Other kwargs sent as query params.
                    """
                    url_base = _base or BASE_URL
                    if not url_base:
                        raise RuntimeError("No base URL configured")

                    # substitute simple path params if kwargs match
                    built_path = _raw_path
                    for k, v in list(kwargs.items()):
                        token = "{"+k+"}"
                        if token in built_path:
                            built_path = built_path.replace(token, str(v))
                            kwargs.pop(k, None)

                    # JSON body support if caller passes body=...
                    json_body = None
                    if "body" in kwargs:
                        json_body = kwargs.pop("body")

                    url = join_url(url_base, built_path)
                    headers = _default_headers()
                    resp = client.request(_method, url, params=kwargs or None,
                                          headers=headers or None, json=json_body)

                    try:
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        try:
                            detail = resp.json()
                        except Exception:
                            detail = resp.text
                        raise RuntimeError(f"HTTP {resp.status_code} {resp.request.method} {resp.request.url}: {detail}") from e

                    ctype = resp.headers.get("content-type","")
                    if ctype.startswith("application/json") or ctype.endswith("+json"):
                        return resp.json()
                    return {"content_type": ctype, "text": resp.text}
                _tool.__doc__ = _summary
                return _tool

            make_tool()
            registered += 1

        if not any_methods:
            print(f"[warn] no HTTP methods under path {raw_path} (keys were {keys})", file=sys.stderr)

    return registered

# =========================
# Main
# =========================
def main():
    if not OPENAPI_URL:
        print("ERROR: set OPENAPI_URL (e.g. http://localhost:8081/api/openapi.json)", file=sys.stderr)
        sys.exit(2)

    server = FastMCP("openapi-proxy")

    @server.tool()
    def ping(msg: str = "ok") -> Dict[str, str]:
        """Health check."""
        return {"pong": msg}

    client = httpx.Client(timeout=TIMEOUT_S)

    # fetch spec
    try:
        spec_resp = client.get(OPENAPI_URL, headers=_default_headers())
        spec_resp.raise_for_status()
        spec = spec_resp.json()
    except Exception as e:
        print(f"ERROR: failed to load OpenAPI from {OPENAPI_URL}: {e}", file=sys.stderr)
        sys.exit(3)

    n = build_tools_from_openapi(server, spec, client)
    print(f"[mcp] total registered: {n}", file=sys.stderr)

    # stdio loop (correct runner)
    # server.run(stdio.stdio_server())
    server.run("stdio")


if __name__ == "__main__":
    main()
