"""Interactive CLI for OSINT Intelligence System using Typer and Rich."""

import sys
import time
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from osint_system.config.settings import settings
from osint_system.config.logging import get_logger

# Initialize CLI app
app = typer.Typer(
    help="OSINT Intelligence System CLI - Multi-Agent OSINT Analysis Platform",
    add_completion=False,
)

# Initialize Rich console for beautiful output
console = Console()

# Initialize logger
logger = get_logger("cli")


@app.command()
def status() -> None:
    """
    Display system status and configuration.

    Shows current environment, API configuration, and logging settings.
    """
    logger.info("Displaying system status")

    # Create status table
    table = Table(title="OSINT System Status", show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan", width=20)
    table.add_column("Status", style="green", width=15)
    table.add_column("Details", style="yellow")

    # Add system information
    python_version = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    table.add_row("Environment", "✓ Ready", f"{python_version} + uv")

    # Add Gemini API configuration
    api_status = "✓ Configured" if settings.gemini_api_key != "your-api-key-here" else "⚠ Not Configured"
    api_details = f"{settings.gemini_model} (RPM: {settings.max_rpm}, TPM: {settings.max_tpm:,})"
    table.add_row("Gemini API", api_status, api_details)

    # Add logging configuration
    log_details = f"Level: {settings.log_level}, Format: {settings.log_format}"
    table.add_row("Logging", "✓ Active", log_details)

    # Add interactive mode
    interactive_status = "✓ Enabled" if settings.interactive_mode else "✗ Disabled"
    table.add_row("Interactive Mode", interactive_status, "CLI prompts and rich output")

    # Display the table
    console.print(table)


@app.command()
def agent(
    name: str = typer.Option(..., prompt="Agent name"),
    task: str = typer.Option(..., prompt="Task description"),
) -> None:
    """
    Run an agent with a specific task.

    Args:
        name: Agent name (e.g., newsfeed, fact_extraction)
        task: Task description for the agent to execute
    """
    logger.info(f"Agent command invoked: {name}", extra={"task": task})

    console.print(f"[bold cyan]Agent:[/bold cyan] {name}")
    console.print(f"[bold yellow]Task:[/bold yellow] {task}")
    console.print("\n[italic]Agent execution not yet implemented - coming in Phase 2[/italic]")

    # Placeholder for future agent execution logic
    console.print(f"\n[dim]Would run agent '{name}' with task: {task}[/dim]")


@app.command()
def test_gemini(
    prompt: str = typer.Option(None, prompt="Enter test prompt")
) -> None:
    """
    Test Gemini API connection with a simple prompt.

    Args:
        prompt: Test prompt to send to Gemini API
    """
    logger.info("Testing Gemini API connection")

    try:
        # Import Gemini client
        from osint_system.llm.gemini_client import client

        # Display prompt info
        console.print("\n[bold cyan]Testing Gemini API[/bold cyan]")
        console.print(f"[yellow]Prompt:[/yellow] {prompt}\n")

        # Count tokens
        token_count = client.count_tokens(prompt)
        console.print(f"[dim]Token count: {token_count}[/dim]")

        # Start timing
        start_time = time.time()

        # Generate content
        console.print("[dim]Generating response...[/dim]\n")
        response = client.generate_content(prompt)

        # Calculate elapsed time
        elapsed = time.time() - start_time

        # Truncate response if too long
        display_response = response[:500]
        if len(response) > 500:
            display_response += "..."

        # Display response in a panel
        console.print(Panel(
            display_response,
            title="Gemini Response",
            border_style="green"
        ))

        # Display success message
        console.print(
            f"\n[green]✓[/green] Success! "
            f"Response generated in {elapsed:.2f}s "
            f"({len(response)} chars)"
        )

        logger.info("Gemini API test completed successfully")

    except Exception as e:
        console.print(f"\n[red]✗[/red] Error: {e}")
        logger.error(f"Gemini API test failed: {e}")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Display version information."""
    console.print("[bold]OSINT Intelligence System[/bold]")
    console.print("Version: 0.1.0-alpha")
    console.print("Phase: Foundation & Environment Setup")


if __name__ == "__main__":
    app()
