"""
SynAuth MCP Server — Biometric approval for AI agent actions.

Exposes SynAuth's Face ID approval workflow as MCP tools.
Any MCP-compatible agent can request human authorization for actions
(emails, purchases, bookings, contracts, data access, posts, system changes).

Configure in Claude settings or any MCP client:
    "mcpServers": {
        "synauth": {
            "command": "synauth-mcp",
            "env": {
                "SYNAUTH_API_KEY": "aa_..."
            }
        }
    }

Environment variables:
    SYNAUTH_URL     - Backend URL (default: https://synauth.fly.dev)
    SYNAUTH_API_KEY - Agent API key (required)
"""

import asyncio
import json
import os
import time
from typing import List

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


SYNAUTH_URL = os.environ.get("SYNAUTH_URL", "https://synauth.fly.dev").rstrip("/")
SYNAUTH_API_KEY = os.environ.get("SYNAUTH_API_KEY", "")

ACTION_TYPES = ["communication", "purchase", "scheduling", "legal", "data_access", "social", "system"]
RISK_LEVELS = ["low", "medium", "high", "critical"]


API_VERSION = "v1"


def _api(method: str, path: str, **kwargs) -> dict:
    """Make an authenticated request to the SynAuth backend."""
    headers = kwargs.pop("headers", {})
    headers["X-API-Key"] = SYNAUTH_API_KEY
    url = f"{SYNAUTH_URL}/api/{API_VERSION}{path}"
    resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.json()


server = Server("synauth")


@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available SynAuth tools."""
    return [
        Tool(
            name="request_approval",
            description="""Request human approval for an AI agent action via Face ID.

Submit any action (email, purchase, booking, contract, data access, social post, system change)
for biometric verification by the authorized human. Returns immediately with request ID and
initial status — the action may be auto-approved/denied by rules, or pending human review.

Action types: communication, purchase, scheduling, legal, data_access, social, system
Risk levels: low, medium, high, critical

Example: Request approval to send an email
  action_type: "communication"
  title: "Send quarterly report to john@company.com"
  risk_level: "low"

Example: Request approval for a $500 purchase
  action_type: "purchase"
  title: "Purchase cloud hosting credits"
  amount: 500.00
  risk_level: "medium"
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": ACTION_TYPES,
                        "description": "Category of the action",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short description shown to the approver",
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the action (optional)",
                    },
                    "risk_level": {
                        "type": "string",
                        "enum": RISK_LEVELS,
                        "default": "medium",
                        "description": "Risk classification (affects UI urgency and rule evaluation)",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Dollar amount, if applicable (e.g., purchases)",
                    },
                    "recipient": {
                        "type": "string",
                        "description": "Who receives the action (email address, merchant name, etc.)",
                    },
                    "reversible": {
                        "type": "boolean",
                        "default": True,
                        "description": "Whether the action can be undone",
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Arbitrary key-value pairs for audit trail",
                    },
                    "expires_in_seconds": {
                        "type": "integer",
                        "default": 300,
                        "description": "Seconds until the request auto-expires (default: 5 minutes)",
                    },
                    "callback_url": {
                        "type": "string",
                        "description": "HTTPS URL to receive webhook when approval status changes (optional)",
                    },
                },
                "required": ["action_type", "title"],
            },
        ),
        Tool(
            name="check_approval",
            description="""Check the status of an approval request.

Returns the current status (pending, approved, denied, expired) and full details
including timestamps, resolution method, and any deny reason.

Use this after request_approval to see if the human has responded.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "request_id": {
                        "type": "string",
                        "description": "The request ID returned by request_approval",
                    },
                },
                "required": ["request_id"],
            },
        ),
        Tool(
            name="wait_for_approval",
            description="""Wait for an approval request to be resolved.

Polls the backend until the request is approved, denied, or expired.
Returns the final status. Use this when you need to block until the human responds.

Default timeout is 120 seconds with 3-second polling intervals.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "request_id": {
                        "type": "string",
                        "description": "The request ID to wait on",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "default": 120,
                        "description": "Max seconds to wait (default: 120)",
                    },
                    "poll_interval": {
                        "type": "number",
                        "default": 3.0,
                        "description": "Seconds between status checks (default: 3)",
                    },
                },
                "required": ["request_id"],
            },
        ),
        Tool(
            name="get_approval_history",
            description="""Get history of resolved approval requests.

Returns past approved, denied, and expired requests. Useful for reviewing
what actions have been taken and their outcomes.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "Max number of results (default: 20)",
                    },
                    "action_type": {
                        "type": "string",
                        "enum": ACTION_TYPES,
                        "description": "Filter by action type (optional)",
                    },
                },
            },
        ),
        Tool(
            name="get_spending_summary",
            description="""Check your current spending against configured limits.

Returns all spending limits that apply to you (agent-specific and global limits),
with your current spend, remaining budget, and utilization percentage for each.

Use this BEFORE making purchases or other monetary actions to check if you have
budget remaining. This prevents hitting spending limit denials.

Each summary includes: limit_id, period (daily/weekly/monthly), limit amount,
spent amount, remaining amount, and utilization percentage.""",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="list_vault_services",
            description="""List available vault services (stored API credentials).

Shows which services have credentials stored in SynAuth's vault.
Each service has allowed hosts that restrict where credentials can be sent.
The agent never sees the actual credential values — only service names and metadata.

Use this to discover what API services are available before calling execute_api_call.""",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="execute_api_call",
            description="""Make an API call using a credential stored in SynAuth's vault.

This is the core structural enforcement tool: the agent provides the request details,
SynAuth requests biometric approval, then executes the call with the stored credential.
The agent never sees the raw API key or token.

Flow:
1. You provide: service name, HTTP method, URL, optional headers and body
2. SynAuth sends a push notification to the user's iPhone
3. User approves via Face ID
4. SynAuth injects the stored credential and makes the HTTP request
5. Response is returned to you

The URL must match one of the service's allowed hosts (security: prevents credential exfiltration).
Each approval is single-use — you cannot re-execute the same approved request.

Example: Call OpenAI API
  service_name: "openai"
  method: "POST"
  url: "https://api.openai.com/v1/chat/completions"
  headers: {"Content-Type": "application/json"}
  body: '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}'
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "Name of the vault service (use list_vault_services to see available)",
                    },
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                        "description": "HTTP method",
                    },
                    "url": {
                        "type": "string",
                        "description": "Full URL to call (host must be in service's allowed_hosts)",
                    },
                    "headers": {
                        "type": "object",
                        "description": "Additional headers (auth header is injected automatically)",
                    },
                    "body": {
                        "type": "string",
                        "description": "Request body (typically JSON string for POST/PUT/PATCH)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Human-readable description shown in the approval prompt",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "default": 120,
                        "description": "Max seconds to wait for approval (default: 120)",
                    },
                },
                "required": ["service_name", "method", "url"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> List[TextContent]:
    """Handle tool calls."""

    if not SYNAUTH_API_KEY:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": "SYNAUTH_API_KEY environment variable not set. "
                         "Configure it in your MCP server settings."
            }),
        )]

    try:
        if name == "request_approval":
            payload = {"action_type": arguments["action_type"], "title": arguments["title"]}
            for field in ["description", "risk_level", "amount", "recipient",
                          "reversible", "metadata", "expires_in_seconds",
                          "callback_url"]:
                if field in arguments:
                    payload[field] = arguments[field]

            result = _api("POST", "/actions", json=payload)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "check_approval":
            result = _api("GET", f"/actions/{arguments['request_id']}")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "wait_for_approval":
            request_id = arguments["request_id"]
            timeout = arguments.get("timeout_seconds", 120)
            interval = arguments.get("poll_interval", 3.0)

            start = time.time()
            while time.time() - start < timeout:
                result = _api("GET", f"/actions/{request_id}")
                if result.get("status") != "pending":
                    return [TextContent(type="text", text=json.dumps(result, indent=2))]
                await asyncio.sleep(interval)

            result = _api("GET", f"/actions/{request_id}")
            result["_note"] = "Timed out waiting — request may still be pending"
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_approval_history":
            params = {"limit": arguments.get("limit", 20)}
            if "action_type" in arguments:
                params["action_type"] = arguments["action_type"]
            result = _api("GET", "/actions", params=params)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_spending_summary":
            result = _api("GET", "/agent/spending-summary")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "list_vault_services":
            result = _api("GET", "/vault/services")
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "execute_api_call":
            service_name = arguments["service_name"]
            method = arguments["method"]
            url = arguments["url"]
            timeout = arguments.get("timeout_seconds", 120)

            payload = {
                "action_type": "data_access",
                "title": arguments.get("description", f"API call: {method} {url}"),
                "description": f"Service: {service_name} | {method} {url}",
                "risk_level": "medium",
                "metadata": {
                    "vault_execute": True,
                    "service_name": service_name,
                    "method": method,
                    "url": url,
                    "headers": arguments.get("headers", {}),
                    "body": arguments.get("body"),
                },
            }
            result = _api("POST", "/actions", json=payload)

            if result.get("status") == "denied":
                return [TextContent(type="text", text=json.dumps({
                    "error": "Request denied",
                    "details": result,
                }, indent=2))]

            request_id = result["id"]

            if result.get("status") == "pending":
                start = time.time()
                while time.time() - start < timeout:
                    status_result = _api("GET", f"/actions/{request_id}")
                    if status_result.get("status") != "pending":
                        result = status_result
                        break
                    await asyncio.sleep(3.0)
                else:
                    return [TextContent(type="text", text=json.dumps({
                        "error": "Approval timed out",
                        "request_id": request_id,
                        "status": "pending",
                    }, indent=2))]

            if result.get("status") != "approved":
                return [TextContent(type="text", text=json.dumps({
                    "error": f"Request {result.get('status', 'unknown')}",
                    "details": result,
                }, indent=2))]

            exec_result = _api("POST", f"/vault/execute/{request_id}")
            return [TextContent(type="text", text=json.dumps(exec_result, indent=2))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except requests.exceptions.ConnectionError:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Cannot connect to SynAuth backend at {SYNAUTH_URL}. "
                     "Is the server running?"
        }))]
    except requests.exceptions.HTTPError as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"SynAuth API error: {e.response.status_code} — {e.response.text}"
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def _run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    """Entry point for the synauth-mcp console script."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
