# mealie-mcp

A small [MCP](https://modelcontextprotocol.io) server that lets Claude Code, Claude Desktop
(or any MCP client) search, read, create and edit recipes in Mealie, and read
and add meal-plan entries. The whole server is [`server.py`](server.py).

## Tools

| Tool | What it does |
|---|---|
| `search_recipes` | Text search, optionally filtered by tag/category slugs or by ingredient foods (all or any) |
| `list_foods` | The ingredient food names recipes are linked to |
| `what_can_i_make` | Recipe suggestions for a list of foods on hand, optionally allowing a few missing |
| `get_recipe` | Full recipe: ingredients, steps, times, servings, notes, nutrition |
| `create_recipe_from_json` | Create from a schema.org `Recipe` object; Mealie parses it natively |
| `create_recipe_from_url` | Mealie scrapes a recipe page |
| `update_recipe` | Change named fields; list fields replace the whole list |
| `list_tags`, `list_categories` | Existing organizers, to avoid near-duplicate tags |
| `get_meal_plan`, `add_to_meal_plan` | Read or add meal-plan entries |

There are deliberately **no delete tools** and nothing touching webhooks,
notifications, users or admin settings.

## Connecting a client

The server requires `Authorization: Bearer <token>` on every request, with
either of two kinds of token:

- **Your own Mealie API token** (Mealie: Profile -> API Tokens). The server
  checks it with Mealie and acts as you, so recipes you create or edit are
  yours, and it can do nothing your account can't. This is how other people
  in the household connect.
- **The server's token**, in the `mealie-mcp-token` SealedSecret (a copy is
  kept at `~/.config/mealie-mcp/token` on the machine that created it). It
  acts as the `mealie-mcp-mealie-token` user (the admin).

| From | URL |
|---|---|
| The home network, or the tailnet | `http://mealie-mcp.homelab.com/mcp` |
| Any tailnet machine, directly | `http://mealie-mcp.tail0ba1ed.ts.net:8000/mcp` |
| Inside the cluster (e.g. claude-code-vm) | `http://mealie-mcp.mealie-mcp.svc.cluster.local:8000/mcp` |

The home-network URL is plain HTTP (the ingress has only a self-signed
certificate), so the token crosses the Wi-Fi unencrypted. The tailnet URL is
encrypted by WireGuard. The server only answers to the hostnames in
`MCP_ALLOWED_HOSTS` (deployment.yaml), so connect by name, not IP.

Claude Code:

```bash
claude mcp add --transport http --scope user mealie http://mealie-mcp.tail0ba1ed.ts.net:8000/mcp --header "Authorization: Bearer $(cat ~/.config/mealie-mcp/token)"
```

Claude Desktop (needs Node.js). Add this to `claude_desktop_config.json`
(Settings -> Developer -> Edit Config), then restart Claude:

```json
{
  "mcpServers": {
    "mealie": {
      "command": "npx",
      "args": ["-y", "mcp-remote@0.15.2", "http://mealie-mcp.homelab.com/mcp",
               "--allow-http", "--transport", "http-only",
               "--header", "Authorization:${AUTH_HEADER}"],
      "env": { "AUTH_HEADER": "Bearer <your Mealie API token>" }
    }
  }
}
```

The Claude apps' own **Connectors** setting (claude.ai, mobile, Desktop) does
not work with this server: those connections come from Anthropic's servers,
which can't reach the home network.

## Secrets

- `mealie-mcp-token` -- the bearer token clients send. Rotate by generating a
  new value, resealing, and updating each client.
- `mealie-mcp-mealie-token` -- a Mealie API token (Mealie: Profile -> API
  Tokens). Recipes are created as that token's user.

## Changing the server

Edit `server.py` (or bump pins in `requirements.txt`) and merge. Kustomize
hashes both files into the ConfigMap name, so the Deployment rolls
automatically. Dependencies are installed at pod start from the exact pins in
`requirements.txt` on a stock `python:3.12.16-slim` image -- no custom image.
