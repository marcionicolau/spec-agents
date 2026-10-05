"""Tiny arithmetic helpers used by the coworker smoke test."""


def mean(xs):
    """Arithmetic mean of a non-empty list of numbers."""
    return sum(xs) / len(xs)


def clamp(x, lo=0.0, hi=1.0):
    """Clamp x into [lo, hi]."""
    return max(lo, min(hi, x))
