# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **[docs/MCP_HOST_CONFIG.md](docs/MCP_HOST_CONFIG.md)** — copy-paste MCP host stdio configuration (**Claude Desktop** `mcpServers` and **Cursor** `.cursor/mcp.json` with **`type: "stdio"`**), **`replayt-mcp-bridge`** vs **`python -m replayt_mcp_bridge`**, Windows vs POSIX paths, and pointers to **[docs/SECURITY.md](docs/SECURITY.md)**.

## [0.1.0] - 2026-03-23

### Added

- Initial documented release of the MCP stdio bridge for replayt workflow steps (`replayt-mcp-bridge` / `python -m replayt_mcp_bridge`).
- Declared **replayt** dependency range `>=0.4.25,<0.5` (see `pyproject.toml`); CI exercises the declared minimum on Python 3.11.
