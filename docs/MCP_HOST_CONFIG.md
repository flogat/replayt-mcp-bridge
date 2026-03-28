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

[Claude Desktop](https://claude.ai/download) reads a JSON file with a top-level **`mcpServers`** object. Exact file location depends on OS (see Anthropic / MCP “local servers” docs). Each listed server is spawned as a **stdio** child: MCP runs as JSON-RPC over that process’s **stdin** and **stdout**. Replace placeholder paths with your checkout and venv (keep real secrets and machine-specific layout out of committed snippets).

**Using the module entrypoint (recommended in config files):**

```json
{
  "mcpServers": {
    "replayt": {
      "command": "/path/to/workflow/.venv/bin/python",
      "args": ["-m", "replayt_mcp_bridge"],
      "cwd": "/path/to/workflow"
    }
  }
}
```

**Windows example (same shape; use a drive and folder that match your tree):**

```json
{
  "mcpServers": {
    "replayt": {
      "command": "D:\\path\\to\\workflow\\.venv\\Scripts\\python.exe",
      "args": ["-m", "replayt_mcp_bridge"],
      "cwd": "D:\\path\\to\\workflow"
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
      "cwd": "/path/to/workflow"
    }
  }
}
```

Restart the host application after editing config. If a key such as **`cwd`** is ignored, consult the host’s current documentation or fall back to launching from the desired directory.

## Example: Cursor (`mcp.json`)

[Cursor](https://cursor.com/docs/context/mcp) loads **`mcp.json`** from **`.cursor/mcp.json`** (project) or **`~/.cursor/mcp.json`** (global); see Cursor’s **Configuration locations** in that doc. Register the bridge as a **stdio** transport server: keep **`"type": "stdio"`** next to **`command`** / **`args`** / optional **`env`** so the host spawns a subprocess and speaks MCP on **stdin/stdout** (not HTTP/SSE).

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

## Example: Zed (`context_servers`)

[Zed](https://zed.dev/docs/ai/mcp) connects custom MCP servers by adding a **`context_servers`** entry in [settings](https://zed.dev/docs/configuring-zed.html#settings-files). Entries that specify **`command`** and **`args`** (and optional **`env`**) are **stdio** subprocesses—MCP JSON-RPC on **stdin/stdout**—unlike entries that set **`url`** for remote servers.

Zed does not always expose a separate **`cwd`** key in the same way as Claude Desktop; use an **absolute** path to the venv’s **`python`** (as below) and open the **workflow repository** as your workspace so replayt’s cwd-relative discovery matches your intent, or rely on Zed’s current behavior for the Agent panel (see Zed’s MCP docs).

**POSIX (module entrypoint):**

```json
{
  "context_servers": {
    "replayt": {
      "command": "/path/to/workflow/.venv/bin/python",
      "args": ["-m", "replayt_mcp_bridge"],
      "env": {}
    }
  }
}
```

**Windows (same shape):**

```json
{
  "context_servers": {
    "replayt": {
      "command": "D:\\path\\to\\workflow\\.venv\\Scripts\\python.exe",
      "args": ["-m", "replayt_mcp_bridge"],
      "env": {}
    }
  }
}
```

Restart Zed or reload settings after editing. In the Agent panel, confirm the server indicator shows **active** when stdio startup succeeds.

## Other hosts (IDEs, custom runners)

Many tools use the same **`command` / `args` / `env`** pattern as above; some read **`mcp.json`**, workspace settings, or UI-only configuration. Prefer **`python -m replayt_mcp_bridge`** plus a **full path** to the venv interpreter (or Cursor-style **`${workspaceFolder}`** interpolation) so the bridge does not depend on shell activation inside the GUI app.

## Optional environment

You can pass **`env`** in host JSON for per-server variables (e.g. **`REPLAYT_MCP_BRIDGE_LOG_LEVEL`**, optional **`REPLAYT_MCP_BRIDGE_STORE_HINT_ROOTS`** for persistence path hardening, optional **`REPLAYT_MCP_BRIDGE_RUN_EVENT_FIELDS`** for a default top-level field allowlist on `persistence_list_run_events` when clients omit **`event_fields`**, optional **`REPLAYT_MCP_BRIDGE_REDACT_RUN_EVENTS`** to redact sensitive-shaped keys in `persistence_list_run_events` results, or optional **`REPLAYT_MCP_BRIDGE_RUN_EVENTS_MAX_COUNT`** / **`REPLAYT_MCP_BRIDGE_RUN_EVENTS_MAX_TOTAL_BYTES`** for process-default caps on listed run events—see **[MCP_TOOLS.md § Run event volume limits](MCP_TOOLS.md#run-event-volume-limits-backlog-spec)**). Do not commit secrets; see **[SECURITY.md](SECURITY.md)** for credential-related variables, allowlist semantics, redaction toggles, volume limits, and logging rules.
