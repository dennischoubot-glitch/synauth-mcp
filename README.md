# SynAuth MCP Server

Biometric authorization for AI agent actions. Every sensitive action your AI agent takes — sending emails, making purchases, accessing data, signing contracts — goes through Face ID verification on your iPhone.

This is the MCP (Model Context Protocol) server. It works with Claude, Cursor, and any MCP-compatible agent. For direct Python integration, see the [SynAuth SDK](https://pypi.org/project/synauth/).

## Install

```bash
pip install synauth-mcp
```

## Configure

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

Restart Claude. The agent now has access to SynAuth tools.

## Setup: From Zero to First Approval

**1. Get the SynAuth iOS app.** Download from the App Store. Create an account.

**2. Get your API key.** The app generates an API key when you create your account. Copy it — this is what connects your agent to your phone.

**3. Configure your agent.** Add the MCP config above with your API key.

**4. (Optional) Store credentials in the vault.** In the SynAuth app, go to the Vault tab and add your API credentials (OpenAI, GitHub, Stripe, etc.). This enables the vault execution model — your agent can use these services without ever seeing the keys.

**5. Try it.** Ask your agent to do something that requires approval — "send an email to team@company.com" or "check my OpenAI usage." Your iPhone will light up with a Face ID prompt.

## How It Works

```
Your Agent (Claude, Cursor, etc.)
    │
    ├─ request_approval("Send email to team@co.com")
    │       │
    │       ▼
    │   SynAuth Backend ──── push notification ───▶ iPhone
    │       │                                        │
    │       │                                    Face ID ✓
    │       │                                        │
    │       ◀──────────── approved ──────────────────┘
    │
    ├─ (Approval-only mode) Agent executes the action itself
    │
    └─ (Vault mode) execute_api_call("openai", "POST", "https://api.openai.com/...")
            │
            ▼
        SynAuth injects stored credential, makes the API call
            │
            ▼
        Response returned to agent (agent never saw the API key)
```

There are two modes:

- **Approval-only** — The agent asks permission, then acts with its own credentials. Good for actions where the agent already has access but needs human sign-off.
- **Vault execution** — The agent asks permission, then SynAuth executes using stored credentials. The agent never touches the real API keys. This is structural enforcement — the agent can't bypass what it can't access.

## Why This Exists

Most agent approval systems work like this: agent has your API keys, agent asks "can I use them?", you click a button in Slack. If the agent ignores the answer — or if someone else clicks the button — it still has the keys.

SynAuth works differently:

- **Face ID, not buttons.** Proves the authorized person approved it — not just someone with Slack access.
- **Vault execution.** The agent doesn't have your API keys. SynAuth does. After biometric approval, SynAuth makes the API call and returns the result. The agent gets the output without ever seeing the credential.
- **Audit trail with identity proof.** Every action is logged with biometric verification — not a click timestamp.

| | SynAuth | Slack/Email Buttons |
|---|---|---|
| Verification | Face ID (biometric) | Click a button (anyone with access) |
| Credential safety | Agent never sees keys | Agent often has direct key access |
| Audit trail | Every action logged with biometric proof | Click timestamp at best |
| Compliance | Proves physical identity of approver | Proves someone had Slack access |

## Usage Examples

### Approve an email

Your agent decides to send an email. It requests approval, waits for your Face ID, then proceeds:

```
Agent: I'll send the quarterly report to investors@company.com.
       Let me get approval first.

→ request_approval(
    action_type: "communication",
    title: "Send quarterly report to investors@company.com",
    description: "Q4 2025 financial results and outlook",
    risk_level: "low"
  )

← { "id": "req_abc123", "status": "pending" }

→ wait_for_approval(request_id: "req_abc123")

  [Your iPhone buzzes. You glance, see "Send quarterly report
   to investors@company.com", verify with Face ID.]

← { "id": "req_abc123", "status": "approved", "resolved_by": "face_id" }

Agent: Approved. Sending now.
```

### Make a purchase (with spending limits)

Before buying something, the agent checks spending limits, then requests approval:

```
Agent: You asked me to buy DigitalOcean credits. Let me check the budget.

→ get_spending_summary()

← { "summaries": [
     { "period": "monthly", "limit": 500.00, "spent": 120.00,
       "remaining": 380.00, "utilization_pct": 24.0 }
   ] }

Agent: You have $380 remaining this month. Requesting approval for $49.99.

→ request_approval(
    action_type: "purchase",
    title: "Purchase DigitalOcean credits",
    amount: 49.99,
    recipient: "DigitalOcean",
    risk_level: "medium"
  )

→ wait_for_approval(request_id: "req_def456")

  [Face ID prompt on your iPhone shows: "Purchase DigitalOcean
   credits — $49.99"]

← { "status": "approved" }
```

### Call an API through the vault

This is the key differentiator. Your agent needs to call the GitHub API, but it doesn't have your GitHub token — SynAuth does:

```
Agent: I'll create the repository. Let me check what services
       are available.

→ list_vault_services()

← { "services": [
     { "service_name": "github", "auth_type": "bearer",
       "allowed_hosts": ["api.github.com"] },
     { "service_name": "openai", "auth_type": "bearer",
       "allowed_hosts": ["api.openai.com"] }
   ] }

→ execute_api_call(
    service_name: "github",
    method: "POST",
    url: "https://api.github.com/user/repos",
    headers: { "Content-Type": "application/json" },
    body: '{"name": "new-project", "private": true}',
    description: "Create private repo 'new-project' on GitHub"
  )

  [Face ID prompt: "Create private repo 'new-project' on GitHub"]

← { "status": "approved", "response": { "status_code": 201, ... } }
```

The agent provided the request details. SynAuth showed you what it wanted to do. You verified with Face ID. SynAuth injected your GitHub token and made the API call. The agent got the response but never saw the token.

**Security properties of vault execution:**
- **URL host validation** — The GitHub token can only be sent to `api.github.com`. If the agent tries to send it elsewhere, the request is rejected.
- **Single-use** — Each approval authorizes exactly one API call. The agent can't reuse an old approval.
- **Credential isolation** — The agent's environment has only a SynAuth API key. No GitHub tokens, no OpenAI keys, no Stripe secrets.

### Review past actions

```
→ get_approval_history(limit: 5)

← { "actions": [
     { "title": "Send quarterly report", "status": "approved",
       "resolved_at": "2025-02-18T10:30:00Z" },
     { "title": "Purchase DigitalOcean credits", "status": "approved",
       "amount": 49.99, "resolved_at": "2025-02-18T10:15:00Z" },
     { "title": "Post to Twitter", "status": "denied",
       "deny_reason": "Content needs review" }
   ] }
```

## Available Tools

| Tool | What it does |
|------|-------------|
| `request_approval` | Submit any action for biometric approval. Returns immediately with status. |
| `check_approval` | Check current status of a pending request. |
| `wait_for_approval` | Block until the request is approved, denied, or expired. |
| `get_spending_summary` | Check spending against configured limits before making purchases. |
| `get_approval_history` | Review past approved, denied, and expired actions. |
| `list_vault_services` | See which API credentials are stored in the vault. |
| `execute_api_call` | Make an API call through the vault — biometric approval + credential injection. |

## Rules Engine

Not every action needs a Face ID prompt. SynAuth has a rules engine that can auto-approve or auto-deny based on:

- **Action type** — Auto-approve low-risk scheduling, require approval for legal actions
- **Risk level** — Low-risk actions auto-approve, critical actions always require Face ID
- **Amount** — Purchases under $10 auto-approve, over $100 require approval
- **Agent ID** — Different rules for different agents

You configure rules in the iOS app. The agent doesn't need to know about rules — it just calls `request_approval` and gets back either `"status": "approved"` (auto-approved by rule) or `"status": "pending"` (waiting for Face ID).

## Action Types

| Type | Examples | Default Risk |
|------|----------|-------------|
| `communication` | Emails, messages, notifications | low |
| `purchase` | Buying, subscriptions, payments | medium |
| `scheduling` | Bookings, reservations, calendar | low |
| `legal` | Contracts, terms, agreements | critical |
| `data_access` | Database queries, file downloads | high |
| `social` | Social media posts, profile updates | medium |
| `system` | Config changes, restarts, deployments | high |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SYNAUTH_API_KEY` | Yes | — | Your SynAuth API key (starts with `aa_`) |
| `SYNAUTH_URL` | No | `https://synauth.fly.dev` | Backend URL (override for self-hosted) |

## Also Available

- **[synauth](https://pypi.org/project/synauth/)** — Python SDK for direct integration (convenience methods, typed errors, spending limits)
- **[SynAuth iOS App](https://synauth.dev)** — Face ID approval on your iPhone
- **REST API** — `https://synauth.fly.dev/api/v1/` for any language

## License

MIT
