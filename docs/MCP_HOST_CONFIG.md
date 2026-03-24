# MCP host configuration (stdio)

This bridge speaks **MCP over stdio** (JSON-RPC on stdin/stdout). Your MCP parent spawns a child process and wires its stdio to the protocol. Hosts differ by **config file path** and **which optional keys** they support (`cwd`, `env`, …); the **process launch shape** below is what matters for this package.

**Trust boundary:** Anyone who can attach an MCP client to that process can invoke registered tools. Read **[SECURITY.md](SECURITY.md)** for environment variables, logging risks, and deployment expectations before you enable the server in a shared or remote setup.

**Upstream references:**

- [Model Context Protocol](https://modelcontextprotocol.io/) — protocol and SDK orientation.
- [Connect to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers) — general guidance for local stdio servers (field names and restart behavior vary by host).

## Canonical entrypoints

After `pip install -e .` (or a non-editable install) in a **virtual environment**, use either:

| Entrypoint | When to use |
| ---------- | ----------- |
| **`replayt-mcp-bridge`** | Console script from `[project.scripts]` in `pyproject.toml`; must be on **`PATH`** (typical when the venv is activated or when you pass the full path to the script). |
| **`python -m replayt_mcp_bridge`** | Explicit interpreter; set **`command`** to the venv’s `python` and pass **`-m`**, **`replayt_mcp_bridge`** in **`args`** (see examples below). |

Both are equivalent for MCP traffic. Prefer **`python -m …`** in host JSON when activation is awkward or you want a single absolute path to the interpreter.

## Working directory (`cwd`)

Replayt discovers project config (e.g. `.replaytrc.toml`, `pyproject.toml` `[tool.replayt]`) from the **process working directory** and ancestors, similar to the replayt CLI. Point **`cwd`** at your **workflow repo root** when your host supports that key; otherwise run the host from that directory or document the limitation for your team.

## Windows vs POSIX

Create the venv and install the bridge the same way on all platforms; only paths and activation differ.

| | POSIX (Linux, macOS) | Windows |
| - | -------------------- | ------- |
| Create venv | `python3 -m venv .venv` | `py -3 -m venv .venv` or `python -m venv .venv` |
| Activate (shell) | `source .venv/bin/activate` | `.venv\Scripts\activate` (cmd/PowerShell) |
| Interpreter for **`command`** | `.venv/bin/python` | `.venv\Scripts\python.exe` |
| Console script (if on PATH) | `replayt-mcp-bridge` | `replayt-mcp-bridge.exe` (same name; resolves via `PATH`) |

Use **forward slashes** or **escaped backslashes** in JSON on Windows when you embed absolute paths.

## Example: Claude Desktop (`mcpServers`)

[Claude Desktop](https://claude.ai/download) reads a JSON file with a top-level **`mcpServers`** object. Exact file location depends on OS (see Anthropic / MCP “local servers” docs). Replace paths with your checkout and venv.

**Using the module entrypoint (recommended in config files):**

```json
{
  "mcpServers": {
    "replayt": {
      "command": "/home/you/projects/my-workflow/.venv/bin/python",
      "args": ["-m", "replayt_mcp_bridge"],
      "cwd": "/home/you/projects/my-workflow"
    }
  }
}
```

**Windows example (same shape, different paths):**

```json
{
  "mcpServers": {
    "replayt": {
      "command": "C:\\Users\\you\\projects\\my-workflow\\.venv\\Scripts\\python.exe",
      "args": ["-m", "replayt_mcp_bridge"],
      "cwd": "C:\\Users\\you\\projects\\my-workflow"
    }
  }
}
```

**Using the console script** (only if that executable is on the **`PATH`** seen by the desktop app—often requires a wrapper or a full path to `replayt-mcp-bridge` inside the venv):

```json
{
  "mcpServers": {
    "replayt": {
      "command": "replayt-mcp-bridge",
      "args": [],
      "cwd": "/home/you/projects/my-workflow"
    }
  }
}
```

Restart the host application after editing config. If a key such as **`cwd`** is ignored, consult the host’s current documentation or fall back to launching from the desired directory.

## Example: Cursor (`mcp.json`)

[Cursor](https://cursor.com/docs/context/mcp) loads **`mcp.json`** from **`.cursor/mcp.json`** (project) or **`~/.cursor/mcp.json`** (global); see Cursor’s **Configuration locations** in that doc. For **stdio** servers it documents a **`type`** field set to **`"stdio"`** alongside **`command`** / **`args`** / optional **`env`**.

Replayt resolves config from the process working directory; Cursor usually starts stdio servers with the **workspace folder** as cwd when you use project config—if tools cannot see your workflow files, confirm cwd behavior in Cursor’s current MCP docs.

**Project-local example (POSIX venv under the repo):**

```json
{
  "mcpServers": {
    "replayt": {
      "type": "stdio",
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["-m", "replayt_mcp_bridge"]
    }
  }
}
```

**Windows (same shape; adjust the venv path):**

```json
{
  "mcpServers": {
    "replayt": {
      "type": "stdio",
      "command": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
      "args": ["-m", "replayt_mcp_bridge"]
    }
  }
}
```

You can instead hardcode an absolute path to the venv’s **`python`** if you prefer not to use **`${workspaceFolder}`** interpolation. Restart Cursor after editing **`mcp.json`**.

## Other hosts (IDEs, custom runners)

Many tools use the same **`command` / `args` / `env`** pattern as above; some read **`mcp.json`**, workspace settings, or UI-only configuration. Prefer **`python -m replayt_mcp_bridge`** plus a **full path** to the venv interpreter (or Cursor-style **`${workspaceFolder}`** interpolation) so the bridge does not depend on shell activation inside the GUI app.

## Optional environment

You can pass **`env`** in host JSON for per-server variables (e.g. **`REPLAYT_MCP_BRIDGE_LOG_LEVEL`** or optional **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** for persistence path hardening). Do not commit secrets; see **[SECURITY.md](SECURITY.md)** for credential-related variables, allowlist semantics, and logging rules.
