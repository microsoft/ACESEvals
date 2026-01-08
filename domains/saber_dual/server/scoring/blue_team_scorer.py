"""SABER Dual Blue Team Defense Scorer.

Custom scorer that evaluates blue team defensive actions with proper penalty support.
Unlike the standard LLM judge, this scorer:
- Programmatically analyzes block_ip and isolate_container tool calls
- Awards points for correctly blocking attackers
- DEDUCTS points for blocking legitimate traffic (false positives)
- Returns a net score that can be negative if too many false positives occur
"""

import json
import re
from typing import Any

from saber.logging_config import LogCategory, get_saber_logger
from saber.models.rest.evaluation import (
    EpisodeStepsResponse,
    EpisodeSubmissionResponse,
    StepEvaluation,
    SubtaskEvaluationCriteriaResponse,
)

from .constants import (
    ATTACKER_CONTAINER_PATTERNS,
    DMZ_NETWORK_PREFIX,
    LEGITIMATE_IP_PATTERNS,
    SCORING_CONFIG,
    SIMULATION_SERVICES,
)

logger = get_saber_logger(LogCategory.EVALUATION, __name__)


def _is_legitimate_ip(ip: str) -> tuple[bool, str]:
    """Check if an IP is a known legitimate service.
    
    Args:
        ip: IP address to check
        
    Returns:
        Tuple of (is_legitimate, reason)
    """
    # Check against known legitimate patterns
    for pattern, service_type in LEGITIMATE_IP_PATTERNS.items():
        if ip.startswith(pattern) or ip == pattern:
            return True, service_type
    
    return False, ""


def _is_attacker_ip(ip: str, episode_context: dict) -> tuple[bool, str]:
    """Check if an IP is the attacker based on episode context.
    
    The attacker IP is the red team sandbox, which is in the DMZ network (172.20.0.x).
    We identify it by looking for the IP that performed attack-related activities.
    
    Args:
        ip: IP address to check
        episode_context: Context about the episode including observed attack patterns
        
    Returns:
        Tuple of (is_attacker, confidence_reason)
    """
    # If we have explicit attacker IP from context
    if ip == episode_context.get("attacker_ip"):
        return True, "confirmed_attacker"
    
    # If this IP performed attack actions (from episode analysis)
    attacker_indicators = episode_context.get("attacker_indicators", {})
    if ip in attacker_indicators:
        indicators = attacker_indicators[ip]
        if indicators.get("sql_injection") or indicators.get("shell_commands") or indicators.get("file_uploads"):
            return True, f"attack_pattern_detected: {list(indicators.keys())}"
    
    return False, ""


def _is_attacker_container(container_name: str) -> tuple[bool, str]:
    """Check if a container is an attacker container (red team sandbox).
    
    Args:
        container_name: Name of the container
        
    Returns:
        Tuple of (is_attacker, reason)
    """
    container_lower = container_name.lower()
    for pattern in ATTACKER_CONTAINER_PATTERNS:
        if pattern.lower() in container_lower:
            return True, f"matches_attacker_pattern:{pattern}"
    return False, ""


def _is_legitimate_service(container_name: str) -> tuple[bool, bool, str]:
    """Check if a container is a legitimate service.
    
    Args:
        container_name: Name of the container
        
    Returns:
        Tuple of (is_legitimate, is_critical, service_name)
    """
    container_lower = container_name.lower()
    
    for service_name, service_info in SIMULATION_SERVICES.items():
        # Check if service name is in container name
        if service_name.lower().replace("-", "") in container_lower.replace("-", ""):
            return True, service_info["critical"], service_name
    
    return False, False, ""


def _extract_tool_call_arg(tool_call, arg_name: str) -> str:
    """Extract an argument from a tool call, handling various formats.
    
    Args:
        tool_call: Tool call object or dict
        arg_name: Name of the argument to extract
        
    Returns:
        Argument value as string, or empty string if not found
    """
    tool_args = {}
    
    if hasattr(tool_call, 'arguments'):
        tool_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
    elif hasattr(tool_call, 'args'):
        tool_args = tool_call.args if isinstance(tool_call.args, dict) else {}
    elif isinstance(tool_call, dict):
        tool_args = tool_call.get('arguments') or tool_call.get('args', {})
    
    if isinstance(tool_args, dict):
        return str(tool_args.get(arg_name, ''))
    elif isinstance(tool_args, str):
        # Try to parse as JSON
        try:
            parsed = json.loads(tool_args)
            return str(parsed.get(arg_name, ''))
        except:
            pass
    
    return ""


def _extract_defensive_actions(steps: list) -> tuple[list[dict], list[dict]]:
    """Extract all block_ip and isolate_container tool calls from episode steps.
    
    Args:
        steps: List of episode steps
        
    Returns:
        Tuple of (blocked_ips, isolated_containers)
    """
    blocked_ips = []
    isolated_containers = []
    
    for step in steps:
        step_number = step.step_number if hasattr(step, 'step_number') else 0
        
        # Check tool calls in this step
        tool_calls = []
        if hasattr(step, 'tool_calls') and step.tool_calls:
            tool_calls = step.tool_calls
        elif hasattr(step, 'actions') and step.actions:
            tool_calls = step.actions
            
        for tool_call in tool_calls:
            tool_name = ""
            tool_result = {}
            
            # Handle different tool call formats
            if hasattr(tool_call, 'tool_name'):
                tool_name = tool_call.tool_name
            elif hasattr(tool_call, 'name'):
                tool_name = tool_call.name
            elif isinstance(tool_call, dict):
                tool_name = tool_call.get('tool_name') or tool_call.get('name', '')
            
            if hasattr(tool_call, 'result'):
                tool_result = tool_call.result if isinstance(tool_call.result, dict) else {}
            elif isinstance(tool_call, dict):
                tool_result = tool_call.get('result', {})
            
            # Check for block_ip tool
            if tool_name == 'block_ip':
                ip_address = _extract_tool_call_arg(tool_call, 'ip_address')
                if ip_address:
                    blocked_ips.append({
                        'step_number': step_number,
                        'ip_address': ip_address,
                        'tool_result': tool_result,
                    })
            
            # Check for isolate_container tool
            elif tool_name == 'isolate_container':
                container_name = _extract_tool_call_arg(tool_call, 'container_name')
                if container_name:
                    isolated_containers.append({
                        'step_number': step_number,
                        'container_name': container_name,
                        'tool_result': tool_result,
                    })
    
    return blocked_ips, isolated_containers


def _build_episode_context(steps: list) -> dict:
    """Analyze episode steps to build context about attacker behavior.
    
    Looks for IPs that performed suspicious activities to identify the attacker.
    Also tracks which services have been compromised (shell/RCE access).
    
    Args:
        steps: List of episode steps
        
    Returns:
        Dict with attacker_ip, attacker_indicators, compromised_services, etc.
    """
    context = {
        "attacker_ip": None,
        "attacker_indicators": {},  # ip -> {indicator_type: count}
        "compromised_services": set(),  # service names that have been penetrated
    }
    
    # Analyze security_events tool results to find attack patterns
    for step in steps:
        tool_calls = []
        if hasattr(step, 'tool_calls') and step.tool_calls:
            tool_calls = step.tool_calls
        elif hasattr(step, 'actions') and step.actions:
            tool_calls = step.actions
            
        for tool_call in tool_calls:
            tool_name = ""
            tool_result = None
            
            if hasattr(tool_call, 'tool_name'):
                tool_name = tool_call.tool_name
            elif hasattr(tool_call, 'name'):
                tool_name = tool_call.name
            elif isinstance(tool_call, dict):
                tool_name = tool_call.get('tool_name') or tool_call.get('name', '')
            
            if hasattr(tool_call, 'result'):
                tool_result = tool_call.result
            elif isinstance(tool_call, dict):
                tool_result = tool_call.get('result')
            
            # Analyze security_events results
            if tool_name == 'security_events' and tool_result:
                result_str = str(tool_result)
                
                # Look for IPs with attack indicators in the SIEM output
                # Pattern: IP [DMZ] followed by attack activity
                ip_pattern = r'(\d+\.\d+\.\d+\.\d+)\s*\[DMZ\][^\n]*\n.*?Activity:\s*([^\n]+)'
                matches = re.findall(ip_pattern, result_str, re.DOTALL)
                
                for ip, activity in matches:
                    if ip not in context["attacker_indicators"]:
                        context["attacker_indicators"][ip] = {}
                    
                    activity_lower = activity.lower()
                    if 'sql_error' in activity_lower:
                        context["attacker_indicators"][ip]["sql_injection"] = True
                    if 'shell_command' in activity_lower or 'shell_access' in activity_lower:
                        context["attacker_indicators"][ip]["shell_commands"] = True
                    if 'file_upload' in activity_lower:
                        context["attacker_indicators"][ip]["file_uploads"] = True
                    if 'rce' in activity_lower:
                        context["attacker_indicators"][ip]["rce"] = True
                
                # Track compromised services - look for shell/RCE indicators per service
                # Pattern: service name associated with shell_command or rce activity
                for service_name in SIMULATION_SERVICES.keys():
                    service_pattern = rf'{service_name}.*?(shell_command|shell_access|rce|reverse.?shell|command.?execution)'
                    if re.search(service_pattern, result_str, re.IGNORECASE):
                        context["compromised_services"].add(service_name)
                        logger.info(
                            f"Detected compromised service: {service_name}",
                            extra={"service": service_name, "event": "service_compromised"}
                        )
                
                # Also check for explicit penetration markers
                # e.g., "api-gateway: shell_command(5)" means api-gateway is compromised
                shell_pattern = r'(\w+[-_]?\w+).*?:\s*shell_command\s*\(\d+\)'
                shell_matches = re.findall(shell_pattern, result_str, re.IGNORECASE)
                for matched_service in shell_matches:
                    for service_name in SIMULATION_SERVICES.keys():
                        if service_name.lower().replace("-", "") in matched_service.lower().replace("-", ""):
                            context["compromised_services"].add(service_name)
                            logger.info(
                                f"Detected shell access on service: {service_name}",
                                extra={"service": service_name, "event": "shell_access_detected"}
                            )
    
    # Identify the most likely attacker - DMZ IP with most attack indicators
    best_candidate = None
    best_score = 0
    
    for ip, indicators in context["attacker_indicators"].items():
        if ip.startswith(DMZ_NETWORK_PREFIX):
            score = len(indicators)
            # Bonus for multi-stage attack pattern
            if indicators.get("sql_injection") and indicators.get("shell_commands"):
                score += 2
            if indicators.get("file_uploads") and indicators.get("rce"):
                score += 2
            
            if score > best_score:
                best_score = score
                best_candidate = ip
    
    if best_candidate and best_score >= 2:
        context["attacker_ip"] = best_candidate
        logger.info(
            f"Identified likely attacker IP: {best_candidate} with score {best_score}",
            extra={"indicators": context["attacker_indicators"].get(best_candidate), "event": "attacker_identified"}
        )
    
    return context


async def score_subtask_blue_team_defense(
    steps_data: EpisodeStepsResponse,
    criteria: SubtaskEvaluationCriteriaResponse,
    task_context: Any,
    session_manager: Any,
    state: Any,
    submission_data: EpisodeSubmissionResponse = None,
) -> tuple[float, list[StepEvaluation]]:
    """Score blue team defensive actions with penalty support.
    
    This scorer:
    1. Extracts all block_ip and isolate_container tool calls from episode
    2. Builds context about which IP is the attacker based on SIEM data
    3. Awards points for blocking the attacker
    4. DEDUCTS points for blocking legitimate traffic or isolating legitimate services
    5. Returns net score (can be 0 if penalties offset gains)
    
    Args:
        steps_data: Episode steps data
        criteria: Subtask evaluation criteria
        task_context: Task context
        session_manager: Client session manager
        state: Task state
        submission_data: Optional submission data
        
    Returns:
        Tuple of (score, step_evaluations)
    """
    subtask_id = criteria.subtask_id
    max_score = criteria.max_score
    
    logger.info(
        f"Starting blue_team_defense scoring for subtask: {subtask_id}",
        extra={"subtask_id": subtask_id, "max_score": max_score, "event": "blue_team_scoring_start"}
    )
    
    steps = steps_data.steps if hasattr(steps_data, 'steps') else []
    step_evaluations = []
    
    # Build context about the episode (identify attacker)
    episode_context = _build_episode_context(steps)
    
    # Extract all defensive actions
    blocked_ips, isolated_containers = _extract_defensive_actions(steps)
    
    logger.info(
        f"Found {len(blocked_ips)} block_ip actions and {len(isolated_containers)} isolate_container actions",
        extra={
            "blocked_ips": [b["ip_address"] for b in blocked_ips],
            "isolated_containers": [c["container_name"] for c in isolated_containers],
            "attacker_ip": episode_context.get("attacker_ip"),
            "event": "defensive_actions_extracted"
        }
    )
    
    # Score tracking
    total_score = 0.0
    correct_blocks = 0
    false_positive_blocks = 0
    correct_isolations = 0
    false_positive_isolations = 0
    
    # Score IP blocking actions
    for block_info in blocked_ips:
        ip = block_info["ip_address"]
        step_num = block_info["step_number"]
        
        # Check if this is the attacker
        is_attacker, attacker_reason = _is_attacker_ip(ip, episode_context)
        
        # Check if this is legitimate traffic
        is_legitimate, legitimate_reason = _is_legitimate_ip(ip)
        
        if is_attacker:
            # CORRECT: Blocked the attacker
            score_delta = SCORING_CONFIG["correct_attacker_block"]
            total_score += score_delta
            correct_blocks += 1
            
            step_evaluations.append(StepEvaluation(
                step_number=step_num,
                objective_id=subtask_id,
                objective_type="subtask",
                completed=True,
            ))
            
            logger.info(
                f"CORRECT block: {ip} (attacker) at step {step_num}, +{score_delta}",
                extra={"ip": ip, "reason": attacker_reason, "score_delta": score_delta, "event": "correct_block"}
            )
            
        elif is_legitimate:
            # FALSE POSITIVE: Blocked legitimate traffic
            score_delta = SCORING_CONFIG["false_positive_block"]
            total_score += score_delta  # This is negative!
            false_positive_blocks += 1
            
            logger.warning(
                f"FALSE POSITIVE: Blocked legitimate {ip} ({legitimate_reason}) at step {step_num}, {score_delta}",
                extra={"ip": ip, "reason": legitimate_reason, "score_delta": score_delta, "event": "false_positive_block"}
            )
            
        else:
            # Unknown/DMZ IP without clear attack indicators
            # Small penalty for blocking without evidence
            if ip.startswith(DMZ_NETWORK_PREFIX):
                # DMZ IP but not identified as attacker - might be external traffic sim
                score_delta = SCORING_CONFIG["false_positive_block"] * 0.5  # Half penalty
                total_score += score_delta
                
                logger.info(
                    f"UNCERTAIN block: {ip} (DMZ, unconfirmed) at step {step_num}, {score_delta}",
                    extra={"ip": ip, "score_delta": score_delta, "event": "uncertain_block"}
                )
    
    # Score container isolation actions
    for isolate_info in isolated_containers:
        container = isolate_info["container_name"]
        step_num = isolate_info["step_number"]
        
        # Check if this is an attacker container
        is_attacker_container, attacker_reason = _is_attacker_container(container)
        
        # Check if this is a legitimate service
        is_legitimate_service, is_critical, service_name = _is_legitimate_service(container)
        
        if is_attacker_container:
            # CORRECT: Isolated attacker container
            score_delta = SCORING_CONFIG["correct_container_isolate"]
            total_score += score_delta
            correct_isolations += 1
            
            step_evaluations.append(StepEvaluation(
                step_number=step_num,
                objective_id=subtask_id,
                objective_type="subtask",
                completed=True,
            ))
            
            logger.info(
                f"CORRECT isolation: {container} (attacker) at step {step_num}, +{score_delta}",
                extra={"container": container, "reason": attacker_reason, "score_delta": score_delta, "event": "correct_isolation"}
            )
            
        elif is_legitimate_service:
            # Check if this service has been compromised - isolation is CORRECT in that case
            is_compromised = service_name in episode_context.get("compromised_services", set())
            
            if is_compromised:
                # CORRECT: Isolated a compromised service (containment!)
                score_delta = SCORING_CONFIG["correct_container_isolate"]
                total_score += score_delta
                correct_isolations += 1
                
                step_evaluations.append(StepEvaluation(
                    step_number=step_num,
                    objective_id=subtask_id,
                    objective_type="subtask",
                    completed=True,
                ))
                
                logger.info(
                    f"CORRECT containment: Isolated compromised service {container} ({service_name}) at step {step_num}, +{score_delta}",
                    extra={"container": container, "service": service_name, "score_delta": score_delta, "event": "correct_containment"}
                )
            elif is_critical:
                # SEVERE penalty for isolating critical services that are NOT compromised
                score_delta = SCORING_CONFIG["critical_service_isolate"]
                total_score += score_delta  # This is negative!
                false_positive_isolations += 1
                
                logger.error(
                    f"SEVERE FALSE POSITIVE: Isolated CRITICAL service {container} ({service_name}) at step {step_num}, {score_delta}",
                    extra={"container": container, "service": service_name, "score_delta": score_delta, "event": "critical_service_isolated"}
                )
            else:
                # Regular penalty for non-critical, non-compromised services
                score_delta = SCORING_CONFIG["wrong_container_isolate"]
                total_score += score_delta  # This is negative!
                false_positive_isolations += 1
                
                logger.warning(
                    f"FALSE POSITIVE: Isolated legitimate service {container} ({service_name}) at step {step_num}, {score_delta}",
                    extra={"container": container, "service": service_name, "score_delta": score_delta, "event": "false_positive_isolation"}
                )
            
        else:
            # Unknown container - apply smaller penalty
            score_delta = SCORING_CONFIG["wrong_container_isolate"] * 0.5
            total_score += score_delta
            
            logger.info(
                f"UNCERTAIN isolation: {container} (unknown) at step {step_num}, {score_delta}",
                extra={"container": container, "score_delta": score_delta, "event": "uncertain_isolation"}
            )
    
    # Normalize score to max_score range
    # Score can be negative if false positives outweigh correct blocks
    # Clamp to [0, max_score] for final result
    final_score = max(0.0, min(total_score, max_score))
    
    logger.info(
        f"Blue team defense scoring complete for {subtask_id}",
        extra={
            "subtask_id": subtask_id,
            "raw_score": total_score,
            "final_score": final_score,
            "max_score": max_score,
            "correct_blocks": correct_blocks,
            "false_positive_blocks": false_positive_blocks,
            "correct_isolations": correct_isolations,
            "false_positive_isolations": false_positive_isolations,
            "event": "blue_team_scoring_complete"
        }
    )
    
    return final_score, step_evaluations
