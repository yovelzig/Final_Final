"""Unit tests for Phase G2A1 Live Research provider configuration
(`infrastructure.live_research.config`). Constructing any of these
settings classes - enabled or disabled - never makes a network call and
never requires real environment variables; tests always pass explicit
constructor kwargs so a developer's local `.env` cannot influence results.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stock_research_core.infrastructure.live_research.config import PerplexitySearchSettings, SecEdgarSettings

_FAKE_PERPLEXITY_KEY = "pplx-test-only-not-a-real-secret-abc123"
_VALID_SEC_USER_AGENT = "FinQuest Research research@example.com"


def _perplexity(**overrides: object) -> PerplexitySearchSettings:
    return PerplexitySearchSettings(_env_file=None, **overrides)


def _sec(**overrides: object) -> SecEdgarSettings:
    return SecEdgarSettings(_env_file=None, **overrides)


class TestPerplexityDefaults:
    def test_disabled_by_default(self) -> None:
        assert _perplexity().live_research_perplexity_enabled is False

    def test_disabled_settings_require_no_api_key(self) -> None:
        settings = _perplexity(live_research_perplexity_api_key="")
        assert settings.live_research_perplexity_api_key.get_secret_value() == ""

    def test_default_base_url_is_https(self) -> None:
        assert _perplexity().live_research_perplexity_base_url.startswith("https://")

    def test_default_max_results(self) -> None:
        assert _perplexity().live_research_perplexity_max_results == 10


class TestPerplexityEnabledValidation:
    def test_enabled_requires_api_key(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_enabled=True, live_research_perplexity_api_key="")

    def test_enabled_with_api_key_and_https_succeeds(self) -> None:
        settings = _perplexity(
            live_research_perplexity_enabled=True, live_research_perplexity_api_key=_FAKE_PERPLEXITY_KEY
        )
        assert settings.live_research_perplexity_enabled is True

    def test_enabled_requires_https_base_url(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(
                live_research_perplexity_enabled=True,
                live_research_perplexity_api_key=_FAKE_PERPLEXITY_KEY,
                live_research_perplexity_base_url="http://api.perplexity.ai",
            )

    def test_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_timeout_seconds=0)
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_timeout_seconds=-1)

    def test_timeout_must_be_finite(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_timeout_seconds=float("inf"))

    @pytest.mark.parametrize("value", [1, 20])
    def test_max_results_bounds_accepted(self, value: int) -> None:
        assert _perplexity(live_research_perplexity_max_results=value).live_research_perplexity_max_results == value

    @pytest.mark.parametrize("value", [0, 21])
    def test_max_results_bounds_rejected(self, value: int) -> None:
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_max_results=value)

    def test_max_tokens_must_be_positive_and_bounded(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_max_tokens=0)
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_max_tokens=1_000_000)

    def test_max_tokens_per_page_must_be_positive_and_bounded(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_max_tokens_per_page=0)
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_max_tokens_per_page=1_000_000)

    def test_api_key_does_not_appear_in_repr(self) -> None:
        settings = _perplexity(live_research_perplexity_api_key=_FAKE_PERPLEXITY_KEY)
        assert _FAKE_PERPLEXITY_KEY not in repr(settings)
        assert _FAKE_PERPLEXITY_KEY not in str(settings)

    def test_secret_does_not_appear_in_validation_error(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _perplexity(
                live_research_perplexity_enabled=True,
                live_research_perplexity_api_key=_FAKE_PERPLEXITY_KEY,
                live_research_perplexity_base_url="http://api.perplexity.ai",
            )
        assert _FAKE_PERPLEXITY_KEY not in str(exc_info.value)

    def test_whitespace_only_api_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_api_key="   ")

    def test_api_key_is_stripped_and_stored(self) -> None:
        settings = _perplexity(live_research_perplexity_api_key=f"  {_FAKE_PERPLEXITY_KEY}  ")
        assert settings.live_research_perplexity_api_key.get_secret_value() == _FAKE_PERPLEXITY_KEY

    def test_enabled_base_url_whitespace_is_stripped(self) -> None:
        settings = _perplexity(
            live_research_perplexity_enabled=True,
            live_research_perplexity_api_key=_FAKE_PERPLEXITY_KEY,
            live_research_perplexity_base_url="  https://api.perplexity.ai  ",
        )
        assert settings.live_research_perplexity_base_url == "https://api.perplexity.ai"

    def test_enabled_base_url_trailing_slash_removed(self) -> None:
        settings = _perplexity(
            live_research_perplexity_enabled=True,
            live_research_perplexity_api_key=_FAKE_PERPLEXITY_KEY,
            live_research_perplexity_base_url="https://api.perplexity.ai/",
        )
        assert settings.live_research_perplexity_base_url == "https://api.perplexity.ai"

    def test_enabled_base_url_with_username_password_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(
                live_research_perplexity_enabled=True,
                live_research_perplexity_api_key=_FAKE_PERPLEXITY_KEY,
                live_research_perplexity_base_url="https://user:pass@api.perplexity.ai",
            )

    def test_enabled_base_url_with_query_component_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(
                live_research_perplexity_enabled=True,
                live_research_perplexity_api_key=_FAKE_PERPLEXITY_KEY,
                live_research_perplexity_base_url="https://api.perplexity.ai?x=1",
            )

    def test_enabled_base_url_with_fragment_component_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(
                live_research_perplexity_enabled=True,
                live_research_perplexity_api_key=_FAKE_PERPLEXITY_KEY,
                live_research_perplexity_base_url="https://api.perplexity.ai#frag",
            )

    def test_max_tokens_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_max_tokens=True)

    def test_max_tokens_float_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_max_tokens=100.0)

    def test_max_tokens_per_page_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_max_tokens_per_page=True)

    def test_max_tokens_per_page_float_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _perplexity(live_research_perplexity_max_tokens_per_page=100.0)


class TestSecDefaults:
    def test_disabled_by_default(self) -> None:
        assert _sec().live_research_sec_enabled is False

    def test_disabled_settings_require_no_user_agent(self) -> None:
        assert _sec(live_research_sec_user_agent="").live_research_sec_user_agent == ""

    def test_default_base_url_is_https(self) -> None:
        assert _sec().live_research_sec_base_url.startswith("https://")

    def test_default_requests_per_second(self) -> None:
        assert _sec().live_research_sec_requests_per_second == 5.0


class TestSecEnabledValidation:
    def test_enabled_requires_user_agent(self) -> None:
        with pytest.raises(ValidationError):
            _sec(live_research_sec_enabled=True, live_research_sec_user_agent="")

    def test_enabled_requires_declared_identity_and_contact(self) -> None:
        with pytest.raises(ValidationError):
            _sec(live_research_sec_enabled=True, live_research_sec_user_agent="justonetoken")
        with pytest.raises(ValidationError):
            _sec(live_research_sec_enabled=True, live_research_sec_user_agent="My Company NoContactInfo")

    def test_enabled_with_declared_user_agent_succeeds(self) -> None:
        settings = _sec(live_research_sec_enabled=True, live_research_sec_user_agent=_VALID_SEC_USER_AGENT)
        assert settings.live_research_sec_enabled is True

    def test_enabled_requires_https_base_url(self) -> None:
        with pytest.raises(ValidationError):
            _sec(
                live_research_sec_enabled=True,
                live_research_sec_user_agent=_VALID_SEC_USER_AGENT,
                live_research_sec_base_url="http://data.sec.gov",
            )

    def test_timeout_must_be_positive_and_finite(self) -> None:
        with pytest.raises(ValidationError):
            _sec(live_research_sec_timeout_seconds=0)
        with pytest.raises(ValidationError):
            _sec(live_research_sec_timeout_seconds=float("nan"))

    def test_requests_per_second_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            _sec(live_research_sec_requests_per_second=0)
        with pytest.raises(ValidationError):
            _sec(live_research_sec_requests_per_second=-1)

    def test_requests_per_second_must_be_finite(self) -> None:
        with pytest.raises(ValidationError):
            _sec(live_research_sec_requests_per_second=float("inf"))

    def test_requests_per_second_cannot_exceed_ten(self) -> None:
        assert _sec(live_research_sec_requests_per_second=10.0).live_research_sec_requests_per_second == 10.0
        with pytest.raises(ValidationError):
            _sec(live_research_sec_requests_per_second=10.1)

    def test_user_agent_does_not_appear_in_validation_error_message(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            _sec(
                live_research_sec_enabled=True,
                live_research_sec_user_agent=_VALID_SEC_USER_AGENT,
                live_research_sec_base_url="http://data.sec.gov",
            )
        # The base-url error must not embed the (non-secret, but unrelated) User-Agent value.
        assert _VALID_SEC_USER_AGENT not in str(exc_info.value)

    def test_user_agent_is_stripped_and_stored(self) -> None:
        settings = _sec(live_research_sec_user_agent=f"  {_VALID_SEC_USER_AGENT}  ")
        assert settings.live_research_sec_user_agent == _VALID_SEC_USER_AGENT

    def test_oversized_user_agent_rejected(self) -> None:
        oversized = _VALID_SEC_USER_AGENT + " " + ("x" * 250)
        with pytest.raises(ValidationError):
            _sec(live_research_sec_user_agent=oversized)

    def test_user_agent_with_control_character_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _sec(live_research_sec_user_agent=_VALID_SEC_USER_AGENT + "\x00")

    def test_enabled_base_url_whitespace_is_stripped(self) -> None:
        settings = _sec(
            live_research_sec_enabled=True,
            live_research_sec_user_agent=_VALID_SEC_USER_AGENT,
            live_research_sec_base_url="  https://data.sec.gov  ",
        )
        assert settings.live_research_sec_base_url == "https://data.sec.gov"

    def test_enabled_base_url_trailing_slash_removed(self) -> None:
        settings = _sec(
            live_research_sec_enabled=True,
            live_research_sec_user_agent=_VALID_SEC_USER_AGENT,
            live_research_sec_base_url="https://data.sec.gov/",
        )
        assert settings.live_research_sec_base_url == "https://data.sec.gov"

    def test_enabled_base_url_with_username_password_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _sec(
                live_research_sec_enabled=True,
                live_research_sec_user_agent=_VALID_SEC_USER_AGENT,
                live_research_sec_base_url="https://user:pass@data.sec.gov",
            )

    def test_enabled_base_url_with_query_component_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _sec(
                live_research_sec_enabled=True,
                live_research_sec_user_agent=_VALID_SEC_USER_AGENT,
                live_research_sec_base_url="https://data.sec.gov?x=1",
            )

    def test_enabled_base_url_with_fragment_component_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _sec(
                live_research_sec_enabled=True,
                live_research_sec_user_agent=_VALID_SEC_USER_AGENT,
                live_research_sec_base_url="https://data.sec.gov#frag",
            )

    def test_requests_per_second_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _sec(live_research_sec_requests_per_second=True)

    def test_timeout_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _sec(live_research_sec_timeout_seconds=True)
