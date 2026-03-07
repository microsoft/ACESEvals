import pytest

from inspect_ai.util._limit import (
    LimitExceededError,
    check_tool_call_limit,
    record_tool_call_usage,
    tool_call_limit,
)


def test_can_record_tool_call_usage_with_no_active_limits() -> None:
    record_tool_call_usage(1)


def test_can_check_tool_call_limit_with_no_active_limits() -> None:
    check_tool_call_limit()


def test_validates_limit_parameter() -> None:
    with pytest.raises(ValueError):
        tool_call_limit(-1)


def test_can_create_with_none_limit() -> None:
    with tool_call_limit(None):
        _consume_tool_calls(10)


def test_can_create_with_zero_limit() -> None:
    with tool_call_limit(0):
        pass


def test_does_not_raise_error_when_limit_not_exceeded() -> None:
    _consume_tool_calls(10)

    with tool_call_limit(10):
        _consume_tool_calls(10)


def test_raises_error_when_limit_exceeded() -> None:
    with tool_call_limit(5) as limit:
        with pytest.raises(LimitExceededError) as exc_info:
            _consume_tool_calls(6)

    assert exc_info.value.type == "tool_call"
    assert exc_info.value.value == 6
    assert exc_info.value.limit == 5
    assert exc_info.value.source is limit


def test_raises_error_when_limit_exceeded_incrementally() -> None:
    with tool_call_limit(5):
        _consume_tool_calls(3)
        with pytest.raises(LimitExceededError):
            _consume_tool_calls(3)


def test_can_get_and_update_limit_value() -> None:
    limit = tool_call_limit(5)
    assert limit.limit == 5

    with limit:
        _consume_tool_calls(3)

        limit.limit = 10
        _consume_tool_calls(7)

        limit.limit = 5

        with pytest.raises(LimitExceededError):
            check_tool_call_limit()

        limit.limit = None
        _consume_tool_calls(100)

    assert limit.limit is None


def test_can_get_usage() -> None:
    limit = tool_call_limit(100)
    assert limit.usage == 0

    with limit:
        _consume_tool_calls(5)
        assert limit.usage == 5

    assert limit.usage == 5


def test_usage_tracks_across_multiple_records() -> None:
    with tool_call_limit(100) as limit:
        _consume_tool_calls(3)
        _consume_tool_calls(2)
        _consume_tool_calls(5)
        assert limit.usage == 10


def test_nested_limits_inner_triggered() -> None:
    outer = tool_call_limit(50)
    inner = tool_call_limit(5)

    with outer:
        _consume_tool_calls(3)
        with inner:
            with pytest.raises(LimitExceededError) as exc_info:
                _consume_tool_calls(6)
            assert exc_info.value.source is inner
            assert exc_info.value.limit == 5

    assert outer.usage == 9


def test_nested_limits_outer_triggered() -> None:
    outer = tool_call_limit(5)
    inner = tool_call_limit(50)

    with outer:
        with inner:
            with pytest.raises(LimitExceededError) as exc_info:
                _consume_tool_calls(6)
            # outer limit should trigger first (checked root to leaf)
            assert exc_info.value.source is outer
            assert exc_info.value.limit == 5


def test_out_of_scope_usage_not_counted() -> None:
    """Tool calls recorded outside a limit context are not counted."""
    _consume_tool_calls(100)
    with tool_call_limit(5):
        _consume_tool_calls(5)


def test_context_manager_reuse_prevention() -> None:
    """A tool call limit context manager cannot be re-entered."""
    limit = tool_call_limit(10)
    with limit:
        pass
    with pytest.raises(RuntimeError):
        with limit:
            pass


def test_batch_recording() -> None:
    """Recording multiple tool calls in one call."""
    with tool_call_limit(10) as limit:
        record_tool_call_usage(5)
        assert limit.usage == 5
        record_tool_call_usage(3)
        assert limit.usage == 8


def test_zero_limit_fails_on_first_call() -> None:
    with tool_call_limit(0):
        with pytest.raises(LimitExceededError):
            _consume_tool_calls(1)


def _consume_tool_calls(count: int) -> None:
    record_tool_call_usage(count)
    check_tool_call_limit()
