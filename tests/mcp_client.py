"""A minimal MCP client, just enough to drive this project's server.

The MCP surface is a second API over the same models and the same bearer tokens
as the REST routers (``docs/mcp-server-plan.md``), and it is the one an AI
assistant actually talks to -- see the demo linked from ``README.md``. It has no
coverage from the REST suite at all: those tests never touch ``/mcp/mcp``.

Written against the transport rather than an SDK on purpose. The whole point of
this suite is to exercise the deployed stack -- nginx, gunicorn,
django-mcp-server and a real MySQL -- so the fewer layers of our own between the
test and the wire, the better. It is also tiny: the server speaks streamable
HTTP JSON-RPC, and three methods cover everything these tests need.

Two transport details that are easy to get wrong and cost real debugging time:

* **Responses may be SSE-framed.** The server answers with either
  ``application/json`` or ``text/event-stream`` depending on the request; the
  latter wraps the payload in a ``data:`` line. :func:`_payload` handles both.
* **The session id arrives as a response header.** ``initialize`` returns
  ``Mcp-Session-Id``, and every later call must echo it back or the server
  treats the call as a fresh, uninitialized session.
"""
import json

import requests


class McpError(Exception):
    """The server rejected a call.

    Covers both JSON-RPC transport errors and tool-level errors (``isError``),
    because from a caller's point of view they mean the same thing: the query
    did not run. Querying an unpublished collection raises this.
    """


class McpClient:
    """One initialized MCP session against a deployed server."""

    def __init__(self, url, token, timeout=60):
        self.url = url
        self.timeout = timeout
        self._id = 0
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            # Both, because the server picks the framing per response.
            "Accept": "application/json, text/event-stream",
        })

    # -- transport ---------------------------------------------------------

    @staticmethod
    def _payload(response):
        """Unwrap a response body that may or may not be SSE-framed."""
        if "text/event-stream" in response.headers.get("Content-Type", ""):
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            raise McpError(f"SSE response carried no data line: {response.text[:200]}")
        return json.loads(response.text)

    def _rpc(self, method, params=None, notify=False):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._id += 1
            body["id"] = self._id

        response = self._session.post(self.url, json=body, timeout=self.timeout)

        # Carry the session across calls; without it the server sees each
        # request as a new, uninitialized session.
        if session_id := response.headers.get("Mcp-Session-Id"):
            self._session.headers["Mcp-Session-Id"] = session_id

        if notify:
            return None
        if response.status_code >= 400:
            raise McpError(f"{method} -> HTTP {response.status_code}: {response.text[:300]}")

        message = self._payload(response)
        if "error" in message:
            raise McpError(f"{method} -> {message['error']}")
        return message["result"]

    # -- protocol ----------------------------------------------------------

    def initialize(self):
        result = self._rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "quepid-api-tests", "version": "1"},
        })
        self._rpc("notifications/initialized", {}, notify=True)
        return result

    def tool_names(self):
        return [t["name"] for t in self._rpc("tools/list", {})["tools"]]

    def _call_tool(self, name, arguments):
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise McpError(f"{name} {arguments}: {result.get('content')}")

        content = result.get("content") or []
        if not content:
            # A tool that matched nothing answers with empty content rather
            # than an empty JSON array.
            return []
        text = content[0].get("text", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    # -- the two published tools -------------------------------------------

    def instructions(self):
        """The server-level prompt from ``quepid_mcp/instructions.py``."""
        return self._call_tool("get_server_instructions", {})

    def query(self, collection, pipeline=None):
        """Run a restricted MongoDB-style aggregation pipeline.

        Always returns a list, so callers can index and count without
        re-checking the empty case.
        """
        rows = self._call_tool("query_data_collections", {
            "collection": collection,
            "search_pipeline": pipeline or [],
        })
        if isinstance(rows, dict):
            return [rows]
        return rows if isinstance(rows, list) else []

    def close(self):
        self._session.close()
