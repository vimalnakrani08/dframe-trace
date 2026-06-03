"""dframe_trace: automatic causal tracing for Python DataFrame pipelines.

Stop sprinkling print(df.shape) between steps. Wrap your pipeline once and
ask questions afterward: where did this column become null? where did rows
disappear? what changed dtype silently?
"""
from .core import Trace, Step, traced, trace
from . import autopatch, guards, backends

__version__ = "0.3.0"
__all__ = ["Trace", "Step", "traced", "trace", "autopatch", "guards", "backends"]
