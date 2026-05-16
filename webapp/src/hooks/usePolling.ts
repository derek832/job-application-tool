import { useEffect, useRef } from "react";

export function usePolling(
  callback: () => void,
  intervalMs: number,
  enabled: boolean = true,
): void {
  const savedCallback = useRef(callback);
  savedCallback.current = callback;

  useEffect(() => {
    if (!enabled) return;
    savedCallback.current(); // Fire immediately on mount
    const id = setInterval(() => savedCallback.current(), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled]);
}
