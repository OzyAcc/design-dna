"""Design DNA dashboard: a single-workspace web application around the Design DNA engine.

The application orchestrates the engine in `skills/reverse-design/scripts`; it never reimplements measurement,
rendering or verification. Each engine operation runs in a subprocess with an explicit DESIGN_DNA_HOME.
"""
__version__ = "0.1.0"
