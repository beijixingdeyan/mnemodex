"""Version information for mnemodex."""

__version__ = "0.1.0"
VERSION = __version__

# The version of the on-disk formats (index + memory store). Bump when we
# change a serialized schema; `mnemodex` then automatically migrates or
# rebuilds.
INDEX_FORMAT_VERSION = 1
MEMORY_FORMAT_VERSION = 1

# The MCP protocol version we speak.
MCP_PROTOCOL_VERSION = "2024-11-05"

# Human-facing name reported over MCP and in the web UI.
PRODUCT_NAME = "mnemodex"
PRODUCT_TAGLINE = "The memory index for AI coding agents."