import { useEffect, useState } from "react";

const QUERY = "(prefers-color-scheme: dark)";

export function usePrefersDark(): boolean {
  const [dark, setDark] = useState(() => window.matchMedia?.(QUERY).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(QUERY);
    if (!media) return;
    const update = () => setDark(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return dark;
}
