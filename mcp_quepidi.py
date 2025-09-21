#!/usr/bin/env python3
import os, sys, re, textwrap, io
from typing import Any, Dict, List, Optional, Tuple

import httpx
import mcp.server.stdio as stdio
from mcp.server.fastmcp import FastMCP

OPENAPI_URL   = os.getenv("OPENAPI_URL")
BASE_URL      = os.getenv("NINJA_BASE_URL")
TIMEOUT_S     = float(os.getenv("NINJA_TIMEOUT", "20"))

BEARER        = os.getenv("NINJA_BEARER")
API_KEY_NAME  = os.getenv("NINJA_API_KEY_NAME")
API_KEY_VALUE = os.getenv("NINJA_API_KEY_VALUE")

ENABLE_RESP_VALIDATION = os.getenv("VALIDATE_RESPONSES", "0") == "1"
DEBUG_HTTP     = os.getenv("DEBUG_HTTP", "0") == "1"

HTTP_METHODS = {"get","post","put","delete","patch","head","options"}

def resolve_ref(spec: dict, node: dict) -> dict:
    if not isinstance(node, dict) or "$ref" not in node:
        return node
    ref = node["$ref"]
    # only support internal refs: "#/components/..."
    assert ref.startswith("#/")
    parts = ref[2:].split("/")
    cur = spec
    for p in parts:
        cur = cur[p]
    return cur


def deref_schema(spec: dict, schema: Optional[dict]) -> Optional[dict]:
    if not schema: return schema
    seen = set()
    cur = schema
    while isinstance(cur, dict) and "$ref" in cur:
        key = cur["$ref"]
        if key in seen: break
        seen.add(key)
        cur = resolve_ref(spec, cur)
    # minimal allOf merge (flat objects only)
    if isinstance(cur, dict) and "allOf" in cur:
        merged = {"type":"object","properties":{},"required":[]}
        for part in cur["allOf"]:
            part = deref_schema(spec, part) or {}
            merged["properties"].update(part.get("properties") or {})
            if "required" in part:
                merged["required"].extend(part["required"])
        return merged
    return cur


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
            return join_url(BASE_URL or "", url)
        return url
    return BASE_URL

def collect_params(path_item: Dict[str, Any], op: Dict[str, Any]) -> List[Dict[str, Any]]:
    params, seen = [], set()
    for p in (path_item.get("parameters") or []) + (op.get("parameters") or []):
        key = (p.get("name"), p.get("in"))
        if key in seen: continue
        seen.add(key); params.append(p)
    return params

def parse_request_body(op: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    rb = op.get("requestBody")
    if not rb: return None, None
    content = rb.get("content") or {}
    # Prefer JSON, then form types
    for ct in ("application/json","application/*+json","application/x-www-form-urlencoded","multipart/form-data"):
        if ct in content:
            return content[ct].get("schema"), ct
    # else first available
    for ct, desc in content.items():
        return (desc or {}).get("schema"), ct
    return None, None

def get_response_schema(op: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    responses = op.get("responses") or {}
    for code in ("200","201","202","204"):
        it = responses.get(code)
        if not it: continue
        content = it.get("content") or {}
        for ct in ("application/json","application/*+json"):
            if ct in content: return content[ct].get("schema")
        for _, desc in content.items():
            return (desc or {}).get("schema")
    return None

def validate_json(schema: Dict[str, Any], data: Any):
    import jsonschema
    jsonschema.validate(data, schema)

def schema_wrapper_hint(schema: Optional[Dict[str, Any]]) -> Optional[str]:
    """If schema is an object with a single required key (e.g. 'data'), hint/wrap."""
    if not schema or schema.get("type") != "object":
        return None
    required = schema.get("required") or []
    props = schema.get("properties") or {}
    if len(required) == 1 and required[0] in props and len(props) == 1:
        return required[0]
    return None

def body_help(schema: Optional[Dict[str, Any]], ct: Optional[str]) -> str:
    if not schema and not ct:
        return "No body."
    parts = []
    if ct: parts.append(f"Content-Type: {ct}")
    if schema:
        wrap = schema_wrapper_hint(schema)
        if wrap:
            parts.append(f"Body expects wrapper key '{wrap}'. You may pass `body={{...}}` and it will be auto-wrapped to `{{\"{wrap}\": body}}`.")
        else:
            parts.append("Body expects JSON object matching the operation's schema.")
    parts.append("Override content-type by passing `ct=\"...\"` if needed.")
    if ct == "application/x-www-form-urlencoded":
        parts.append("Use `form={...}` to send form fields.")
    if ct == "multipart/form-data":
        parts.append("Use `form={...}` and optionally `files={\"field\": \"/path/to/file\"}`.")
    return " ".join(parts)

def preview_for_debug(payload: Any, limit: int = 500) -> str:
    try:
        s = str(payload)
    except Exception:
        s = "<unrepr>"
    return (s[:limit] + ("..." if len(s) > limit else ""))

def build_tools_from_openapi(server: FastMCP, spec: Dict[str, Any], client: httpx.Client) -> int:
    paths: Dict[str, Any] = spec.get("paths") or {}
    print(f"[debug] spec version: {spec.get('openapi') or spec.get('swagger')}", file=sys.stderr)
    print(f"[debug] servers: {spec.get('servers')}", file=sys.stderr)
    print(f"[debug] paths count: {len(paths)}", file=sys.stderr)

    registered = 0
    if not paths:
        print("[warn] spec has no 'paths'", file=sys.stderr)

    for raw_path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        keys = list(path_item.keys())
        print(f"[debug] path {raw_path} keys: {keys}", file=sys.stderr)

        for method, op in path_item.items():
            mlow = method.lower()
            if mlow not in HTTP_METHODS or not isinstance(op, dict):
                continue

            op_id = op.get("operationId") or slugify(f"{mlow}_{raw_path}")
            name  = slugify(op_id)
            base  = pick_server(op, spec)
            if not base and not BASE_URL:
                print(f"[skip] {name}: no server/base URL", file=sys.stderr)
                continue

            params = collect_params(path_item, op)
            req_schema, req_ct = parse_request_body(op)
            resp_schema = get_response_schema(op) if ENABLE_RESP_VALIDATION else None

            summary = (op.get("summary") or op.get("description") or f"{mlow.upper()} {raw_path}").strip()
            doc = textwrap.dedent(f"""
            {summary}

            Parameters:
            - Path / Query / Header / Cookie: pass by name (e.g., id=123, page=1)
            - Body: pass `body={{...}}`. {body_help(req_schema, req_ct)}
            - You can also pass explicit `headers={{...}}` to add/override request headers.

            Security: {'Auth expected (per spec).' if (op.get('security') or spec.get('security')) else 'No auth required (per spec).'}
            """).strip()

            # Pre-scan path tokens
            path_tokens = re.findall(r"{([^}]+)}", raw_path)

            def make_tool(_name=name, _method=mlow.upper(), _raw_path=raw_path, _base=base,
                          _req_schema=req_schema, _req_ct=req_ct, _resp_schema=resp_schema, _doc=doc):
                @server.tool(name=_name)
                def _tool(**kwargs) -> Any:
                    """
                    Auto-generated from OpenAPI. Body via `body={...}`.
                    For forms: `form={...}`, for multipart also `files={{field: "/path/to/file"}}`.
                    """
                    url_base = _base or BASE_URL
                    if not url_base: raise RuntimeError("No base URL configured")

                    # headers override
                    extra_headers = kwargs.pop("headers", None)
                    # explicit content-type override
                    ct_override = kwargs.pop("ct", None)

                    # 1) Build path
                    built_path = _raw_path
                    used = set()
                    for token in path_tokens:
                        if token not in kwargs:
                            raise ValueError(f"Missing path param: {token}")
                        built_path = built_path.replace("{"+token+"}", str(kwargs[token]))
                        used.add(token)
                    url = join_url(url_base, built_path)

                    # 2) Extract body candidates
                    json_body = None
                    form_data = None
                    files_arg = None

                    if "body" in kwargs:
                        json_body = kwargs.pop("body")
                        used.add("body")

                    if "form" in kwargs:
                        form_data = kwargs.pop("form")
                        used.add("form")

                    if "files" in kwargs:
                        files_arg = kwargs.pop("files")
                        used.add("files")
                        # Convert {"field": "/path/to/file"} to httpx files format
                        if isinstance(files_arg, dict):
                            conv = {}
                            for k, v in files_arg.items():
                                if isinstance(v, (str, bytes, bytearray)):
                                    # path or raw bytes
                                    if isinstance(v, str) and os.path.exists(v):
                                        conv[k] = (os.path.basename(v), open(v, "rb"))
                                    else:
                                        if isinstance(v, str):
                                            v_bytes = v.encode("utf-8")
                                            conv[k] = (k, io.BytesIO(v_bytes))
                                        else:
                                            conv[k] = (k, io.BytesIO(v))
                                elif hasattr(v, "read"):
                                    conv[k] = (getattr(v, "name", k), v)
                                else:
                                    raise ValueError(f"Unsupported file value for key '{k}': {type(v)}")
                            files_arg = conv

                    # 3) Remaining kwargs → query params (and headers if named)
                    query = {}
                    for k, v in list(kwargs.items()):
                        if k in used: continue
                        # simple heuristic: allow "header__X_Name" to inject header X-Name
                        if k.startswith("header__"):
                            pass  # handled below
                        else:
                            query[k] = v

                    # Headers merge
                    headers = _default_headers()
                    if extra_headers and isinstance(extra_headers, dict):
                        headers.update(extra_headers)
                    # header__Foo_Bar → Foo-Bar
                    for k, v in kwargs.items():
                        if k.startswith("header__"):
                            hname = k[len("header__"):].replace("_", "-")
                            headers[hname] = v

                    # 4) Choose content type
                    chosen_ct = ct_override or _req_ct
                    # Schema-based auto-wrap: if schema requires single key (e.g. data), wrap plain body
                    wrapper_key = schema_wrapper_hint(_req_schema)
                    if wrapper_key and json_body is not None and isinstance(json_body, dict) and wrapper_key not in json_body:
                        json_body = {wrapper_key: json_body}

                    # 5) Prepare request args
                    req_kwargs: Dict[str, Any] = dict(params=query or None, headers=headers or None)
                    method = _method

                    if chosen_ct in (None, "application/json", "application/*+json"):
                        if json_body is not None:
                            req_kwargs["json"] = json_body
                    elif chosen_ct == "application/x-www-form-urlencoded":
                        if form_data is None and isinstance(json_body, dict):
                            # allow using body for convenience
                            form_data = json_body
                            json_body = None
                        if form_data is not None:
                            req_kwargs["data"] = form_data
                        if "json" in req_kwargs:
                            req_kwargs.pop("json", None)
                    elif chosen_ct == "multipart/form-data":
                        if form_data is None and isinstance(json_body, dict):
                            form_data = json_body
                            json_body = None
                        if form_data is not None:
                            req_kwargs["data"] = form_data
                        if files_arg is not None:
                            req_kwargs["files"] = files_arg
                        if "json" in req_kwargs:
                            req_kwargs.pop("json", None)
                    else:
                        # unknown/other content-type: send JSON if provided, else form
                        if json_body is not None:
                            req_kwargs["json"] = json_body
                        elif form_data is not None:
                            req_kwargs["data"] = form_data

                    # Set explicit Content-Type if user overrode
                    if ct_override:
                        req_kwargs.setdefault("headers", {})
                        req_kwargs["headers"]["Content-Type"] = ct_override

                    if DEBUG_HTTP:
                        print(f"[http] {method} {url}", file=sys.stderr)
                        print(f"[http] headers: {headers}", file=sys.stderr)
                        if "json" in req_kwargs:
                            print(f"[http] json: {preview_for_debug(req_kwargs['json'])}", file=sys.stderr)
                        if "data" in req_kwargs:
                            print(f"[http] form: {preview_for_debug(req_kwargs['data'])}", file=sys.stderr)
                        if "files" in req_kwargs:
                            print(f"[http] files: {list(req_kwargs['files'].keys())}", file=sys.stderr)

                    resp = client.request(method, url, **req_kwargs)
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
                        data = resp.json()
                    else:
                        data = {"content_type": ctype, "text": resp.text}

                    if _resp_schema is not None and ENABLE_RESP_VALIDATION:
                        try:
                            validate_json(_resp_schema, data)
                        except Exception as ve:
                            return {"_validation": str(ve), "data": data}

                    return data

                _tool.__doc__ = _doc
                return _tool

            print(f"[mcp] registering tool: {name} → {mlow.upper()} {raw_path}", file=sys.stderr)
            make_tool()
            registered += 1

    return registered

def main():
    if not OPENAPI_URL:
        print("ERROR: set OPENAPI_URL", file=sys.stderr); sys.exit(2)

    server = FastMCP("openapi-proxy")

    @server.tool()
    def ping(msg: str = "ok") -> Dict[str, str]:
        """Health check."""
        return {"pong": msg}

    client = httpx.Client(timeout=TIMEOUT_S)

    try:
        spec = client.get(OPENAPI_URL, headers=_default_headers()).json()
    except Exception as e:
        print(f"ERROR: failed to load OpenAPI from {OPENAPI_URL}: {e}", file=sys.stderr)
        sys.exit(3)

    n = build_tools_from_openapi(server, spec, client)
    print(f"[mcp] total registered: {n}", file=sys.stderr)
    server.run("stdio")

if __name__ == "__main__":
    main()
