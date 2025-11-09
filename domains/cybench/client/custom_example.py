"""Example custom agent for CyBench domain.

This demonstrates how to create a domain-specific agent in the client/ folder.
This agent would be used with: -T agent=custom_example
"""

from inspect_ai.agent import react
from inspect_ai.agent._types import AgentPrompt

from saber.inspect_ai.tools import saber_tools
from saber.logging_config import LogCategory, get_saber_logger

logger = get_saber_logger(LogCategory.AGENT, __name__)


def create_agent(**kwargs):
    """Create a custom agent with special behavior for CyBench.
    
    This is an example showing how to create domain-specific agents.
    You can customize:
    - Agent type (react, chain, custom)
    - Prompt engineering
    - Tool selection
    - Model parameters
    
    Args:
        **kwargs: Additional parameters passed to agent
        
    Returns:
        Callable that creates agent with prompts
    """
    def create_with_prompts(instruction_prompt: str, assistant_prompt: str, submit_prompt: str):
        """Inner factory that receives prompts from task execution."""
        logger.info(
            "Creating CUSTOM CyBench agent",
            extra={
                "agent": "custom_example",
                "instruction_length": len(instruction_prompt),
            }
        )
        
        # You can modify prompts here for domain-specific behavior
        # For example, add additional instructions:
        custom_instruction = (
            f"{instruction_prompt}\n\n"
            "ADDITIONAL GUIDANCE FOR CYBENCH:\n"
            "- Always verify file permissions before reading\n"
            "- Check for hidden files and directories\n"
            "- Look for configuration files that might contain clues"
        )
        
        # Create React agent with customized prompts
        return react(
            prompt=AgentPrompt(
                instructions=custom_instruction,
                handoff_prompt=None,
                assistant_prompt=assistant_prompt,
                submit_prompt=submit_prompt,
            ),
            tools=[saber_tools()],
            **kwargs
        )
    
    return create_with_prompts


__all__ = ["create_agent"]
