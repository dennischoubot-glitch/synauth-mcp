# SynAuth MCP Server

Biometric approval for AI agent actions. Every sensitive action your AI agent takes — sending emails, making purchases, accessing data, signing contracts — goes through Face ID verification on your iPhone.

## Quick Start

```bash
pip install synauth-mcp
```

Add to your Claude configuration (`~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "synauth": {
      "command": "synauth-mcp",
      "env": {
        "SYNAUTH_API_KEY": "aa_your_key_here"
      }
    }
  }
}
```

## How It Works

1. Your AI agent calls a tool (send email, make purchase, query database)
2. SynAuth sends a push notification to your iPhone
3. You verify with Face ID
4. SynAuth executes the action with your stored credentials
5. The agent gets the result — but never sees your API keys

## Why SynAuth

**The agent can't bypass what it can't access.** Your API credentials live in SynAuth's vault, not in the agent's environment. The MCP server is the only tool surface — there is no other path to your sensitive services.

| Feature | SynAuth | Slack/Email Buttons |
|---------|---------|-------------------|
| Verification | Face ID (biometric) | Click a button (anyone with access) |
| Credential safety | Agent never sees keys | Agent often has direct key access |
| Audit trail | Every action logged with biometric proof | Click timestamp at best |
| Compliance | Proves physical identity of approver | Proves someone had Slack access |

## Available Tools

| Tool | Description |
|------|-------------|
| `request_approval` | Submit an action for biometric approval |
| `check_approval` | Check status of a pending request |
| `wait_for_approval` | Block until request is resolved |
| `get_spending_summary` | View spending against configured limits |
| `get_approval_history` | Review past approved/denied actions |
| `list_vault_services` | See which API credentials are stored |
| `execute_api_call` | Make an API call through the vault (biometric-gated) |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SYNAUTH_API_KEY` | Yes | — | Your SynAuth API key |
| `SYNAUTH_URL` | No | `https://synauth.fly.dev` | SynAuth backend URL (override for self-hosted) |

## Action Types

- **communication** — emails, messages, notifications
- **purchase** — buying, subscriptions, payments
- **scheduling** — bookings, reservations, calendar
- **legal** — contracts, terms, agreements
- **data_access** — database queries, file downloads
- **social** — social media posts, profile updates
- **system** — config changes, restarts, deployments

## License

MIT
