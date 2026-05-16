import { useEffect } from "react";

const DEFAULT_TITLE = "Job Application Tool";

export function useBadge(count: number): void {
  useEffect(() => {
    document.title = count > 0 ? `(${count}) ${DEFAULT_TITLE}` : DEFAULT_TITLE;
    return () => {
      document.title = DEFAULT_TITLE;
    };
  }, [count]);
}
