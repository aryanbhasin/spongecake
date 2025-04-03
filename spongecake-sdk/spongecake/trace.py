import time
import logging
from typing import Dict, Any, Callable, Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class TraceEntry:
    """Represents a single event in a trace."""
    def __init__(self, action_type: str, timestamp: float, **kwargs):
        self.action_type = action_type
        self.timestamp = timestamp
        self.data = kwargs

    def to_dict(self) -> Dict[str, Any]:
        return {"action_type": self.action_type, "timestamp": self.timestamp, **self.data}

class TraceConfig:
    """Configuration for tracing behavior."""
    def __init__(
        self,
        enabled: bool = True,
        trace_api_calls: bool = False,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        self.enabled = enabled
        self.trace_api_calls = trace_api_calls
        self.callback = callback

class Tracer:
    """Manages tracing for an application."""
    def __init__(self, config: TraceConfig = None):
        self.config = config or TraceConfig()
        self.current_trace = None

    def start(self, trace_id: str) -> None:
        """Start a new trace if tracing is enabled."""
        if self.config.enabled and not self.current_trace:
            self.current_trace = {"trace_id": trace_id, "start_time": time.time(), "entries": []}

    def stop(self) -> None:
        """Stop the current trace and process it."""
        if self.current_trace:
            self.current_trace["end_time"] = time.time()
            trace_data = self.current_trace
            self.current_trace = None
            self._process_trace(trace_data)

    def add_entry(self, action_type: str, **kwargs) -> None:
        """Add an entry to the current trace."""
        if self.current_trace:
            entry = TraceEntry(action_type, time.time(), **kwargs)
            self.current_trace["entries"].append(entry.to_dict())
            logger.debug(f"Added trace entry: {action_type}")

    def _process_trace(self, trace_data: Dict[str, Any]) -> None:
        """Handle the completed trace by invoking the callback if provided."""
        if self.config.callback:
            try:
                self.config.callback(trace_data)
                logger.info(f"Trace {trace_data['trace_id']} passed to callback.")
            except Exception as e:
                logger.error(f"Error in trace callback: {str(e)}")

    @contextmanager
    def trace(self, trace_id: str):
        """Context manager for scoped tracing."""
        self.start(trace_id)
        try:
            yield
        finally:
            self.stop()