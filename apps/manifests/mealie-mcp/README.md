# mealie-mcp

A small [MCP](https://modelcontextprotocol.io) server that lets Claude Code
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

The server requires `Authorization: Bearer <token>` on every request. The
token lives in the `mealie-mcp-token` SealedSecret; a copy is kept at
`~/.config/mealie-mcp/token` on the machine that created it.

From any tailnet machine (the Service is exposed by the Tailscale operator,
so traffic is WireGuard-encrypted and not reachable from the LAN):

```bash
claude mcp add --transport http --scope user mealie http://mealie-mcp.tail0ba1ed.ts.net:8000/mcp --header "Authorization: Bearer $(cat ~/.config/mealie-mcp/token)"
```

From inside the cluster (e.g. claude-code-vm), use
`http://mealie-mcp.mealie-mcp.svc.cluster.local:8000/mcp` instead. The server
only answers to the hostnames in `MCP_ALLOWED_HOSTS` (deployment.yaml), so
connect by name, not IP.

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
