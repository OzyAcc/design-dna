"""Test-only fault injection for crash-recovery tests.

With DNA_ENABLE_MOCK_PROVIDERS=1 (tests only) and DNA_TEST_CRASH_AT=<point>, the process exits abruptly at that point,
like a worker killed by the operating system: no cleanup, no lease release, no job bookkeeping. With either variable
unset this does nothing, so a production worker can never be stopped through it.

Points: after_provider_receipt (a provider answered; its result is not stored yet), after_checkpoint (the result is
stored; nothing has been built from it), after_artifact (output files are written; the job is not finished).
"""
from __future__ import annotations

import os

from . import config


def crash_point(name: str) -> None:
    if os.environ.get("DNA_TEST_CRASH_AT") == name and config.get().enable_mock_providers:
        os._exit(86)
