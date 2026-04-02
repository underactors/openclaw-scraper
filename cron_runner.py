"""
RUGGTECH Cron Runner — calls the OpenClaw skill agent on schedule.
"""

import sys
from dotenv import load_dotenv

load_dotenv()

from skill_runner import run_agent


def main():
    try:
        result = run_agent(trigger_type="cron")
        tools = result.get("tools_called", 0)
        errors = result.get("errors", 0)
        print(f"[Cron] Cycle: {tools} tools, {errors} errors, {result.get('turns', 0)} turns")
        sys.exit(0 if errors == 0 else 1)
    except Exception as e:
        print(f"[Cron] Fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
