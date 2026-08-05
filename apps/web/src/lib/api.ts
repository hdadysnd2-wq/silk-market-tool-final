// Typed fetch client. Auth rides an httpOnly `silk_token` cookie set by the
// /api/session/* route handlers; the browser sends it automatically on
// same-origin /api/v1 calls (which next.config rewrites to FastAPI). Client JS
// never reads or attaches the token (C2 — CRITICAL-2).

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const { headers, ...rest } = options;
  const res = await fetch(`/api/v1${path}`, {
    ...rest,
    headers: {
      ...(rest.body && !(rest.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...headers,
    },
    credentials: "same-origin", // send the httpOnly session cookie
    cache: "no-store",
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : "Request failed");
  }

  if (res.status === 204) return undefined as T;
  const contentType = res.headers.get("content-type") ?? "";
  return contentType.includes("application/json")
    ? ((await res.json()) as T)
    : (undefined as T);
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
    }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  // Fetch a non-JSON endpoint (e.g. the HTML report) as a Blob. The session
  // cookie authenticates it, same as every other call.
  blob: async (path: string): Promise<Blob> => {
    const res = await fetch(`/api/v1${path}`, { credentials: "same-origin", cache: "no-store" });
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return res.blob();
  },
};
