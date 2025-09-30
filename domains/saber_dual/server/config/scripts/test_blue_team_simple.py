#!/usr/bin/env python3
"""
Simple Blue Team Tools Test

Quick test to verify the core blue team tools are functioning properly.
"""

import asyncio
import logging
import sys
import time

# Add the scripts directory to path
sys.path.append('/home/ms_test/repos/SABER_dual/saber_dual/server/config/scripts')
from test_session_management import SABERDualTester

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_blue_team_tools():
    """Test individual blue team tools."""
    
    logger.info("🔵 SIMPLE BLUE TEAM TOOLS TEST")
    logger.info("=" * 50)
    
    # Initialize tester
    tester = SABERDualTester("blue_team_simple_test")
    
    # Setup environment
    if not await tester.check_server_health():
        logger.error("❌ Server health check failed")
        return False
    
    # Create session and blue team episode
    session_id = await tester.create_session()
    await tester.create_blue_team_episode()
    
    logger.info("✅ Environment setup complete")
    
    # Initialize test result variables
    result1 = {"success": False}
    result1b = {"success": False}
    result1c = {"success": False}
    result1d = {"success": False}
    result2 = {"success": False}
    result3 = {"success": False}
    
    # Test 1: Security Events (No filters)
    logger.info("\n🔍 Test 1: Basic Security Events Query")
    time.sleep(5)
    result1 = await tester.execute_tool(
        tester.blue_episode_id, "security_events", "blue team",
        timeframe="5m"
    )
    
    if result1.get("success"):
        logger.info("✅ security_events tool working")
        # Extract and format the clean security events output
        output_data = result1.get("output", {})
        if isinstance(output_data, dict) and "data" in output_data:
            stdout_content = output_data["data"].get("stdout", "")
            # Format the output nicely without extra escaping
            logger.info("📋 Security Events Output:")
            logger.info("-" * 60)
            logger.info(stdout_content)
            logger.info("-" * 60)
        elif isinstance(output_data, str):
            # Handle case where output might be a string
            try:
                import ast
                parsed_output = ast.literal_eval(output_data)
                if isinstance(parsed_output, dict) and "data" in parsed_output:
                    stdout_content = parsed_output["data"].get("stdout", "")
                    logger.info("📋 Security Events Output:")
                    logger.info("-" * 60)
                    logger.info(stdout_content)
                    logger.info("-" * 60)
            except:
                logger.info(f"📋 Raw output format: {output_data[:200]}...")
    else:
        logger.warning(f"⚠️  security_events issue: {result1.get('error', 'Unknown error')}")
    
    # Test 1B: Security Events with specific event types (to reproduce the error)
    logger.info("\n🔍 Test 1B: Security Events with Event Type Filters")
    result1b = await tester.execute_tool(
        tester.blue_episode_id, "security_events", "blue team",
        timeframe="1m",
        event_types=["auth_attempt", "auth_success", "auth_failure"]
    )
    
    if result1b.get("success"):
        logger.info("✅ security_events with filters working")
        output_data = result1b.get("output", {})
        if isinstance(output_data, dict) and "data" in output_data:
            stdout_content = output_data["data"].get("stdout", "")
            logger.info("📋 Filtered Security Events Output:")
            logger.info("-" * 60)
            logger.info(stdout_content)
            logger.info("-" * 60)
        elif isinstance(output_data, str):
            try:
                import ast
                parsed_output = ast.literal_eval(output_data)
                if isinstance(parsed_output, dict) and "data" in parsed_output:
                    stdout_content = parsed_output["data"].get("stdout", "")
                    logger.info("📋 Filtered Security Events Output:")
                    logger.info("-" * 60)
                    logger.info(stdout_content)
                    logger.info("-" * 60)
            except:
                logger.info(f"📋 Raw filtered output: {output_data[:200]}...")
    else:
        logger.warning(f"⚠️  security_events with filters issue: {result1b.get('error', 'Unknown error')}")
        # Show only the error message, not the entire raw response
        if "output" in result1b and isinstance(result1b["output"], dict):
            error_data = result1b["output"].get("data", {})
            if "stderr" in error_data:
                logger.error(f"🐛 SIEM Error: {error_data['stderr']}")
        else:
            logger.error(f"🐛 Error details: {result1b.get('error', 'Unknown')}")
    
    # Test 1C: Security Events with source filters
    logger.info("\n🔍 Test 1C: Security Events with Source Filters")
    result1c = await tester.execute_tool(
        tester.blue_episode_id, "security_events", "blue team",
        timeframe="2m",
        sources=["vault", "webapp"]
    )
    
    if result1c.get("success"):
        logger.info("✅ security_events with source filters working")
        output_data = result1c.get("output", {})
        if isinstance(output_data, dict) and "data" in output_data:
            stdout_content = output_data["data"].get("stdout", "")
            logger.info("📋 Source-Filtered Security Events Output:")
            logger.info("-" * 60)
            logger.info(stdout_content)
            logger.info("-" * 60)
        elif isinstance(output_data, str):
            try:
                import ast
                parsed_output = ast.literal_eval(output_data)
                if isinstance(parsed_output, dict) and "data" in parsed_output:
                    stdout_content = parsed_output["data"].get("stdout", "")
                    logger.info("📋 Source-Filtered Security Events Output:")
                    logger.info("-" * 60)
                    logger.info(stdout_content)
                    logger.info("-" * 60)
            except:
                logger.info(f"📋 Raw source-filtered output: {output_data[:200]}...")
    else:
        logger.warning(f"⚠️  security_events with source filters issue: {result1c.get('error', 'Unknown error')}")
        if "output" in result1c and isinstance(result1c["output"], dict):
            error_data = result1c["output"].get("data", {})
            if "stderr" in error_data:
                logger.error(f"🐛 SIEM Error: {error_data['stderr']}")
        else:
            logger.error(f"🐛 Error details: {result1c.get('error', 'Unknown')}")
    
    # Test 1D: Security Events with combined filters (event types + sources)
    logger.info("\n🔍 Test 1D: Security Events with Combined Filters (Types + Sources)")
    result1d = await tester.execute_tool(
        tester.blue_episode_id, "security_events", "blue team",
        timeframe="2m",
        event_types=["secret_access", "auth_success", "sql_error"],
        sources=["vault", "database"]
    )
    
    if result1d.get("success"):
        logger.info("✅ security_events with combined filters working")
        output_data = result1d.get("output", {})
        if isinstance(output_data, dict) and "data" in output_data:
            stdout_content = output_data["data"].get("stdout", "")
            logger.info("📋 Combined-Filtered Security Events Output:")
            logger.info("-" * 60)
            logger.info(stdout_content)
            logger.info("-" * 60)
        elif isinstance(output_data, str):
            try:
                import ast
                parsed_output = ast.literal_eval(output_data)
                if isinstance(parsed_output, dict) and "data" in parsed_output:
                    stdout_content = parsed_output["data"].get("stdout", "")
                    logger.info("📋 Combined-Filtered Security Events Output:")
                    logger.info("-" * 60)
                    logger.info(stdout_content)
                    logger.info("-" * 60)
            except:
                logger.info(f"📋 Raw combined-filtered output: {output_data[:200]}...")
    else:
        logger.warning(f"⚠️  security_events with combined filters issue: {result1d.get('error', 'Unknown error')}")
        if "output" in result1d and isinstance(result1d["output"], dict):
            error_data = result1d["output"].get("data", {})
            if "stderr" in error_data:
                logger.error(f"🐛 SIEM Error: {error_data['stderr']}")
        else:
            logger.error(f"🐛 Error details: {result1d.get('error', 'Unknown')}")
    
    # Test 2: Block IP
    logger.info("\n🔒 Test 2: IP Blocking")
    result2 = await tester.execute_tool(
        tester.blue_episode_id, "block_ip", "blue team",
        ip_address="192.168.1.100",
        duration_seconds=60
    )
    
    if result2.get("success"):
        logger.info("✅ block_ip tool working")
    else:
        logger.warning(f"⚠️  block_ip issue: {result2.get('error', 'Unknown error')}")
    
    # Test 3: Container Isolation
    logger.info("\n🛡️  Test 3: Container Isolation")
    result3 = await tester.execute_tool(
        tester.blue_episode_id, "isolate_container", "blue team",
        service_name="webapp"
    )
    
    if result3.get("success"):
        logger.info("✅ isolate_container tool working")
    else:
        logger.warning(f"⚠️  isolate_container issue: {result3.get('error', 'Unknown error')}")
    
    # Summary
    logger.info("\n📊 BLUE TEAM TOOLS SUMMARY")
    logger.info("=" * 30)
    
    tools_tested = [
        ("security_events", result1.get("success", False)),
        ("security_events_filtered", result1b.get("success", False)),
        ("security_events_source_filter", result1c.get("success", False)),
        ("security_events_combined_filter", result1d.get("success", False)),
        ("block_ip", result2.get("success", False)),
        ("isolate_container", result3.get("success", False))
    ]
    
    working_tools = sum(1 for _, success in tools_tested if success)
    total_tools = len(tools_tested)
    
    for tool_name, success in tools_tested:
        status = "✅" if success else "❌"
        logger.info(f"{status} {tool_name}")
    
    logger.info(f"\n🎯 Blue Team Tools Status: {working_tools}/{total_tools} working ({(working_tools/total_tools)*100:.1f}%)")
    
    # Enhanced analysis
    security_events_tests = sum(1 for name, success in tools_tested if "security_events" in name and success)
    logger.info(f"📊 Security Events Tests: {security_events_tests}/4 filters working")
    
    if working_tools >= 5:
        logger.info("🎉 Blue team tools are functioning correctly!")
        return True
    else:
        logger.error("❌ Some blue team tools need attention")
        return False

if __name__ == "__main__":
    asyncio.run(test_blue_team_tools())