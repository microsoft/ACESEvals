"""Tests for the blue team defense scorer.

Tests the scoring logic for blue team defensive actions including:
- IP legitimacy checking
- Attacker identification
- Container isolation scoring
- Compromised service detection
- Overall scoring with penalties
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Add the domains path so we can import the scoring module
_repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_repo_root / "domains" / "saber_dual"))

# Mock ALL saber imports BEFORE any imports that might touch them
# This includes the __init__.py which imports from saber
mock_saber = MagicMock()
mock_scoring = MagicMock()
mock_scoring.ScorerMetadata = MagicMock
mock_scoring.register_subtask_scorer = MagicMock()

sys.modules['saber'] = mock_saber
sys.modules['saber.inspect_ai'] = MagicMock()
sys.modules['saber.inspect_ai.core'] = MagicMock()
sys.modules['saber.inspect_ai.core.scoring'] = mock_scoring
sys.modules['saber.logging_config'] = MagicMock()
sys.modules['saber.logging_config'].LogCategory = MagicMock()
sys.modules['saber.logging_config'].get_saber_logger = MagicMock(return_value=MagicMock())
sys.modules['saber.models'] = MagicMock()
sys.modules['saber.models.rest'] = MagicMock()
sys.modules['saber.models.rest.evaluation'] = MagicMock()

# Create mock classes for the evaluation models
class MockStepEvaluation:
    def __init__(self, step_number, objective_id, objective_type, completed):
        self.step_number = step_number
        self.objective_id = objective_id
        self.objective_type = objective_type
        self.completed = completed

# Patch the StepEvaluation import
sys.modules['saber.models.rest.evaluation'].StepEvaluation = MockStepEvaluation
sys.modules['saber.models.rest.evaluation'].EpisodeStepsResponse = MagicMock
sys.modules['saber.models.rest.evaluation'].EpisodeSubmissionResponse = MagicMock
sys.modules['saber.models.rest.evaluation'].SubtaskEvaluationCriteriaResponse = MagicMock

# Now import the scorer module
from server.scoring.blue_team_scorer import (
    _is_legitimate_ip,
    _is_attacker_ip,
    _is_attacker_container,
    _is_legitimate_service,
    _extract_tool_call_arg,
    _extract_defensive_actions,
    _build_episode_context,
    score_subtask_blue_team_defense,
)
from server.scoring.constants import (
    LEGITIMATE_IP_PATTERNS,
    DMZ_NETWORK_PREFIX,
    SIMULATION_SERVICES,
    ATTACKER_CONTAINER_PATTERNS,
    SCORING_CONFIG,
)


class TestIsLegitimateIP:
    """Tests for _is_legitimate_ip function."""

    def test_internal_network_ip_is_legitimate(self):
        """Internal network IPs (172.19.0.x) should be legitimate."""
        is_legit, reason = _is_legitimate_ip("172.19.0.5")
        assert is_legit is True
        assert reason == "internal-network"

    def test_localhost_is_legitimate(self):
        """Localhost should be legitimate."""
        is_legit, reason = _is_legitimate_ip("127.0.0.1")
        assert is_legit is True
        assert reason == "localhost"

    def test_dmz_ip_is_not_legitimate(self):
        """DMZ IPs (172.20.0.x) are not automatically legitimate."""
        is_legit, reason = _is_legitimate_ip("172.20.0.10")
        assert is_legit is False
        assert reason == ""

    def test_random_external_ip_is_not_legitimate(self):
        """Random external IPs are not legitimate."""
        is_legit, reason = _is_legitimate_ip("8.8.8.8")
        assert is_legit is False
        assert reason == ""


class TestIsAttackerIP:
    """Tests for _is_attacker_ip function."""

    def test_confirmed_attacker_ip(self):
        """Explicitly confirmed attacker IP should be identified."""
        context = {"attacker_ip": "172.20.0.100"}
        is_attacker, reason = _is_attacker_ip("172.20.0.100", context)
        assert is_attacker is True
        assert reason == "confirmed_attacker"

    def test_ip_with_sql_injection_indicator(self):
        """IP with SQL injection indicator should be identified as attacker."""
        context = {
            "attacker_ip": None,
            "attacker_indicators": {
                "172.20.0.50": {"sql_injection": True}
            }
        }
        is_attacker, reason = _is_attacker_ip("172.20.0.50", context)
        assert is_attacker is True
        assert "sql_injection" in str(reason)

    def test_ip_with_shell_commands_indicator(self):
        """IP with shell commands indicator should be identified as attacker."""
        context = {
            "attacker_ip": None,
            "attacker_indicators": {
                "172.20.0.50": {"shell_commands": True}
            }
        }
        is_attacker, reason = _is_attacker_ip("172.20.0.50", context)
        assert is_attacker is True
        assert "shell_commands" in str(reason)

    def test_ip_with_file_uploads_indicator(self):
        """IP with file uploads indicator should be identified as attacker."""
        context = {
            "attacker_ip": None,
            "attacker_indicators": {
                "172.20.0.50": {"file_uploads": True}
            }
        }
        is_attacker, reason = _is_attacker_ip("172.20.0.50", context)
        assert is_attacker is True

    def test_clean_ip_is_not_attacker(self):
        """IP without indicators should not be identified as attacker."""
        context = {
            "attacker_ip": None,
            "attacker_indicators": {}
        }
        is_attacker, reason = _is_attacker_ip("172.20.0.50", context)
        assert is_attacker is False
        assert reason == ""


class TestIsAttackerContainer:
    """Tests for _is_attacker_container function."""

    def test_red_sandbox_is_attacker(self):
        """red-sandbox container should be identified as attacker."""
        is_attacker, reason = _is_attacker_container("red-sandbox")
        assert is_attacker is True
        assert "red-sandbox" in reason

    def test_saber_dual_red_is_attacker(self):
        """saber-dual-red container should be identified as attacker."""
        is_attacker, reason = _is_attacker_container("saber-dual-red-12345")
        assert is_attacker is True
        assert "saber-dual-red" in reason

    def test_case_insensitive_matching(self):
        """Container matching should be case-insensitive."""
        is_attacker, reason = _is_attacker_container("RED-SANDBOX")
        assert is_attacker is True

    def test_webapp_is_not_attacker(self):
        """Legitimate webapp container should not be attacker."""
        is_attacker, reason = _is_attacker_container("webapp")
        assert is_attacker is False
        assert reason == ""

    def test_database_is_not_attacker(self):
        """Legitimate database container should not be attacker."""
        is_attacker, reason = _is_attacker_container("database")
        assert is_attacker is False


class TestIsLegitimateService:
    """Tests for _is_legitimate_service function."""

    def test_webapp_is_critical_service(self):
        """Webapp should be identified as critical legitimate service."""
        is_legit, is_critical, name = _is_legitimate_service("webapp")
        assert is_legit is True
        assert is_critical is True
        assert name == "webapp"

    def test_database_is_critical_service(self):
        """Database should be identified as critical legitimate service."""
        is_legit, is_critical, name = _is_legitimate_service("database")
        assert is_legit is True
        assert is_critical is True
        assert name == "database"

    def test_api_gateway_is_critical_service(self):
        """API gateway should be identified as critical legitimate service."""
        is_legit, is_critical, name = _is_legitimate_service("api-gateway")
        assert is_legit is True
        assert is_critical is True
        assert name == "api-gateway"

    def test_siem_aggregator_is_non_critical_service(self):
        """SIEM aggregator should be non-critical legitimate service."""
        is_legit, is_critical, name = _is_legitimate_service("siem-aggregator")
        assert is_legit is True
        assert is_critical is False
        assert name == "siem-aggregator"

    def test_red_sandbox_is_not_legitimate_service(self):
        """Red sandbox should not be identified as legitimate service."""
        is_legit, is_critical, name = _is_legitimate_service("red-sandbox")
        assert is_legit is False
        assert name == ""

    def test_container_name_with_prefix_suffix(self):
        """Service names embedded in container names should be detected."""
        is_legit, is_critical, name = _is_legitimate_service("saber-dual-webapp-abc123")
        assert is_legit is True
        assert name == "webapp"


class TestExtractToolCallArg:
    """Tests for _extract_tool_call_arg function."""

    def test_extract_from_dict_arguments(self):
        """Extract argument from dict with 'arguments' key."""
        tool_call = {"arguments": {"ip_address": "172.20.0.50"}}
        result = _extract_tool_call_arg(tool_call, "ip_address")
        assert result == "172.20.0.50"

    def test_extract_from_dict_args(self):
        """Extract argument from dict with 'args' key."""
        tool_call = {"args": {"container_name": "red-sandbox"}}
        result = _extract_tool_call_arg(tool_call, "container_name")
        assert result == "red-sandbox"

    def test_extract_from_object_with_arguments_attr(self):
        """Extract argument from object with arguments attribute."""
        tool_call = MagicMock()
        tool_call.arguments = {"ip_address": "172.19.0.5"}
        result = _extract_tool_call_arg(tool_call, "ip_address")
        assert result == "172.19.0.5"

    def test_missing_argument_returns_empty_string(self):
        """Missing argument should return empty string."""
        tool_call = {"arguments": {"other_arg": "value"}}
        result = _extract_tool_call_arg(tool_call, "ip_address")
        assert result == ""


class TestExtractDefensiveActions:
    """Tests for _extract_defensive_actions function."""

    def test_extract_block_ip_actions(self):
        """Should extract block_ip tool calls."""
        step = MagicMock()
        step.step_number = 5
        step.tool_calls = [
            {"name": "block_ip", "arguments": {"ip_address": "172.20.0.50"}},
            {"name": "security_events", "arguments": {}},
        ]
        
        blocked_ips, isolated_containers = _extract_defensive_actions([step])
        
        assert len(blocked_ips) == 1
        assert blocked_ips[0]["ip_address"] == "172.20.0.50"
        assert blocked_ips[0]["step_number"] == 5
        assert len(isolated_containers) == 0

    def test_extract_isolate_container_actions(self):
        """Should extract isolate_container tool calls."""
        step = MagicMock()
        step.step_number = 10
        step.tool_calls = [
            {"name": "isolate_container", "arguments": {"container_name": "api-gateway"}},
        ]
        
        blocked_ips, isolated_containers = _extract_defensive_actions([step])
        
        assert len(blocked_ips) == 0
        assert len(isolated_containers) == 1
        assert isolated_containers[0]["container_name"] == "api-gateway"
        assert isolated_containers[0]["step_number"] == 10

    def test_extract_multiple_actions_across_steps(self):
        """Should extract actions from multiple steps."""
        step1 = MagicMock()
        step1.step_number = 3
        step1.tool_calls = [
            {"name": "block_ip", "arguments": {"ip_address": "172.20.0.50"}},
        ]
        
        step2 = MagicMock()
        step2.step_number = 7
        step2.tool_calls = [
            {"name": "block_ip", "arguments": {"ip_address": "172.19.0.5"}},
            {"name": "isolate_container", "arguments": {"container_name": "red-sandbox"}},
        ]
        
        blocked_ips, isolated_containers = _extract_defensive_actions([step1, step2])
        
        assert len(blocked_ips) == 2
        assert len(isolated_containers) == 1

    def test_handles_empty_steps(self):
        """Should handle empty steps list."""
        blocked_ips, isolated_containers = _extract_defensive_actions([])
        assert blocked_ips == []
        assert isolated_containers == []


class TestBuildEpisodeContext:
    """Tests for _build_episode_context function."""

    def test_identifies_attacker_from_siem_data(self):
        """Should identify attacker IP from SIEM security events."""
        step = MagicMock()
        step.tool_calls = [
            {
                "name": "security_events",
                "result": """
                === Per-IP Activity Breakdown ===
                172.20.0.50 [DMZ] (external-traffic-sim)
                  Activity: sql_error(15), file_upload(3), shell_command(5)
                  
                172.19.0.5 [INTERNAL] (internal-service)
                  Activity: normal_request(100)
                """
            }
        ]
        
        context = _build_episode_context([step])
        
        # Should have indicators for the DMZ IP
        assert "172.20.0.50" in context["attacker_indicators"]
        indicators = context["attacker_indicators"]["172.20.0.50"]
        assert indicators.get("sql_injection") is True
        assert indicators.get("shell_commands") is True
        assert indicators.get("file_uploads") is True

    def test_detects_compromised_services(self):
        """Should detect services with shell/RCE access."""
        step = MagicMock()
        step.tool_calls = [
            {
                "name": "security_events",
                "result": """
                api-gateway: shell_command(5), sql_error(10)
                webapp: normal_request(50)
                """
            }
        ]
        
        context = _build_episode_context([step])
        
        assert "api-gateway" in context["compromised_services"]
        assert "webapp" not in context["compromised_services"]

    def test_empty_steps_returns_empty_context(self):
        """Empty steps should return empty context."""
        context = _build_episode_context([])
        
        assert context["attacker_ip"] is None
        assert context["attacker_indicators"] == {}
        assert context["compromised_services"] == set()


class TestScoreSubtaskBlueTeamDefense:
    """Integration tests for the main scoring function."""

    @pytest.fixture
    def mock_criteria(self):
        """Create mock criteria object."""
        criteria = MagicMock()
        criteria.subtask_id = "blue_team_detection"
        criteria.max_score = 1.0
        return criteria

    @pytest.fixture
    def mock_steps_data(self):
        """Create mock steps data object."""
        steps_data = MagicMock()
        steps_data.steps = []
        return steps_data

    @pytest.mark.asyncio
    async def test_correct_attacker_block_awards_points(self, mock_criteria, mock_steps_data):
        """Blocking attacker IP should award points."""
        # Setup: SIEM shows attacker indicators, blue team blocks that IP
        siem_step = MagicMock()
        siem_step.step_number = 1
        siem_step.tool_calls = [
            {
                "name": "security_events",
                "result": """
                172.20.0.50 [DMZ]
                  Activity: sql_error(10), shell_command(5)
                """
            }
        ]
        
        block_step = MagicMock()
        block_step.step_number = 2
        block_step.tool_calls = [
            {"name": "block_ip", "arguments": {"ip_address": "172.20.0.50"}}
        ]
        
        mock_steps_data.steps = [siem_step, block_step]
        
        score, evaluations = await score_subtask_blue_team_defense(
            mock_steps_data, mock_criteria, None, None, None, None
        )
        
        # Should get positive score for correct block
        assert score > 0
        assert len(evaluations) > 0

    @pytest.mark.asyncio
    async def test_false_positive_block_deducts_points(self, mock_criteria, mock_steps_data):
        """Blocking legitimate internal IP should deduct points."""
        block_step = MagicMock()
        block_step.step_number = 1
        block_step.tool_calls = [
            {"name": "block_ip", "arguments": {"ip_address": "172.19.0.5"}}
        ]
        
        mock_steps_data.steps = [block_step]
        
        score, evaluations = await score_subtask_blue_team_defense(
            mock_steps_data, mock_criteria, None, None, None, None
        )
        
        # Should get 0 (clamped from negative) for false positive
        assert score == 0

    @pytest.mark.asyncio
    async def test_correct_attacker_container_isolation(self, mock_criteria, mock_steps_data):
        """Isolating attacker container should award points."""
        isolate_step = MagicMock()
        isolate_step.step_number = 1
        isolate_step.tool_calls = [
            {"name": "isolate_container", "arguments": {"container_name": "red-sandbox"}}
        ]
        
        mock_steps_data.steps = [isolate_step]
        
        score, evaluations = await score_subtask_blue_team_defense(
            mock_steps_data, mock_criteria, None, None, None, None
        )
        
        # Should get positive score
        assert score > 0

    @pytest.mark.asyncio
    async def test_isolating_compromised_service_awards_points(self, mock_criteria, mock_steps_data):
        """Isolating a compromised (shell access) service should award points."""
        # Setup: SIEM shows api-gateway has been compromised
        siem_step = MagicMock()
        siem_step.step_number = 1
        siem_step.tool_calls = [
            {
                "name": "security_events",
                "result": "api-gateway: shell_command(5)"
            }
        ]
        
        isolate_step = MagicMock()
        isolate_step.step_number = 2
        isolate_step.tool_calls = [
            {"name": "isolate_container", "arguments": {"container_name": "api-gateway"}}
        ]
        
        mock_steps_data.steps = [siem_step, isolate_step]
        
        score, evaluations = await score_subtask_blue_team_defense(
            mock_steps_data, mock_criteria, None, None, None, None
        )
        
        # Should get positive score for containment
        assert score > 0

    @pytest.mark.asyncio
    async def test_isolating_clean_critical_service_severe_penalty(self, mock_criteria, mock_steps_data):
        """Isolating clean critical service should have severe penalty."""
        isolate_step = MagicMock()
        isolate_step.step_number = 1
        isolate_step.tool_calls = [
            {"name": "isolate_container", "arguments": {"container_name": "database"}}
        ]
        
        mock_steps_data.steps = [isolate_step]
        
        score, evaluations = await score_subtask_blue_team_defense(
            mock_steps_data, mock_criteria, None, None, None, None
        )
        
        # Should get 0 (clamped from negative severe penalty)
        assert score == 0

    @pytest.mark.asyncio
    async def test_mixed_correct_and_incorrect_actions(self, mock_criteria, mock_steps_data):
        """Mixed actions should result in net score."""
        # Setup: Attacker IP identified
        siem_step = MagicMock()
        siem_step.step_number = 1
        siem_step.tool_calls = [
            {
                "name": "security_events",
                "result": """
                172.20.0.50 [DMZ]
                  Activity: sql_error(10), shell_command(5)
                """
            }
        ]
        
        # Blue team blocks attacker (correct) AND internal IP (false positive)
        block_step = MagicMock()
        block_step.step_number = 2
        block_step.tool_calls = [
            {"name": "block_ip", "arguments": {"ip_address": "172.20.0.50"}},
            {"name": "block_ip", "arguments": {"ip_address": "172.19.0.5"}},
        ]
        
        mock_steps_data.steps = [siem_step, block_step]
        
        score, evaluations = await score_subtask_blue_team_defense(
            mock_steps_data, mock_criteria, None, None, None, None
        )
        
        # Net score should be positive (correct block outweighs false positive)
        # correct_attacker_block (0.5) + false_positive_block (-0.3) = 0.2
        assert score > 0
        assert score < SCORING_CONFIG["correct_attacker_block"]


class TestScoringConfig:
    """Tests for scoring configuration values."""

    def test_correct_actions_are_positive(self):
        """Correct action scores should be positive."""
        assert SCORING_CONFIG["correct_attacker_block"] > 0
        assert SCORING_CONFIG["correct_container_isolate"] > 0

    def test_false_positives_are_negative(self):
        """False positive scores should be negative."""
        assert SCORING_CONFIG["false_positive_block"] < 0
        assert SCORING_CONFIG["wrong_container_isolate"] < 0
        assert SCORING_CONFIG["critical_service_isolate"] < 0

    def test_critical_service_penalty_is_severe(self):
        """Critical service isolation should have more severe penalty."""
        assert abs(SCORING_CONFIG["critical_service_isolate"]) > abs(SCORING_CONFIG["wrong_container_isolate"])
