"""Fix cycle management and patch retry logic for validation workflow.

Tracks fix cycle consumption per platform and patch retry attempts per root cause.
"""


class FixCycleManager:
    """Tracks fix cycles per platform with a maximum of 5 cycles.

    After 5 cycles without achieving Platform_Pass, the platform is marked as "fail".
    """

    MAX_CYCLES = 5

    def __init__(self) -> None:
        self._cycles: dict[str, int] = {}

    def consume_cycle(self, platform: str) -> bool:
        """Consume a fix cycle for the given platform.

        Returns:
            True if a cycle was available and consumed.
            False if the limit has been reached (platform exhausted).
        """
        current = self._cycles.get(platform, 0)
        if current >= self.MAX_CYCLES:
            return False
        self._cycles[platform] = current + 1
        return True

    def is_exhausted(self, platform: str) -> bool:
        """Return True if the platform has used all 5 fix cycles."""
        return self._cycles.get(platform, 0) >= self.MAX_CYCLES

    def cycles_used(self, platform: str) -> int:
        """Return the number of cycles consumed for a platform."""
        return self._cycles.get(platform, 0)


class PatchRetryTracker:
    """Tracks patch attempts per root cause per platform.

    After 2 failed patches targeting the same root cause, the system
    discards those patches and triggers a fresh re-diagnosis.
    """

    MAX_ATTEMPTS_PER_CAUSE = 2

    def __init__(self) -> None:
        # {(platform, root_cause): failure_count}
        self._failures: dict[tuple[str, str], int] = {}

    def record_patch_attempt(self, platform: str, root_cause: str, success: bool) -> str:
        """Record a patch attempt outcome.

        Returns:
            "resolved" if the patch succeeded.
            "continue" if more attempts are allowed.
            "discard_and_rediagnose" if 2 failures at this root cause.
        """
        if success:
            return "resolved"

        key = (platform, root_cause)
        self._failures[key] = self._failures.get(key, 0) + 1

        if self._failures[key] >= self.MAX_ATTEMPTS_PER_CAUSE:
            return "discard_and_rediagnose"

        return "continue"
