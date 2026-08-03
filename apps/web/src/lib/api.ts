// Typed fetch client. The JWT is kept in an httpOnly cookie set by the
// /[locale]/login route handler; browser calls hit same-origin /api/* which
// next.config rewrites to the FastAPI backend.

const TOKEN_COOKIE = "silk_token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function readTokenFromCookie(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${TOKEN_COOKIE}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

async function request<T>(
  path: string,
  options: RequestInit & { token?: string | null } = {},
): Promise<T> {
  const { token, headers, ...rest } = options;
  const authToken = token ?? readTokenFromCookie();
  const res = await fetch(`/api/v1${path}`, {
    ...rest,
    headers: {
      ...(rest.body && !(rest.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...headers,
    },
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
  get: <T>(path: string, token?: string | null) => request<T>(path, { method: "GET", token }),
  post: <T>(path: string, body?: unknown, token?: string | null) =>
    request<T>(path, {
      method: "POST",
      body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
      token,
    }),
  put: <T>(path: string, body?: unknown, token?: string | null) =>
    request<T>(path, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
      token,
    }),
  del: <T>(path: string, token?: string | null) =>
    request<T>(path, { method: "DELETE", token }),
  // Fetch a non-JSON endpoint (e.g. the HTML report) as a Blob, carrying the
  // bearer token that a plain <a> download link could not.
  blob: async (path: string, token?: string | null): Promise<Blob> => {
    const authToken = token ?? readTokenFromCookie();
    const res = await fetch(`/api/v1${path}`, {
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
      cache: "no-store",
    });
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return res.blob();
  },
};

export { TOKEN_COOKIE };
