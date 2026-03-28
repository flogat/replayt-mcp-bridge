"""Documented max lengths for MCP tool arguments (see docs/MCP_TOOLS.md § String parameter bounds)."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

# Tier A — path-like / target-resolution strings (Unicode code points, len(str))
LEN_TARGET_PATH = 8192

# Tier B — identifiers
LEN_RUN_ID = 1024

# Tier C — JSON object text passed to replayt validation paths
LEN_JSON_BLOB = 1_048_576

# Tier D — diagnostic echo
LEN_ECHO_MESSAGE = 262_144

# Tier E — string lists
MAX_INPUT_OVERRIDES_ITEMS = 128
MAX_EVENT_FIELDS_ITEMS = 256
LEN_EVENT_FIELD_NAME = 256

TierAString = Annotated[str, Field(max_length=LEN_TARGET_PATH)]
TierAStringOpt = Annotated[str | None, Field(default=None, max_length=LEN_TARGET_PATH)]
RunIdStr = Annotated[str, Field(max_length=LEN_RUN_ID)]
JsonBlobStrOpt = Annotated[str | None, Field(default=None, max_length=LEN_JSON_BLOB)]
EchoMessageStr = Annotated[str, Field(max_length=LEN_ECHO_MESSAGE)]

InputOverrideEntry = Annotated[str, Field(max_length=LEN_TARGET_PATH)]
InputOverridesOpt = Annotated[
    list[InputOverrideEntry] | None,
    Field(default=None, max_length=MAX_INPUT_OVERRIDES_ITEMS),
]

EventFieldEntry = Annotated[str, Field(max_length=LEN_EVENT_FIELD_NAME)]
EventFieldsOpt = Annotated[
    list[EventFieldEntry] | None,
    Field(default=None, max_length=MAX_EVENT_FIELDS_ITEMS),
]
