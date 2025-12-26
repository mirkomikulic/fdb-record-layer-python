"""Tests for logging utilities."""

import logging
from unittest.mock import MagicMock

import pytest

from fdb_record_layer.utils.logging import (
    LogContext,
    StructuredFormatter,
    configure_logging,
    get_logger,
    log_operation,
    log_timing,
)


class TestGetLogger:
    """Tests for get_logger function."""

    def test_returns_logger(self):
        """Test get_logger returns a Logger instance."""
        logger = get_logger("test")
        assert isinstance(logger, logging.Logger)

    def test_logger_name_hierarchy(self):
        """Test logger name includes package prefix."""
        logger = get_logger("test.module")
        assert logger.name == "fdb_record_layer.test.module"

    def test_different_names_different_loggers(self):
        """Test different names return different loggers."""
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")
        assert logger1 is not logger2


class TestLogContext:
    """Tests for LogContext."""

    def test_empty_context(self):
        """Test empty context."""
        ctx = LogContext()
        assert ctx.fields == {}

    def test_context_with_fields(self):
        """Test context with initial fields."""
        ctx = LogContext(fields={"user": "test", "action": "save"})
        assert ctx.fields["user"] == "test"
        assert ctx.fields["action"] == "save"

    def test_with_field(self):
        """Test with_field creates new context."""
        ctx1 = LogContext(fields={"user": "test"})
        ctx2 = ctx1.with_field("action", "save")

        assert "action" not in ctx1.fields
        assert ctx2.fields["user"] == "test"
        assert ctx2.fields["action"] == "save"

    def test_with_fields(self):
        """Test with_fields creates new context with multiple fields."""
        ctx1 = LogContext(fields={"user": "test"})
        ctx2 = ctx1.with_fields(action="save", status="success")

        assert "action" not in ctx1.fields
        assert ctx2.fields["action"] == "save"
        assert ctx2.fields["status"] == "success"

    def test_log_method(self):
        """Test log method calls logger correctly."""
        logger = MagicMock()
        ctx = LogContext(fields={"user": "test"})

        ctx.log(logger, "info", "Test message", extra_field="value")

        logger.info.assert_called_once()
        args, kwargs = logger.info.call_args
        assert args[0] == "Test message"
        assert kwargs["extra"]["user"] == "test"
        assert kwargs["extra"]["extra_field"] == "value"


class TestStructuredFormatter:
    """Tests for StructuredFormatter."""

    @pytest.fixture
    def formatter(self) -> StructuredFormatter:
        """Create a formatter for testing."""
        return StructuredFormatter()

    def test_basic_format(self, formatter: StructuredFormatter):
        """Test basic log formatting."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert "Test message" in result
        assert "INFO" in result

    def test_format_with_extra_fields(self, formatter: StructuredFormatter):
        """Test formatting with extra fields."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.custom_field = "custom_value"
        record.another_field = 123

        result = formatter.format(record)
        assert "custom_field=custom_value" in result
        assert "another_field=123" in result

    def test_format_without_extra_fields(self):
        """Test formatting with include_extra=False."""
        formatter = StructuredFormatter(include_extra=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.custom_field = "custom_value"

        result = formatter.format(record)
        assert "custom_field" not in result


class TestLogOperation:
    """Tests for log_operation decorator."""

    @pytest.fixture
    def logger(self) -> logging.Logger:
        """Create a mock logger."""
        return MagicMock(spec=logging.Logger)

    def test_sync_function(self, logger):
        """Test decorator with sync function."""

        @log_operation(logger, "test_op")
        def my_func(x: int) -> int:
            return x * 2

        result = my_func(5)
        assert result == 10
        assert logger.debug.called

    @pytest.mark.asyncio
    async def test_async_function(self, logger):
        """Test decorator with async function."""

        @log_operation(logger, "test_op")
        async def my_func(x: int) -> int:
            return x * 2

        result = await my_func(5)
        assert result == 10
        assert logger.debug.called

    @pytest.mark.asyncio
    async def test_logs_on_success(self, logger):
        """Test decorator logs on success."""

        @log_operation(logger, "test_op")
        async def my_func() -> str:
            return "success"

        await my_func()

        # Should log start and completion
        assert logger.debug.call_count >= 2

    @pytest.mark.asyncio
    async def test_logs_on_failure(self, logger):
        """Test decorator logs on failure."""

        @log_operation(logger, "test_op")
        async def my_func():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            await my_func()

        # Should log warning on failure
        assert logger.warning.called

    @pytest.mark.asyncio
    async def test_logs_args_when_enabled(self, logger):
        """Test decorator logs args when enabled."""

        @log_operation(logger, "test_op", log_args=True)
        async def my_func(x: int, y: str) -> None:
            pass

        await my_func(1, "test")

        # Check that args were logged
        call_args = logger.debug.call_args_list[0]
        extra = call_args[1].get("extra", {})
        assert "args" in extra


class TestLogTiming:
    """Tests for log_timing context manager."""

    def test_logs_timing(self):
        """Test log_timing logs operation timing."""
        logger = MagicMock(spec=logging.Logger)

        with log_timing(logger, "test_op"):
            pass

        logger.log.assert_called_once()
        call_args = logger.log.call_args
        assert "duration_ms" in call_args[1]["extra"]

    def test_logs_on_exception(self):
        """Test log_timing logs on exception."""
        logger = MagicMock(spec=logging.Logger)

        with pytest.raises(ValueError):
            with log_timing(logger, "test_op"):
                raise ValueError("Test error")

        logger.warning.assert_called_once()
        call_args = logger.warning.call_args
        assert "error" in call_args[1]["extra"]

    def test_includes_extra_fields(self):
        """Test log_timing includes extra fields."""
        logger = MagicMock(spec=logging.Logger)

        with log_timing(logger, "test_op", batch_size=100, table="users"):
            pass

        call_args = logger.log.call_args
        extra = call_args[1]["extra"]
        assert extra["batch_size"] == 100
        assert extra["table"] == "users"


class TestConfigureLogging:
    """Tests for configure_logging function."""

    def test_configure_with_defaults(self):
        """Test configure_logging with defaults."""
        # Should not raise
        configure_logging()

    def test_configure_with_custom_level(self):
        """Test configure_logging with custom level."""
        configure_logging(level=logging.DEBUG)

    def test_configure_with_custom_handler(self):
        """Test configure_logging with custom handler."""
        handler = logging.StreamHandler()
        configure_logging(handler=handler)

    def test_configure_with_structured_false(self):
        """Test configure_logging without structured formatting."""
        configure_logging(structured=False)
