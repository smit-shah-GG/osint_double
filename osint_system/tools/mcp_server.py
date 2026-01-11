"""MCP Tool Server for OSINT System.

This module implements an MCP (Model Context Protocol) server that exposes
tools to LLM agents for web scraping, search, and other operations.
"""

import asyncio
import json
from typing import Any, Dict, Optional
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.types import (
    Tool,
    TextContent,
    CallToolResult,
    CallToolRequest,
)


# Initialize the MCP server
server = Server("osint-tools")


@server.tool()
async def web_scraper() -> Tool:
    """Define the web scraper tool."""
    return Tool(
        name="web_scraper",
        description="Scrape content from a given URL",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to scrape"
                },
                "selector": {
                    "type": "string",
                    "description": "Optional CSS selector to extract specific content",
                    "required": False
                }
            },
            "required": ["url"]
        }
    )


@server.tool()
async def search_tool() -> Tool:
    """Define the search tool."""
    return Tool(
        name="search_tool",
        description="Search for information using a query",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    )


@server.call_tool()
async def handle_tool_call(request: CallToolRequest) -> CallToolResult:
    """Handle tool execution requests."""
    try:
        tool_name = request.params["name"]
        arguments = request.params.get("arguments", {})

        if tool_name == "web_scraper":
            url = arguments.get("url", "")
            selector = arguments.get("selector", None)

            # Mock implementation for now
            result = {
                "status": "success",
                "url": url,
                "content": f"Mock scraped content from {url}",
                "selector_used": selector,
                "metadata": {
                    "timestamp": "2026-01-11T17:00:00Z",
                    "source": "web_scraper_stub"
                }
            }

            return CallToolResult(
                content=[TextContent(text=json.dumps(result, indent=2))]
            )

        elif tool_name == "search_tool":
            query = arguments.get("query", "")
            max_results = arguments.get("max_results", 10)

            # Mock implementation for now
            results = []
            for i in range(min(3, max_results)):
                results.append({
                    "title": f"Result {i+1} for '{query}'",
                    "url": f"https://example.com/result{i+1}",
                    "snippet": f"Mock search result snippet containing information about {query}",
                    "relevance_score": 0.9 - (i * 0.1)
                })

            result = {
                "status": "success",
                "query": query,
                "results": results,
                "total_found": len(results),
                "metadata": {
                    "timestamp": "2026-01-11T17:00:00Z",
                    "source": "search_tool_stub"
                }
            }

            return CallToolResult(
                content=[TextContent(text=json.dumps(result, indent=2))]
            )

        else:
            raise McpError(f"Unknown tool: {tool_name}")

    except Exception as e:
        # Proper error handling
        error_result = {
            "status": "error",
            "error": str(e),
            "tool": request.params.get("name", "unknown")
        }
        return CallToolResult(
            content=[TextContent(text=json.dumps(error_result, indent=2))],
            isError=True
        )


async def main():
    """Main entry point for the MCP server."""
    # Run the server using stdio transport
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)


if __name__ == "__main__":
    # Support both direct execution and --help flag
    import sys
    if "--help" in sys.argv:
        print("OSINT MCP Tool Server")
        print("")
        print("This server exposes tools via MCP protocol:")
        print("  - web_scraper: Scrape content from URLs")
        print("  - search_tool: Search for information")
        print("")
        print("Usage: python mcp_server.py")
        sys.exit(0)

    # Run the async main function
    asyncio.run(main())