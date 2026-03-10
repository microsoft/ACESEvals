from test_helpers.tool_call_utils import get_tool_call, get_tool_response

from inspect_ai import Task, eval
from inspect_ai._util.text import (
    TRUNCATION_MARKER,
    TruncatedOutput,
    _adjust_utf8_boundary_left,
    _adjust_utf8_boundary_right,
    truncate_bytes,
    truncate_str,
    truncate_string_to_bytes,
)
from inspect_ai.dataset._dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.solver._solver import generate
from inspect_ai.solver._use_tools import use_tools
from inspect_ai.tool._tool import tool


def test_max_tool_output():
    @tool
    def output(size: int):
        async def execute():
            """
            Generate some output

            Returns:
                The output
            """
            return "x" * size

        return execute

    def mock_model():
        return get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="output",
                    tool_arguments={},
                ),
                ModelOutput.from_content(model="mockllm/model", content="content"),
            ],
        )

    task = Task(
        dataset=[
            Sample(
                input="Please call the output tool and then reply with its output in a normal assistant message."
            )
        ],
        solver=[use_tools(output(10)), generate()],
        config=GenerateConfig(max_tool_output=5),
    )

    def check_log(log: EvalLog, count: int, overflow=True):
        assert log.samples
        messages = log.samples[0].messages
        output_call = get_tool_call(messages, "output")
        assert output_call
        output_result = get_tool_response(messages, output_call)
        assert output_result
        if overflow:
            newline = "\n"
            assert f"{newline}{'x' * count}{newline}" in output_result.content
        else:
            assert "x" * count == output_result.content

    log = eval(task, mock_model())[0]
    check_log(log, 5)

    log = eval(task, mock_model(), max_tool_output=7)[0]
    check_log(log, 7)

    log = eval(task, mock_model(), max_tool_output=0)[0]
    check_log(log, 10, False)


def test_truncate_str_no_truncation_needed():
    """Test that truncate_str returns None when input fits within limit."""
    result = truncate_str("hello", 10)
    assert result is None

    result = truncate_str("test", 4)
    assert result is None

    result = truncate_str("", 5)
    assert result is None


def test_truncate_str_max_bytes_zero():
    """Test truncate_str with max_bytes=0 returns None (no truncation)."""
    result = truncate_str("hello", 0)
    assert result == TruncatedOutput("", 5)


def test_truncate_str_basic_truncation():
    """Test front-only truncation for ASCII strings when budget < marker length."""
    result = truncate_str("abcdefghij", 6)
    assert result is not None
    assert result.output == "abcdef"  # front-only: budget < marker length
    assert result.original_bytes == 10


def test_truncate_str_odd_max_bytes():
    """Test front-only truncation with odd max_bytes value."""
    result = truncate_str("abcdefghij", 5)
    assert result is not None
    assert result.output == "abcde"  # front-only: budget < marker length
    assert result.original_bytes == 10


def test_truncate_bytes_no_truncation_needed():
    """Test that truncate_bytes returns None when input fits within limit."""
    result = truncate_bytes(b"hello", 10)
    assert result is None

    result = truncate_bytes(b"test", 4)
    assert result is None

    result = truncate_bytes(b"", 5)
    assert result is None


def test_truncate_bytes_max_bytes_zero():
    result = truncate_bytes(b"hello", 0)
    assert result == TruncatedOutput("", 5)


def test_truncate_bytes_basic_truncation():
    """Test front-only truncation for bytes when budget < marker length."""
    result = truncate_bytes(b"abcdefghij", 6)
    assert result is not None
    assert result.output == "abcdef"  # front-only: budget < marker length
    assert result.original_bytes == 10


def test_truncate_bytes_odd_max_bytes():
    """Test front-only truncation with odd max_bytes value."""
    result = truncate_bytes(b"abcdefghij", 5)
    assert result is not None
    assert result.output == "abcde"  # front-only: budget < marker length
    assert result.original_bytes == 10


def test_both_functions_edge_cases():
    """Test edge cases for both functions."""
    # Empty input should return None regardless of max_bytes
    assert truncate_str("", 0) is None
    assert truncate_str("", 1) is None
    assert truncate_bytes(b"", 0) is None
    assert truncate_bytes(b"", 1) is None

    # max_bytes=0 truncates to empty string (internal helpers)
    assert truncate_str("a", 0) == TruncatedOutput("", 1)
    assert truncate_bytes(b"a", 0) == TruncatedOutput("", 1)


def test_truncate_string_to_bytes_no_truncation_needed():
    """Test that truncate_string_to_bytes returns None when input fits within limit."""
    result = truncate_string_to_bytes("hello", 10)
    assert result is None

    result = truncate_string_to_bytes("test", 4)
    assert result is None

    result = truncate_string_to_bytes("", 5)
    assert result is None


def test_truncate_string_to_bytes_zero_means_no_truncation():
    """Test that max_bytes=0 means no truncation for truncate_string_to_bytes."""
    result = truncate_string_to_bytes("hello", 0)
    assert result is None

    result = truncate_string_to_bytes("", 0)
    assert result is None


def test_truncate_string_to_bytes_utf8_characters():
    """Test truncation with UTF-8 characters like emoji."""
    # Test with emoji that might get broken by byte truncation
    result = truncate_string_to_bytes("🌍🌎🌏", 5)
    assert result is not None
    assert result.original_bytes == 12  # 3 emoji * 4 bytes each
    # The result should be valid (no assertion on exact output due to broken UTF-8)
    assert isinstance(result.output, str)


def test_truncate_string_to_bytes_mixed_content():
    """Test truncation with mixed ASCII and UTF-8."""
    result = truncate_string_to_bytes("Hello, 世界! 🌍", 10)
    assert result is not None
    # Just verify it returns something valid
    assert isinstance(result.output, str)
    assert result.original_bytes > 10


def test_middle_truncation_preserves_ends():
    """Test that middle truncation with marker preserves start and end content."""
    text = "start" + "x" * 100 + "end"
    result = truncate_str(text, 46)
    assert result is not None
    assert result.output.startswith("start")
    assert result.output.endswith("end")
    assert TRUNCATION_MARKER in result.output


# === Phase 1: Truncation Marker Tests ===


def test_truncation_marker_constant() -> None:
    """Verify TRUNCATION_MARKER constant exists and has expected value."""
    assert TRUNCATION_MARKER == "\n... [truncated] ...\n"
    # Marker is pure ASCII, so byte length == char length
    assert len(TRUNCATION_MARKER) == len(TRUNCATION_MARKER.encode("utf-8"))


def test_truncate_str_with_marker() -> None:
    """Verify marker is inserted for sufficiently large budgets."""
    text = "A" * 100
    marker_len = len(TRUNCATION_MARKER)
    max_bytes = marker_len + 28  # 28 chars of content
    result = truncate_str(text, max_bytes)
    assert result is not None
    assert TRUNCATION_MARKER in result.output
    assert len(result.output) <= max_bytes
    assert result.original_bytes == 100


def test_truncate_str_small_budget_no_marker() -> None:
    """Verify front-only truncation when budget < marker length."""
    marker_len = len(TRUNCATION_MARKER)
    text = "A" * 100
    result = truncate_str(text, marker_len - 1)
    assert result is not None
    assert TRUNCATION_MARKER not in result.output
    assert result.output == "A" * (marker_len - 1)
    assert len(result.output) <= marker_len - 1


def test_truncate_str_preserves_start_end_with_marker() -> None:
    """Verify that start and end content are preserved with marker."""
    text = "START" + "x" * 100 + "END"
    marker_len = len(TRUNCATION_MARKER)
    max_bytes = marker_len + 30  # 15 from each end
    result = truncate_str(text, max_bytes)
    assert result is not None
    assert result.output.startswith("START")
    assert result.output.endswith("END")
    assert TRUNCATION_MARKER in result.output
    assert len(result.output) <= max_bytes


def test_truncate_str_output_size_within_budget() -> None:
    """Verify len(result.output) <= max_bytes for various sizes."""
    text = "x" * 1000
    for max_bytes in [1, 5, 10, 20, 21, 22, 50, 100, 500]:
        result = truncate_str(text, max_bytes)
        assert result is not None
        assert len(result.output) <= max_bytes, (
            f"Failed for max_bytes={max_bytes}: got {len(result.output)}"
        )


def test_truncate_bytes_with_marker() -> None:
    """Verify marker is present in bytes truncation for large budgets."""
    data = b"A" * 100
    marker_len = len(TRUNCATION_MARKER.encode("utf-8"))
    max_bytes = marker_len + 28
    result = truncate_bytes(data, max_bytes)
    assert result is not None
    assert TRUNCATION_MARKER in result.output
    assert result.original_bytes == 100


def test_truncate_bytes_output_size_within_budget() -> None:
    """Verify the byte-level output constraint for truncate_bytes."""
    data = b"x" * 1000
    marker_bytes = TRUNCATION_MARKER.encode("utf-8")
    for max_bytes in [1, 5, 10, len(marker_bytes), len(marker_bytes) + 1, 50, 100]:
        result = truncate_bytes(data, max_bytes)
        assert result is not None
        # Re-encode to check byte length
        result_bytes = result.output.encode("utf-8")
        assert len(result_bytes) <= max_bytes, (
            f"Failed for max_bytes={max_bytes}: got {len(result_bytes)}"
        )


# === Phase 2: UTF-8 Boundary Safety Tests ===


def test_adjust_utf8_boundary_left_at_char_start() -> None:
    """No adjustment needed when position is at a character boundary."""
    # H(0) e(1) l(2) l(3) o(4) (5) E4(6) B8(7) 96(8) E7(9) 95(10) 8C(11)
    data = "Hello 世界".encode("utf-8")
    # Position 6 is the start of '世' (E4) — a lead byte, not a continuation
    assert _adjust_utf8_boundary_left(data, 6) == 6


def test_adjust_utf8_boundary_left_in_middle() -> None:
    """Adjustment needed when position is in the middle of a multi-byte char."""
    data = "Hello 世界".encode("utf-8")
    # Position 7: B8 is a continuation byte of '世'
    assert _adjust_utf8_boundary_left(data, 7) == 6
    # Position 8: 96 is also a continuation byte of '世'
    assert _adjust_utf8_boundary_left(data, 8) == 6


def test_adjust_utf8_boundary_left_at_zero() -> None:
    """Position 0 should always return 0."""
    data = "🌍".encode("utf-8")
    assert _adjust_utf8_boundary_left(data, 0) == 0


def test_adjust_utf8_boundary_right_at_char_start() -> None:
    """No adjustment needed when position is at a character boundary."""
    data = "Hello 世界".encode("utf-8")
    # Position 6 is the start of '世' (E4) — not a continuation byte
    assert _adjust_utf8_boundary_right(data, 6) == 6


def test_adjust_utf8_boundary_right_in_middle() -> None:
    """Adjustment needed when position is at a continuation byte."""
    data = "Hello 世界".encode("utf-8")
    # Position 7: B8 is continuation → skip to position 9 (start of '界')
    assert _adjust_utf8_boundary_right(data, 7) == 9
    # Position 8: 96 is continuation → skip to 9
    assert _adjust_utf8_boundary_right(data, 8) == 9


def test_adjust_utf8_boundary_right_at_end() -> None:
    """Position at end of data should return len(data)."""
    data = b"abc"
    assert _adjust_utf8_boundary_right(data, 3) == 3


def test_truncate_bytes_utf8_no_broken_chars() -> None:
    """Verify truncate_bytes produces valid UTF-8 (no broken characters)."""
    # 3 emojis = 12 bytes
    emoji_data = "🌍🌎🌏".encode("utf-8")
    for max_bytes in range(1, 12):
        result = truncate_bytes(emoji_data, max_bytes)
        if result is not None:
            # Should decode cleanly without replacement chars
            result.output.encode("utf-8").decode("utf-8")  # roundtrip
            assert "\ufffd" not in result.output, (
                f"Replacement char at max_bytes={max_bytes}"
            )


# === Phase 3: CircularByteBuffer UTF-8 Safety Tests ===


def test_circular_byte_buffer_utf8_safety() -> None:
    """Test that CircularByteBuffer skips leading continuation bytes after front-truncation."""
    from inspect_ai.util._subprocess import CircularByteBuffer

    buf = CircularByteBuffer(max_bytes=6)
    # Write 3 emojis (12 bytes) in one chunk to force single-chunk front-truncation
    buf.write("🌍🌍🌍".encode("utf-8"))
    result = buf.getvalue()
    # Should be valid UTF-8 — decode with strict errors should not raise
    decoded = result.decode("utf-8")
    assert len(result) <= 6
    # Should not contain replacement characters
    assert "\ufffd" not in decoded


def test_circular_byte_buffer_utf8_single_chunk_overflow() -> None:
    """Test CircularByteBuffer UTF-8 safety with 2-byte chars causing single-chunk overflow."""
    from inspect_ai.util._subprocess import CircularByteBuffer

    buf = CircularByteBuffer(max_bytes=5)
    # Write 3 two-byte chars in one chunk: é(C3 A9) è(C3 A8) ê(C3 AA) = 6 bytes
    buf.write("éèê".encode("utf-8"))
    result = buf.getvalue()
    decoded = result.decode("utf-8")
    assert len(result) <= 5
    assert "\ufffd" not in decoded


def test_circular_byte_buffer_multi_chunk_utf8() -> None:
    """Test that multi-chunk discard handles orphan continuation bytes."""
    from inspect_ai.util._subprocess import CircularByteBuffer

    buf = CircularByteBuffer(max_bytes=4)
    buf.write(b"AB\xe4")  # 3 bytes; contains start of 3-byte char
    buf.write(b"\xb8\x96CD")  # 4 bytes; starts with continuation bytes
    # Total 7 > 4, first chunk should be discarded
    # After discard, remaining is b'\xb8\x96CD' — continuation bytes at start
    # UTF-8 safety should skip them, leaving b'CD'
    result = buf.getvalue()
    decoded = result.decode("utf-8")
    assert "\ufffd" not in decoded


def test_truncate_bytes_budget_with_multibyte() -> None:
    """Verify byte budget holds for multi-byte character input."""
    emoji_data = "🌍🌎🌏🌐🌑".encode("utf-8")  # 20 bytes
    for budget in range(1, 25):
        result = truncate_bytes(emoji_data, budget)
        if result is not None:
            result_bytes = result.output.encode("utf-8")
            assert len(result_bytes) <= budget, (
                f"Budget {budget} violated: got {len(result_bytes)}"
            )


def test_truncate_bytes_no_content_fallback() -> None:
    """When UTF-8 adjustments eat all content, should fallback to front-only."""
    # 6 four-byte emojis = 24 bytes, budget just above marker length (21)
    emoji_data = "🌍🌎🌏🌐🌑🌒".encode("utf-8")  # 24 bytes
    result = truncate_bytes(emoji_data, 22)  # marker is 21 bytes, 1 byte for content
    assert result is not None
    # Should have at least some content, not just the marker
    marker = "\n... [truncated] ...\n"
    # Either has marker with content, or is front-only with content
    assert len(result.output) > 0
    # The result must contain actual content, not just the marker
    content_without_marker = result.output.replace(marker, "")
    assert len(content_without_marker) > 0


def test_truncate_bytes_invalid_utf8_budget() -> None:
    """Verify byte budget is never violated even with invalid UTF-8 input."""
    # b'\xc3' is a leading byte of a 2-byte sequence with no continuation
    invalid_data = b"\xc3" * 10
    for budget in range(1, 15):
        result = truncate_bytes(invalid_data, budget)
        if result is not None:
            result_bytes = result.output.encode("utf-8")
            assert len(result_bytes) <= budget, (
                f"Budget {budget} violated: got {len(result_bytes)}"
            )

    # Mixed valid and invalid bytes
    mixed_data = b"A\x80\x80B\xc3C\xff\xfeDE"
    for budget in range(1, 15):
        result = truncate_bytes(mixed_data, budget)
        if result is not None:
            result_bytes = result.output.encode("utf-8")
            assert len(result_bytes) <= budget, (
                f"Budget {budget} violated: got {len(result_bytes)}"
            )
