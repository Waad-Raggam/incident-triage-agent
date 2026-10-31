"""Chaos #2: turn on the `slow_dependency` feature flag. Inventory calls take ~2 s.

Expected: `checkout-api-latency-p99` goes into ALARM within ~3 minutes.
Correct fix the agent should find: clear the feature flag (no deploy happened).
"""

from common import set_flags

if __name__ == "__main__":
    set_flags(slow_dependency=True)
    print("slow_dependency=true. Watch the latency alarm.")
