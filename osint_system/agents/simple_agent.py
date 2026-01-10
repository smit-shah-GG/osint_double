"""Simple proof-of-concept agent for foundation validation."""

from osint_system.agents.base_agent import BaseAgent
from osint_system.llm.gemini_client import client as gemini_client


class SimpleAgent(BaseAgent):
    """
    Basic proof-of-concept agent demonstrating foundation integration.

    Validates the complete stack: configuration, logging, LLM API access,
    and agent architecture. Processes simple text generation tasks using
    the Gemini API with token counting and error handling.
    """

    def __init__(self):
        """Initialize SimpleAgent with base configuration."""
        super().__init__("SimpleAgent", "Basic proof-of-concept agent")

    async def process(self, input_data: dict) -> dict:
        """
        Process a simple task using Gemini API.

        Args:
            input_data: Dictionary with 'task' key containing task description

        Returns:
            Dictionary with status, response text, and token usage
        """
        task = input_data.get("task", "No task specified")
        self.logger.info(f"Processing task: {task}")

        # Construct prompt
        prompt = f"As a helpful assistant, {task}"

        try:
            # Count tokens for cost monitoring
            tokens = gemini_client.count_tokens(prompt)
            self.logger.debug(f"Token count: {tokens}")

            # Generate response
            response = gemini_client.generate_content(prompt)

            self.logger.success("Task completed successfully")
            return {
                "status": "success",
                "response": response,
                "tokens_used": tokens
            }

        except Exception as e:
            self.logger.error(f"Processing failed: {e}")
            return {
                "status": "error",
                "error": str(e)
            }

    def get_capabilities(self) -> list[str]:
        """
        Return SimpleAgent capabilities.

        Returns:
            List of capability identifiers
        """
        return ["text_generation", "simple_tasks"]
