#!/usr/bin/env python3
"""Manual SABER Episode Test Script.

Generic script to create and interact with SABER episodes for any domain/task.
Useful for manual testing of MCP tools and episode environments.

Usage:
    cd /home/kyledeprow/repos/oss_saber

    # Start server and create episodes for a domain/task
    uv run python scripts/manual_episode_test.py start --domain saber_dual --task react2shell_red_team

    # Create dual-agent episodes (red/blue teams)
    uv run python scripts/manual_episode_test.py start --domain saber_dual --task react2shell_red_team --dual

    # List available tools for an episode
    uv run python scripts/manual_episode_test.py list [episode_name]
    uv run python scripts/manual_episode_test.py list blue
    uv run python scripts/manual_episode_test.py list red

    # Call tools
    uv run python scripts/manual_episode_test.py call [episode_name] bash --command "ls -la"
    uv run python scripts/manual_episode_test.py call blue bash --command "curl http://sentinel:5000/health"

    # Interactive REPL
    uv run python scripts/manual_episode_test.py interactive

    # Stop server and cleanup
    uv run python scripts/manual_episode_test.py stop
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Optional

# Resolve paths
SCRIPT_DIR = Path(__file__).parent
OSS_SABER_ROOT = SCRIPT_DIR.parent
SABER_SRC = OSS_SABER_ROOT / "external" / "saber" / "src"

# Add saber src to path
sys.path.insert(0, str(SABER_SRC))

from saber.client.client_session import ClientSessionManager
from saber.client.models import SessionManagerConfig
from saber.inspect_ai.server.server import DomainController
from saber.inspect_ai.server.session_manager import SessionLifecycleManager
from saber.inspect_ai.constants import SandboxTimeouts

# Episode data file (stored in script dir for easy access)
EPISODE_DATA_FILE = SCRIPT_DIR / ".manual_episode_data.json"


async def start_server_and_create_episodes(
    domain: str,
    task_id: str,
    dual_mode: bool = False,
    blue_task_id: Optional[str] = None,
    rest_port: int = 8000,
    mcp_port: int = 8001,
    skip_server_start: bool = False,
    timeout: int = 300,
) -> dict:
    """Start SABER server and create episodes.
    
    Args:
        domain: Domain slug (e.g., 'saber_dual', 'excytin')
        task_id: Primary task ID to create episode for
        dual_mode: If True, create blue/red team episodes (task_id is red, blue_task_id is blue)
        blue_task_id: Blue team task ID (for dual mode). If not specified, inferred from red task.
        rest_port: REST API port
        mcp_port: MCP API port
        skip_server_start: Skip server startup (connect to existing)
        timeout: Timeout for episode creation in seconds
    
    Returns:
        Episode data dict with session_id, episode_ids, URLs
    """
    domains_root = OSS_SABER_ROOT / "domains"
    rest_url = f"http://localhost:{rest_port}"
    mcp_url = f"http://localhost:{mcp_port}"

    print("=" * 70)
    print("SABER Manual Episode Test - Setup")
    print("=" * 70)
    print(f"\nDomain: {domain}")
    print(f"Task: {task_id}")
    print(f"Dual mode: {dual_mode}")
    print(f"REST port: {rest_port}")
    print(f"MCP port: {mcp_port}")

    # Step 1: Start domain server (if not skipped)
    if not skip_server_start:
        print("\n" + "-" * 70)
        print("Step 1: Starting SABER domain server...")
        print("-" * 70)

        controller = DomainController(domains_root)

        # Check if already running
        running = await controller.check_running_domain(rest_port, mcp_port)
        if running:
            print(f"✓ Domain '{running}' already running on ports {rest_port}/{mcp_port}")
            if running != domain:
                print(f"  WARNING: Different domain running! Expected {domain}")
                print(f"  Run 'stop' command first or use different ports.")
                sys.exit(1)
        else:
            print(f"  Starting domain '{domain}'...")
            context = await controller.start(
                domain=domain,
                rest_port=rest_port,
                mcp_port=mcp_port,
                log_level="INFO",
            )
            print(f"✓ Domain started successfully")
            print(f"  REST URL: {context.rest_url}")
            print(f"  MCP URL: {context.mcp_url}")
            # Small delay after startup to ensure server is fully ready for requests
            await asyncio.sleep(1)
    else:
        print("\n✓ Skipping server start (--skip-server-start)")

    # Step 2: Create session and episodes using SABER's SessionLifecycleManager pattern
    print("\n" + "-" * 70)
    print("Step 2: Creating session and episodes...")
    print("-" * 70)

    # Use SessionLifecycleManager for robust session creation (same as SABERSandboxEnvironment)
    # with retry logic for robustness
    session_lifecycle = SessionLifecycleManager(rest_url)
    print("  Creating session...")
    
    session_id = None
    for attempt in range(5):
        try:
            session_id = await session_lifecycle.create_session(f"{domain}_manual_test")
            break
        except Exception as e:
            if attempt < 4:
                wait_time = 2 ** attempt  # exponential backoff: 1, 2, 4, 8 seconds
                print(f"    Session creation failed, retrying in {wait_time}s... ({e.__class__.__name__})")
                await asyncio.sleep(wait_time)
            else:
                raise
    
    print(f"✓ Session created: {session_id}")

    # Create ClientSessionManager for episode operations
    config = SessionManagerConfig.from_urls(
        rest_url=rest_url,
        mcp_url=mcp_url,
        client_id=f"{domain}_manual_test",
    )
    session_manager = ClientSessionManager(config)
    session_manager._current_session_id = session_id  # Set session ID from lifecycle manager

    # Query available tasks to find orchestrated task IDs
    print("  Querying available tasks...")
    tasks_response = await session_manager.get_available_tasks()
    
    # Find the orchestrated task containing our task_id
    blue_task_id_actual = None
    red_task_id_actual = None
    
    for task_info in tasks_response:
        # Check if this is an orchestrated task containing our task_id pattern
        task_dict = task_info.model_dump() if hasattr(task_info, 'model_dump') else task_info
        
        # Check if task_id appears in the benchmark_task_id or sub_tasks
        if hasattr(task_info, 'benchmark_task_id') and task_id in task_info.benchmark_task_id:
            # This is the orchestrated task we're looking for
            if hasattr(task_info, 'sub_tasks') and task_info.sub_tasks:
                for sub_task in task_info.sub_tasks:
                    sub_task_dict = sub_task.model_dump() if hasattr(sub_task, 'model_dump') else sub_task
                    role = sub_task_dict.get('role', '')
                    sub_task_id = sub_task_dict.get('task_id', '')
                    if role == 'blue':
                        blue_task_id_actual = sub_task_id
                    elif role == 'red':
                        red_task_id_actual = sub_task_id
        
        # Also check if task_info.task_id matches directly 
        if hasattr(task_info, 'task_id') and task_info.task_id == task_id:
            # Direct match - not orchestrated
            pass
    
    # If we found orchestrated task IDs, use them
    if dual_mode and blue_task_id_actual and red_task_id_actual:
        print(f"  Found orchestrated tasks:")
        print(f"    Blue: {blue_task_id_actual}")
        print(f"    Red: {red_task_id_actual}")
        blue_task_id = blue_task_id_actual
        task_id = red_task_id_actual
    elif dual_mode:
        # Fall back to pattern-based inference
        if not blue_task_id:
            # Try pattern: {base}_red_team -> {base}_blue_team_{base}_red_team
            base = task_id.replace("_red_team", "")
            blue_task_id = f"{base}_blue_team_{task_id}"
            print(f"  Inferred blue task ID: {blue_task_id}")

    episodes = {}

    if dual_mode:
        # Dual mode: Create blue team first (dependency root), then red team
        
        print(f"\n  Creating blue team episode ({blue_task_id})...")
        blue_response = await session_manager.create_episode(session_id, blue_task_id)
        print(f"  ✓ Blue episode created: {blue_response.episode_id}")
        print(f"    State: {blue_response.state}")

        # Wait for blue episode to be ready
        print("    Waiting for blue episode to be ready...")
        blue_status = await session_manager.wait_for_episode_ready(
            session_id, blue_response.episode_id, timeout_seconds=timeout
        )
        print(f"  ✓ Blue episode ready: {blue_status.state}")

        episodes["blue"] = {
            "name": "blue",
            "task_id": blue_task_id,
            "episode_id": blue_response.episode_id,
        }

        # Create red team episode (depends on blue)
        print(f"\n  Creating red team episode ({task_id})...")
        red_response = await session_manager.create_episode(session_id, task_id)
        print(f"  ✓ Red episode created: {red_response.episode_id}")
        print(f"    State: {red_response.state}")
        if red_response.attached_to_episode_id:
            print(f"    Attached to: {red_response.attached_to_episode_id}")

        # Wait for red episode to be ready
        print("    Waiting for red episode to be ready...")
        red_status = await session_manager.wait_for_episode_ready(
            session_id, red_response.episode_id, timeout_seconds=timeout
        )
        print(f"  ✓ Red episode ready: {red_status.state}")

        episodes["red"] = {
            "name": "red",
            "task_id": task_id,
            "episode_id": red_response.episode_id,
            "attached_to": red_response.attached_to_episode_id,
        }

    else:
        # Single episode mode
        print(f"\n  Creating episode ({task_id})...")
        response = await session_manager.create_episode(session_id, task_id)
        print(f"  ✓ Episode created: {response.episode_id}")
        print(f"    State: {response.state}")

        # Wait for episode to be ready
        print("    Waiting for episode to be ready...")
        status = await session_manager.wait_for_episode_ready(
            session_id, response.episode_id, timeout_seconds=timeout
        )
        print(f"  ✓ Episode ready: {status.state}")

        episodes["main"] = {
            "name": "main",
            "task_id": task_id,
            "episode_id": response.episode_id,
        }

    # Step 3: Save episode data
    print("\n" + "-" * 70)
    print("Step 3: Saving episode data...")
    print("-" * 70)

    episode_data = {
        "domain": domain,
        "rest_url": rest_url,
        "mcp_url": mcp_url,
        "session_id": session_id,
        "dual_mode": dual_mode,
        "episodes": episodes,
    }

    with open(EPISODE_DATA_FILE, "w") as f:
        json.dump(episode_data, f, indent=2)

    print(f"✓ Episode data saved to: {EPISODE_DATA_FILE}")

    # Summary
    print("\n" + "=" * 70)
    print("Episode Setup Complete!")
    print("=" * 70)
    print(f"\nSession ID: {session_id}")
    
    for name, ep in episodes.items():
        print(f"\n{name.upper()}:")
        print(f"  Episode ID: {ep['episode_id']}")
        print(f"  Task: {ep['task_id']}")
        if ep.get("attached_to"):
            print(f"  Attached to: {ep['attached_to']}")

    print("\n" + "-" * 70)
    print("Next Steps:")
    print("-" * 70)
    episode_names = list(episodes.keys())
    print(f"  # List available tools")
    print(f"  uv run python scripts/manual_episode_test.py list {episode_names[0]}")
    print("")
    print(f"  # Call bash tool")
    print(f'  uv run python scripts/manual_episode_test.py call {episode_names[0]} bash --command "ls -la"')
    print("")
    print(f"  # Interactive mode")
    print(f"  uv run python scripts/manual_episode_test.py interactive")

    return episode_data


def load_episode_data() -> dict:
    """Load episode data from file."""
    if not EPISODE_DATA_FILE.exists():
        print(f"Error: Episode data file not found: {EPISODE_DATA_FILE}")
        print("Run 'start' command first to create episodes.")
        sys.exit(1)
    
    with open(EPISODE_DATA_FILE) as f:
        return json.load(f)


def resolve_episode_name(data: dict, name: str) -> dict:
    """Resolve episode name to episode data."""
    episodes = data["episodes"]
    
    if name in episodes:
        return episodes[name]
    
    # Try to match by partial name
    for ep_name, ep_data in episodes.items():
        if name.lower() in ep_name.lower():
            return ep_data
    
    # If only one episode, use it
    if len(episodes) == 1:
        return list(episodes.values())[0]
    
    print(f"Error: Episode '{name}' not found.")
    print(f"Available episodes: {', '.join(episodes.keys())}")
    sys.exit(1)


class SimpleMCPClient:
    """Simple MCP HTTP client for manual testing.
    
    MCP protocol requires initialize handshake to get mcp-session-id,
    which must be passed in subsequent requests.
    """
    
    def __init__(self, mcp_url: str, session_id: str, episode_id: str):
        self.mcp_url = mcp_url.rstrip("/") + "/mcp"
        self.session_id = session_id
        self.episode_id = episode_id
        self.mcp_session_id: Optional[str] = None
        self.base_headers = {
            "X-SABER-Session-ID": session_id,
            "X-SABER-Episode-ID": episode_id,
            "X-SABER-Orchestration-Env": "standalone",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
    
    async def _ensure_initialized(self) -> None:
        """Initialize MCP session if not already done."""
        if self.mcp_session_id:
            return
        
        import aiohttp
        
        request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "manual_test", "version": "1.0"}
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.mcp_url, json=request, headers=self.base_headers) as resp:
                # Get mcp-session-id from response headers
                self.mcp_session_id = resp.headers.get("mcp-session-id")
                if not self.mcp_session_id:
                    raise Exception("No mcp-session-id in initialize response")
                
                # Read SSE response
                text = await resp.text()
                # Parse SSE format: "event: message\ndata: {...}"
                for line in text.split("\n"):
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        if "error" in data:
                            raise Exception(f"MCP Initialize Error: {data['error']}")
    
    def _get_headers(self) -> dict:
        """Get headers including mcp-session-id."""
        headers = dict(self.base_headers)
        if self.mcp_session_id:
            headers["mcp-session-id"] = self.mcp_session_id
        return headers
    
    async def _parse_sse_response(self, text: str) -> dict:
        """Parse SSE response format."""
        for line in text.split("\n"):
            if line.startswith("data: "):
                return json.loads(line[6:])
        raise Exception(f"No data in SSE response: {text[:200]}")
    
    async def list_tools(self) -> list:
        """List available MCP tools."""
        import aiohttp
        
        await self._ensure_initialized()
        
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.mcp_url, json=request, headers=self._get_headers()) as resp:
                text = await resp.text()
                data = await self._parse_sse_response(text)
                if "error" in data:
                    raise Exception(f"MCP Error: {data['error']}")
                return data.get("result", {}).get("tools", [])
    
    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call an MCP tool."""
        import aiohttp
        
        await self._ensure_initialized()
        
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(self.mcp_url, json=request, headers=self._get_headers()) as resp:
                text = await resp.text()
                data = await self._parse_sse_response(text)
                if "error" in data:
                    raise Exception(f"MCP Error: {data['error']}")
                return data.get("result", {})


async def list_tools(episode_name: str) -> None:
    """List available MCP tools for an episode."""
    data = load_episode_data()
    episode = resolve_episode_name(data, episode_name)
    
    episode_id = episode["episode_id"]
    mcp_url = data["mcp_url"]
    session_id = data["session_id"]
    
    print(f"\n{'=' * 60}")
    print(f"MCP Tools for Episode: {episode['name'].upper()}")
    print(f"{'=' * 60}")
    print(f"Episode ID: {episode_id}")
    print(f"Task: {episode['task_id']}")
    print(f"MCP URL: {mcp_url}")
    
    client = SimpleMCPClient(mcp_url, session_id, episode_id)
    
    tools = await client.list_tools()
    print(f"\nAvailable Tools ({len(tools)}):")
    print("-" * 60)
    
    for tool in tools:
        name = tool.get("name", "unknown")
        desc = tool.get("description", "")
        print(f"\n  {name}")
        if desc:
            # Truncate long descriptions
            desc_short = desc[:100] + "..." if len(desc) > 100 else desc
            print(f"    {desc_short}")
        input_schema = tool.get("inputSchema", {})
        if input_schema and "properties" in input_schema:
            props = input_schema["properties"]
            if props:
                print(f"    Parameters: {', '.join(props.keys())}")


async def call_tool(episode_name: str, tool_name: str, args: dict) -> None:
    """Call an MCP tool for an episode."""
    data = load_episode_data()
    episode = resolve_episode_name(data, episode_name)
    
    episode_id = episode["episode_id"]
    mcp_url = data["mcp_url"]
    session_id = data["session_id"]
    
    print(f"\n{'=' * 60}")
    print(f"Calling Tool: {tool_name}")
    print(f"{'=' * 60}")
    print(f"Episode: {episode['name'].upper()}")
    print(f"Episode ID: {episode_id}")
    print(f"Arguments: {json.dumps(args, indent=2)}")
    
    client = SimpleMCPClient(mcp_url, session_id, episode_id)
    
    print(f"\n{'─' * 60}")
    print("Executing...")
    print(f"{'─' * 60}")
    
    result = await client.call_tool(tool_name, args)
    
    print(f"\n{'─' * 60}")
    print("Result:")
    print(f"{'─' * 60}")
    
    # Handle MCP result content
    content = result.get("content", [])
    for item in content:
        if isinstance(item, dict) and "text" in item:
            print(item["text"])
        else:
            print(json.dumps(item, indent=2) if isinstance(item, dict) else item)


async def interactive_mode() -> None:
    """Interactive REPL for calling MCP tools."""
    data = load_episode_data()
    episodes = data["episodes"]
    
    print(f"\n{'=' * 60}")
    print("SABER Interactive MCP Tool Tester")
    print(f"{'=' * 60}")
    print(f"Domain: {data['domain']}")
    print(f"Session ID: {data['session_id']}")
    print(f"\nEpisodes:")
    for name, ep in episodes.items():
        print(f"  {name}: {ep['episode_id']} ({ep['task_id']})")
    
    print(f"\nCommands:")
    print("  use <episode>        - Switch active episode")
    print("  list                 - List available tools")
    print("  call <tool> [args]   - Call a tool (args as JSON)")
    print("  bash <command>       - Shortcut for bash tool")
    print("  status               - Show current episode info")
    print("  help                 - Show this help")
    print("  quit                 - Exit")
    
    mcp_url = data["mcp_url"]
    session_id = data["session_id"]
    
    # Start with first episode
    current_name = list(episodes.keys())[0]
    
    def get_client(name: str) -> SimpleMCPClient:
        episode_id = episodes[name]["episode_id"]
        return SimpleMCPClient(mcp_url, session_id, episode_id)
    
    while True:
        try:
            prompt = f"\n[{current_name.upper()}] > "
            line = input(prompt).strip()
            
            if not line:
                continue
            
            parts = line.split(None, 1)
            cmd = parts[0].lower()
            rest = parts[1] if len(parts) > 1 else ""
            
            if cmd == "quit" or cmd == "exit":
                break
            
            elif cmd == "help":
                print("Commands: use, list, call, bash, status, help, quit")
            
            elif cmd == "status":
                ep = episodes[current_name]
                print(f"Current episode: {current_name}")
                print(f"  Episode ID: {ep['episode_id']}")
                print(f"  Task: {ep['task_id']}")
            
            elif cmd == "use":
                if rest in episodes:
                    current_name = rest
                    print(f"Switched to {current_name.upper()} episode")
                else:
                    print(f"Usage: use <{' | '.join(episodes.keys())}>")
            
            elif cmd == "list":
                client = get_client(current_name)
                tools = await client.list_tools()
                print(f"\nTools ({len(tools)}):")
                for t in tools:
                    print(f"  - {t.get('name', 'unknown')}")
            
            elif cmd == "bash":
                if not rest:
                    print("Usage: bash <command>")
                    continue
                client = get_client(current_name)
                result = await client.call_tool("bash", {"command": rest})
                for item in result.get("content", []):
                    if isinstance(item, dict) and "text" in item:
                        print(item["text"])
                    else:
                        print(item)
            
            elif cmd == "call":
                # Parse: call <tool_name> {json_args} or call <tool_name> --arg value
                if not rest:
                    print("Usage: call <tool_name> [json_args]")
                    continue
                
                tool_parts = rest.split(None, 1)
                tool_name = tool_parts[0]
                
                args = {}
                if len(tool_parts) > 1:
                    arg_str = tool_parts[1]
                    if arg_str.startswith("{"):
                        args = json.loads(arg_str)
                    else:
                        # Simple --key value parsing
                        tokens = arg_str.split()
                        i = 0
                        while i < len(tokens):
                            if tokens[i].startswith("--"):
                                key = tokens[i][2:]
                                if i + 1 < len(tokens) and not tokens[i+1].startswith("--"):
                                    args[key] = tokens[i+1]
                                    i += 2
                                else:
                                    args[key] = True
                                    i += 1
                            else:
                                i += 1
                
                client = get_client(current_name)
                result = await client.call_tool(tool_name, args)
                for item in result.get("content", []):
                    if isinstance(item, dict) and "text" in item:
                        print(item["text"])
                    else:
                        print(item)
            
            else:
                print(f"Unknown command: {cmd}")
                print("Type 'help' for available commands")
                
        except EOFError:
            break
        except KeyboardInterrupt:
            print("\n^C")
            continue
        except Exception as e:
            print(f"Error: {e}")


async def stop_server(domain: Optional[str] = None) -> None:
    """Stop the SABER domain server."""
    # Try to get domain from saved data
    if domain is None and EPISODE_DATA_FILE.exists():
        with open(EPISODE_DATA_FILE) as f:
            data = json.load(f)
            domain = data.get("domain")
    
    if domain is None:
        print("Error: No domain specified and no saved episode data found.")
        print("Usage: stop --domain <domain_name>")
        sys.exit(1)
    
    domains_root = OSS_SABER_ROOT / "domains"
    controller = DomainController(domains_root)
    
    print(f"Stopping SABER domain server ({domain})...")
    await controller.stop(domain)
    print("✓ Server stopped")
    
    # Clean up episode data file
    if EPISODE_DATA_FILE.exists():
        EPISODE_DATA_FILE.unlink()
        print(f"✓ Removed {EPISODE_DATA_FILE}")


def main():
    parser = argparse.ArgumentParser(
        description="Manual SABER Episode Test Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # start command
    start_parser = subparsers.add_parser("start", help="Start server and create episodes")
    start_parser.add_argument("--domain", "-d", required=True, help="Domain slug (e.g., saber_dual)")
    start_parser.add_argument("--task", "-t", required=True, help="Task ID to create episode for")
    start_parser.add_argument("--dual", action="store_true", 
                              help="Dual agent mode (create blue/red team episodes)")
    start_parser.add_argument("--blue-task", help="Blue team task ID (for dual mode)")
    start_parser.add_argument("--rest-port", type=int, default=8000, help="REST API port")
    start_parser.add_argument("--mcp-port", type=int, default=8001, help="MCP API port")
    start_parser.add_argument("--skip-server-start", action="store_true", 
                              help="Skip server startup (connect to existing)")
    start_parser.add_argument("--timeout", type=int, default=300,
                              help="Timeout for episode creation in seconds")
    
    # list command
    list_parser = subparsers.add_parser("list", help="List available MCP tools")
    list_parser.add_argument("episode", nargs="?", default="main", 
                             help="Episode name (e.g., main, blue, red)")
    
    # call command  
    call_parser = subparsers.add_parser("call", help="Call an MCP tool")
    call_parser.add_argument("episode", help="Episode name (e.g., main, blue, red)")
    call_parser.add_argument("tool", help="Tool name")
    call_parser.add_argument("--command", "-c", help="Command for bash tool")
    call_parser.add_argument("--args", "-a", help="JSON arguments")
    
    # interactive command
    subparsers.add_parser("interactive", help="Interactive REPL mode")
    
    # stop command
    stop_parser = subparsers.add_parser("stop", help="Stop the SABER server")
    stop_parser.add_argument("--domain", "-d", help="Domain to stop (defaults to saved)")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == "start":
        asyncio.run(start_server_and_create_episodes(
            domain=args.domain,
            task_id=args.task,
            dual_mode=args.dual,
            blue_task_id=args.blue_task,
            rest_port=args.rest_port,
            mcp_port=args.mcp_port,
            skip_server_start=args.skip_server_start,
            timeout=args.timeout,
        ))
    
    elif args.command == "list":
        asyncio.run(list_tools(args.episode))
    
    elif args.command == "call":
        tool_args = {}
        if args.command:
            tool_args["command"] = args.command
        if args.args:
            tool_args.update(json.loads(args.args))
        asyncio.run(call_tool(args.episode, args.tool, tool_args))
    
    elif args.command == "interactive":
        asyncio.run(interactive_mode())
    
    elif args.command == "stop":
        asyncio.run(stop_server(args.domain))


if __name__ == "__main__":
    main()
