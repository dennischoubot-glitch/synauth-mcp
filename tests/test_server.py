"""Tests for the SynAuth MCP server.

Mocks all HTTP calls to the SynAuth backend — no real backend needed.
Tests the tool handlers via call_tool() directly.
"""

import asyncio
import json
import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# Patch env vars BEFORE importing the module (module-level globals read at import time)
@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("SYNAUTH_API_KEY", "aa_test_key")
    monkeypatch.setenv("SYNAUTH_URL", "https://test.synauth.dev")


# We need to reload the module after env patching for module-level vars
@pytest.fixture(autouse=True)
def _reload_server(monkeypatch, _patch_env):
    """Reload server module so module-level env vars pick up test values."""
    monkeypatch.setattr("synauth_mcp.server.SYNAUTH_API_KEY", "aa_test_key")
    monkeypatch.setattr("synauth_mcp.server.SYNAUTH_URL", "https://test.synauth.dev")


from synauth_mcp.server import call_tool, list_tools, _api, server


def _mock_response(status_code=200, json_data=None, text=""):
    """Create a mock requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 400
    resp.text = text or (str(json_data) if json_data else "")
    resp.json.return_value = json_data or {}
    resp.raise_for_status.side_effect = (
        None if status_code < 400
        else requests.exceptions.HTTPError(response=resp)
    )
    return resp


def _parse_result(result):
    """Extract and parse JSON from tool result TextContent list."""
    assert len(result) == 1
    return json.loads(result[0].text)


# --- list_tools ---


class TestListTools:
    @pytest.mark.asyncio
    async def test_returns_seven_tools(self):
        tools = await list_tools()
        assert len(tools) == 7
        names = {t.name for t in tools}
        assert names == {
            "request_approval", "check_approval", "wait_for_approval",
            "get_approval_history", "get_spending_summary",
            "list_vault_services", "execute_api_call",
        }

    @pytest.mark.asyncio
    async def test_request_approval_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "request_approval")
        schema = tool.inputSchema
        assert "action_type" in schema["properties"]
        assert "title" in schema["properties"]
        assert schema["required"] == ["action_type", "title"]

    @pytest.mark.asyncio
    async def test_execute_api_call_schema(self):
        tools = await list_tools()
        tool = next(t for t in tools if t.name == "execute_api_call")
        assert set(tool.inputSchema["required"]) == {"service_name", "method", "url"}


# --- Missing API key ---


class TestMissingApiKey:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_api_key(self, monkeypatch):
        monkeypatch.setattr("synauth_mcp.server.SYNAUTH_API_KEY", "")
        result = await call_tool("request_approval", {
            "action_type": "communication", "title": "Test"
        })
        data = _parse_result(result)
        assert "error" in data
        assert "SYNAUTH_API_KEY" in data["error"]


# --- request_approval ---


class TestRequestApproval:
    @pytest.mark.asyncio
    async def test_minimal_request(self):
        resp = _mock_response(200, json_data={"id": "req-1", "status": "pending"})
        with patch("synauth_mcp.server.requests.request", return_value=resp) as mock_req:
            result = await call_tool("request_approval", {
                "action_type": "communication",
                "title": "Send email",
            })
        data = _parse_result(result)
        assert data["id"] == "req-1"
        # Verify payload
        call_kwargs = mock_req.call_args[1]
        payload = call_kwargs["json"]
        assert payload["action_type"] == "communication"
        assert payload["title"] == "Send email"

    @pytest.mark.asyncio
    async def test_full_request_with_optional_fields(self):
        resp = _mock_response(200, json_data={"id": "req-2", "status": "pending"})
        with patch("synauth_mcp.server.requests.request", return_value=resp) as mock_req:
            result = await call_tool("request_approval", {
                "action_type": "purchase",
                "title": "Buy hosting",
                "description": "Cloud credits",
                "risk_level": "high",
                "amount": 500.0,
                "recipient": "AWS",
                "reversible": False,
                "metadata": {"invoice": "INV-001"},
                "expires_in_seconds": 60,
                "callback_url": "https://example.com/hook",
            })
        payload = mock_req.call_args[1]["json"]
        assert payload["amount"] == 500.0
        assert payload["callback_url"] == "https://example.com/hook"


# --- check_approval ---


class TestCheckApproval:
    @pytest.mark.asyncio
    async def test_returns_status(self):
        resp = _mock_response(200, json_data={"id": "req-1", "status": "approved"})
        with patch("synauth_mcp.server.requests.request", return_value=resp):
            result = await call_tool("check_approval", {"request_id": "req-1"})
        data = _parse_result(result)
        assert data["status"] == "approved"


# --- wait_for_approval ---


class TestWaitForApproval:
    @pytest.mark.asyncio
    async def test_returns_immediately_if_resolved(self):
        resp = _mock_response(200, json_data={"id": "req-1", "status": "approved"})
        with patch("synauth_mcp.server.requests.request", return_value=resp):
            result = await call_tool("wait_for_approval", {"request_id": "req-1"})
        data = _parse_result(result)
        assert data["status"] == "approved"

    @pytest.mark.asyncio
    async def test_polls_until_resolved(self):
        pending = _mock_response(200, json_data={"id": "req-1", "status": "pending"})
        approved = _mock_response(200, json_data={"id": "req-1", "status": "approved"})
        with patch("synauth_mcp.server.requests.request", side_effect=[pending, approved]):
            with patch("asyncio.sleep", return_value=None):
                result = await call_tool("wait_for_approval", {
                    "request_id": "req-1", "timeout_seconds": 10,
                })
        data = _parse_result(result)
        assert data["status"] == "approved"

    @pytest.mark.asyncio
    async def test_timeout_adds_note(self):
        """After timeout, returns final status with _note field."""
        pending = _mock_response(200, json_data={"id": "req-1", "status": "pending"})
        final = _mock_response(200, json_data={"id": "req-1", "status": "pending"})

        call_count = [0]

        def mock_time():
            call_count[0] += 1
            if call_count[0] <= 1:
                return 0.0
            return 999.0

        with patch("synauth_mcp.server.requests.request", side_effect=[final]):
            with patch("synauth_mcp.server.time.time", side_effect=mock_time):
                with patch("asyncio.sleep", return_value=None):
                    result = await call_tool("wait_for_approval", {
                        "request_id": "req-1", "timeout_seconds": 5,
                    })
        data = _parse_result(result)
        assert "_note" in data
        assert "Timed out" in data["_note"]


# --- get_approval_history ---


class TestGetApprovalHistory:
    @pytest.mark.asyncio
    async def test_default_params(self):
        resp = _mock_response(200, json_data={"actions": []})
        with patch("synauth_mcp.server.requests.request", return_value=resp) as mock_req:
            result = await call_tool("get_approval_history", {})
        data = _parse_result(result)
        assert "actions" in data
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["params"]["limit"] == 20

    @pytest.mark.asyncio
    async def test_with_action_type_filter(self):
        resp = _mock_response(200, json_data={"actions": []})
        with patch("synauth_mcp.server.requests.request", return_value=resp) as mock_req:
            await call_tool("get_approval_history", {
                "limit": 5, "action_type": "purchase",
            })
        params = mock_req.call_args[1]["params"]
        assert params["action_type"] == "purchase"
        assert params["limit"] == 5


# --- get_spending_summary ---


class TestGetSpendingSummary:
    @pytest.mark.asyncio
    async def test_returns_summaries(self):
        resp = _mock_response(200, json_data={"agent_id": "a-1", "summaries": []})
        with patch("synauth_mcp.server.requests.request", return_value=resp):
            result = await call_tool("get_spending_summary", {})
        data = _parse_result(result)
        assert data["agent_id"] == "a-1"


# --- list_vault_services ---


class TestListVaultServices:
    @pytest.mark.asyncio
    async def test_returns_services(self):
        resp = _mock_response(200, json_data={
            "services": [{"service_name": "openai", "auth_type": "bearer"}]
        })
        with patch("synauth_mcp.server.requests.request", return_value=resp):
            result = await call_tool("list_vault_services", {})
        data = _parse_result(result)
        assert len(data["services"]) == 1
        assert data["services"][0]["service_name"] == "openai"


# --- execute_api_call ---


class TestExecuteApiCall:
    @pytest.mark.asyncio
    async def test_happy_path_auto_approved(self):
        """Action auto-approved → vault execute → returns result."""
        create_resp = _mock_response(200, json_data={"id": "req-1", "status": "approved"})
        exec_resp = _mock_response(200, json_data={"status_code": 200, "body": '{"ok":true}'})
        with patch("synauth_mcp.server.requests.request",
                    side_effect=[create_resp, exec_resp]):
            result = await call_tool("execute_api_call", {
                "service_name": "openai",
                "method": "POST",
                "url": "https://api.openai.com/v1/chat",
            })
        data = _parse_result(result)
        assert data["status_code"] == 200

    @pytest.mark.asyncio
    async def test_auto_denied(self):
        resp = _mock_response(200, json_data={"id": "req-1", "status": "denied"})
        with patch("synauth_mcp.server.requests.request", return_value=resp):
            result = await call_tool("execute_api_call", {
                "service_name": "openai", "method": "GET", "url": "https://api.openai.com/",
            })
        data = _parse_result(result)
        assert "error" in data
        assert "denied" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_pending_then_approved(self):
        create_resp = _mock_response(200, json_data={"id": "req-1", "status": "pending"})
        poll_approved = _mock_response(200, json_data={"id": "req-1", "status": "approved"})
        exec_resp = _mock_response(200, json_data={"status_code": 200})
        with patch("synauth_mcp.server.requests.request",
                    side_effect=[create_resp, poll_approved, exec_resp]):
            with patch("asyncio.sleep", return_value=None):
                result = await call_tool("execute_api_call", {
                    "service_name": "openai", "method": "POST",
                    "url": "https://api.openai.com/v1/chat",
                })
        data = _parse_result(result)
        assert data["status_code"] == 200

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        """Polling timeout → returns clear timeout error."""
        create_resp = _mock_response(200, json_data={"id": "req-1", "status": "pending"})
        poll_pending = _mock_response(200, json_data={"id": "req-1", "status": "pending"})

        call_count = [0]

        def mock_time():
            call_count[0] += 1
            if call_count[0] <= 2:
                return 0.0
            return 999.0

        with patch("synauth_mcp.server.requests.request",
                    side_effect=[create_resp, poll_pending]):
            with patch("synauth_mcp.server.time.time", side_effect=mock_time):
                with patch("asyncio.sleep", return_value=None):
                    result = await call_tool("execute_api_call", {
                        "service_name": "openai", "method": "GET",
                        "url": "https://api.openai.com/",
                        "timeout_seconds": 5,
                    })
        data = _parse_result(result)
        assert "error" in data
        assert "timed out" in data["error"].lower()
        assert data["request_id"] == "req-1"

    @pytest.mark.asyncio
    async def test_pending_then_denied_during_poll(self):
        create_resp = _mock_response(200, json_data={"id": "req-1", "status": "pending"})
        poll_denied = _mock_response(200, json_data={"id": "req-1", "status": "denied"})
        with patch("synauth_mcp.server.requests.request",
                    side_effect=[create_resp, poll_denied]):
            with patch("asyncio.sleep", return_value=None):
                result = await call_tool("execute_api_call", {
                    "service_name": "openai", "method": "GET",
                    "url": "https://api.openai.com/",
                })
        data = _parse_result(result)
        assert "error" in data
        assert "denied" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_payload_construction(self):
        create_resp = _mock_response(200, json_data={"id": "req-1", "status": "approved"})
        exec_resp = _mock_response(200, json_data={"status_code": 200})
        with patch("synauth_mcp.server.requests.request",
                    side_effect=[create_resp, exec_resp]) as mock_req:
            await call_tool("execute_api_call", {
                "service_name": "github",
                "method": "POST",
                "url": "https://api.github.com/repos",
                "headers": {"Accept": "application/json"},
                "body": '{"name":"test"}',
                "description": "Create repo",
            })
        payload = mock_req.call_args_list[0][1]["json"]
        assert payload["metadata"]["vault_execute"] is True
        assert payload["metadata"]["service_name"] == "github"
        assert payload["title"] == "Create repo"


# --- Error handling ---


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_connection_error(self):
        with patch("synauth_mcp.server.requests.request",
                    side_effect=requests.exceptions.ConnectionError("refused")):
            result = await call_tool("request_approval", {
                "action_type": "communication", "title": "Test",
            })
        data = _parse_result(result)
        assert "error" in data
        assert "Cannot connect" in data["error"]

    @pytest.mark.asyncio
    async def test_http_error(self):
        resp = _mock_response(500, text="Internal Server Error")
        with patch("synauth_mcp.server.requests.request", return_value=resp):
            result = await call_tool("request_approval", {
                "action_type": "communication", "title": "Test",
            })
        data = _parse_result(result)
        assert "error" in data
        assert "500" in data["error"]

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        result = await call_tool("nonexistent_tool", {})
        data = _parse_result(result)
        assert "error" in data
        assert "Unknown tool" in data["error"]

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        with patch("synauth_mcp.server.requests.request",
                    side_effect=ValueError("something broke")):
            result = await call_tool("check_approval", {"request_id": "req-1"})
        data = _parse_result(result)
        assert "error" in data
        assert "something broke" in data["error"]


# --- _api helper ---


class TestApiHelper:
    def test_sets_api_key_header(self):
        resp = _mock_response(200, json_data={"status": "ok"})
        with patch("synauth_mcp.server.requests.request", return_value=resp) as mock_req:
            _api("GET", "/test")
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["headers"]["X-API-Key"] == "aa_test_key"

    def test_url_construction(self):
        resp = _mock_response(200, json_data={})
        with patch("synauth_mcp.server.requests.request", return_value=resp) as mock_req:
            _api("POST", "/actions")
        assert mock_req.call_args[0] == ("POST", "https://test.synauth.dev/api/v1/actions")

    def test_raises_on_http_error(self):
        resp = _mock_response(403, text="Forbidden")
        with patch("synauth_mcp.server.requests.request", return_value=resp):
            with pytest.raises(requests.exceptions.HTTPError):
                _api("GET", "/test")
