// Dependency-free polling helper for the async 202 + poll pipeline contract:
// a POST returns 202 with a `pending` entity, and the client re-fetches the
// entity's GET endpoint until it reaches a terminal state.

interface PollOptions<T> {
  /** Delay between attempts, in ms. */
  intervalMs?: number;
  /** Give up (reject) after this many ms of total elapsed time. */
  timeoutMs?: number;
  /** Called with every fetched value (terminal or not) — lets the caller show
   *  per-stage progress instead of one opaque spinner. */
  onProgress?: (value: T) => void;
}

/**
 * Re-invoke `fetchFn` until `done(value)` is true, then resolve with that value.
 * Fetches immediately (no leading delay), so an already-terminal entity resolves
 * on the first attempt. Rejects if `done` never holds within `timeoutMs`.
 */
export async function pollUntil<T>(
  fetchFn: () => Promise<T>,
  done: (value: T) => boolean,
  { intervalMs = 1500, timeoutMs = 60000, onProgress }: PollOptions<T> = {},
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = await fetchFn();
    onProgress?.(value);
    if (done(value)) return value;
    if (Date.now() >= deadline) {
      throw new Error(`pollUntil: timed out after ${timeoutMs}ms`);
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
