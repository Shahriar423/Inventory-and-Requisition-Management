import { lazy } from "react";

const FLAG = "ims_chunk_reloaded";

const isChunkError = (e) =>
  e?.name === "ChunkLoadError" ||
  /Loading (CSS )?chunk|Failed to fetch dynamically imported module|Importing a module script failed/i.test(e?.message || "");

/**
 * React.lazy() with one automatic recovery step. After a new deployment the old page chunks no longer exist on the
 * server, so a tab that was opened before the deploy fails to load the next page. We reload ONCE to pick up the
 * new build; the flag stops an endless reload loop if the chunk is genuinely missing.
 */
export default function lazyWithRetry(factory) {
  return lazy(async () => {
    try {
      const mod = await factory();
      try { sessionStorage.removeItem(FLAG); } catch (e) { /* storage blocked - ignore */ }
      return mod;
    } catch (err) {
      let already = true;
      try { already = sessionStorage.getItem(FLAG) === "1"; } catch (e) { /* ignore */ }
      if (isChunkError(err) && !already) {
        try { sessionStorage.setItem(FLAG, "1"); } catch (e) { /* ignore */ }
        window.location.reload();
        return new Promise(() => {});          // keep showing the loader while the page reloads
      }
      throw err;                                // the ErrorBoundary shows the "page crashed" screen
    }
  });
}
