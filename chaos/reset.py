"""Put checkout-api back to healthy: failure rate 0, all flags off."""

from common import deploy, set_flags

if __name__ == "__main__":
    set_flags(slow_dependency=False)
    v = deploy(0.0, "deploy: reset to healthy")
    print(f"Healthy again (version {v}). Alarms clear after a few minutes.")
