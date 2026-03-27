"""Pytest hooks for pm-job-agent."""

import pytest

from pm_job_agent.config.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    """Settings are cached; clear between tests so env changes apply."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
