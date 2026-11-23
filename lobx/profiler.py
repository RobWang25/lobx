"""
Profiling utilities for matching engine performance analysis.
"""
import cProfile
import pstats
import io
import time
from functools import wraps
from collections.abc import Callable
from contextlib import contextmanager


class PerformanceProfiler:
    """
    Profiler for tracking matching engine bottlenecks.
    
    Features:
    - cProfile integration for detailed function profiling
    - Hot path identification
    - Latency tracking per operation
    - Cumulative statistics
    """
    
    def __init__(self):
        self.profiler = cProfile.Profile()
        self.enabled = False
        self.stats = None
        
        # Custom metrics
        self.operation_times = {}
        self.operation_counts = {}
    
    def enable(self):
        """Enable profiling"""
        if not self.enabled:
            self.enabled = True
            self.profiler.enable()
    
    def disable(self):
        """Disable profiling"""
        if self.enabled:
            self.enabled = False
            self.profiler.disable()
    
    def get_stats(self, sort_by='cumulative', top_n=20):
        """
        Get profiling statistics.
        
        Args:
            sort_by: Sort order ('cumulative', 'time', 'calls')
            top_n: Number of top functions to return
            
        Returns:
            String with formatted statistics
        """
        if not self.enabled and not self.stats:
            return "Profiler not enabled"
        
        s = io.StringIO()
        ps = pstats.Stats(self.profiler, stream=s)
        ps.strip_dirs()
        ps.sort_stats(sort_by)
        ps.print_stats(top_n)
        
        return s.getvalue()
    
    def get_custom_metrics(self):
        """Get custom operation metrics"""
        metrics = {}
        for op, times in self.operation_times.items():
            count = self.operation_counts.get(op, 0)
            if count > 0:
                metrics[op] = {
                    'count': count,
                    'total_time_ms': sum(times) * 1000,
                    'avg_time_ms': (sum(times) / count) * 1000,
                    'min_time_ms': min(times) * 1000,
                    'max_time_ms': max(times) * 1000
                }
        return metrics
    
    def reset(self):
        """Reset profiler statistics"""
        if self.enabled:
            self.profiler.disable()
        self.profiler = cProfile.Profile()
        if self.enabled:
            self.profiler.enable()
        self.operation_times.clear()
        self.operation_counts.clear()
    
    @contextmanager
    def measure_operation(self, operation_name: str):
        """
        Context manager for measuring specific operation.
        
        Usage:
            with profiler.measure_operation('match_order'):
                # operation code
        """
        start_time = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start_time
            if operation_name not in self.operation_times:
                self.operation_times[operation_name] = []
                self.operation_counts[operation_name] = 0
            self.operation_times[operation_name].append(elapsed)
            self.operation_counts[operation_name] += 1


def profile_function(func: Callable) -> Callable:
    """
    Decorator to profile a function.
    
    Usage:
        @profile_function
        def my_function():
            pass
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            result = func(*args, **kwargs)
        finally:
            profiler.disable()
            s = io.StringIO()
            ps = pstats.Stats(profiler, stream=s)
            ps.strip_dirs()
            ps.sort_stats('cumulative')
            ps.print_stats(10)
            print(f"\nProfile for {func.__name__}:\n{s.getvalue()}")
        return result
    return wrapper


class LatencyTracker:
    """
    Simple latency tracker for identifying hot paths.
    
    Lightweight alternative to full profiling.
    """
    
    def __init__(self, percentiles=(50, 95, 99)):
        self.percentiles = percentiles
        self.measurements = {}
    
    def record(self, operation: str, latency_ms: float):
        """Record a latency measurement"""
        if operation not in self.measurements:
            self.measurements[operation] = []
        self.measurements[operation].append(latency_ms)
    
    def get_stats(self, operation: str = None):
        """
        Get latency statistics.
        
        Args:
            operation: Specific operation (None for all)
            
        Returns:
            Dictionary with percentile statistics
        """
        if operation:
            return self._compute_stats(operation)
        
        return {op: self._compute_stats(op) for op in self.measurements}
    
    def _compute_stats(self, operation: str):
        """Compute statistics for an operation"""
        if operation not in self.measurements:
            return None
        
        values = sorted(self.measurements[operation])
        n = len(values)
        
        if n == 0:
            return None
        
        stats = {
            'count': n,
            'min': values[0],
            'max': values[-1],
            'mean': sum(values) / n
        }
        
        for p in self.percentiles:
            idx = int(n * p / 100)
            stats[f'p{p}'] = values[min(idx, n - 1)]
        
        return stats
    
    def reset(self):
        """Reset all measurements"""
        self.measurements.clear()
