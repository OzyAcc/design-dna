"""Job handlers (imported by the worker to register every job kind)."""
from . import output_jobs, template_jobs

__all__ = ["output_jobs", "template_jobs"]
