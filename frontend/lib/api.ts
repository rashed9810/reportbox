// Small helper for calling the ReportBox API.
//
// Sign-in uses httpOnly cookies set by the API, so this code never sees or stores a session
// token. Every request carries the X-RB-CSRF header, which the API requires for changes.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg: string }) => d.msg).join(". ");
  } catch {
    /* not JSON */
  }
  return `Something went wrong (${res.status})`;
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = { "X-RB-CSRF": "1" };
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, { method: opts.method || (body ? "POST" : "GET"), headers, body, credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, await readError(res));
  return res.json();
}

// Opens a PDF in a new tab. The cookie travels with the request, so no token goes in the URL.
export async function openPdf(path: string) {
  const win = window.open("", "_blank");
  const res = await fetch(path, { credentials: "same-origin" });
  if (!res.ok) {
    win?.close();
    throw new ApiError(res.status, await readError(res));
  }
  const url = URL.createObjectURL(await res.blob());
  if (win) win.location.href = url;
  else window.location.href = url;
}
