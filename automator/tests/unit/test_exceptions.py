"""Unit tests for custom exception classes."""

import pytest

from src.exceptions import (
    ApplyError,
    AutomatorError,
    ConfigError,
    ExtractionError,
    GDocsError,
    PipelineError,
    ScoringError,
    SMSError,
    TailoringError,
    VisionAgentError,
)


class TestAutomatorErrorBase:
    """Tests for the base AutomatorError class."""

    def test_message_and_job_id(self) -> None:
        err = AutomatorError("something broke", job_id="12345")
        assert err.message == "something broke"
        assert err.job_id == "12345"
        assert str(err) == "something broke"

    def test_job_id_defaults_to_none(self) -> None:
        err = AutomatorError("no job context")
        assert err.job_id is None

    def test_repr(self) -> None:
        err = AutomatorError("msg", job_id="99")
        assert repr(err) == "AutomatorError(message='msg', job_id='99')"

    def test_is_exception(self) -> None:
        with pytest.raises(AutomatorError):
            raise AutomatorError("test")


class TestSubclassInheritance:
    """All domain exceptions inherit from AutomatorError."""

    @pytest.mark.parametrize(
        "exc_class",
        [
            ExtractionError,
            ScoringError,
            TailoringError,
            ApplyError,
            VisionAgentError,
            GDocsError,
            SMSError,
            ConfigError,
            PipelineError,
        ],
    )
    def test_subclass_is_automator_error(self, exc_class: type) -> None:
        assert issubclass(exc_class, AutomatorError)

    @pytest.mark.parametrize(
        "exc_class",
        [
            ExtractionError,
            ScoringError,
            TailoringError,
            ApplyError,
            VisionAgentError,
            SMSError,
            ConfigError,
            PipelineError,
        ],
    )
    def test_subclass_carries_job_id_and_message(self, exc_class: type) -> None:
        err = exc_class("failed", job_id="abc")
        assert err.message == "failed"
        assert err.job_id == "abc"

    @pytest.mark.parametrize(
        "exc_class",
        [
            ExtractionError,
            ScoringError,
            TailoringError,
            ApplyError,
            VisionAgentError,
            SMSError,
            ConfigError,
            PipelineError,
        ],
    )
    def test_catchable_as_automator_error(self, exc_class: type) -> None:
        with pytest.raises(AutomatorError):
            raise exc_class("catch me", job_id="xyz")


class TestGDocsError:
    """GDocsError has an additional authorization_expired attribute."""

    def test_authorization_expired_defaults_false(self) -> None:
        err = GDocsError("timeout", job_id="111")
        assert err.authorization_expired is False

    def test_authorization_expired_true(self) -> None:
        err = GDocsError("auth failed", job_id="222", authorization_expired=True)
        assert err.authorization_expired is True
        assert err.message == "auth failed"
        assert err.job_id == "222"

    def test_repr_includes_authorization_expired(self) -> None:
        err = GDocsError("expired", job_id="333", authorization_expired=True)
        assert "authorization_expired=True" in repr(err)

    def test_is_automator_error(self) -> None:
        with pytest.raises(AutomatorError):
            raise GDocsError("test", authorization_expired=True)
