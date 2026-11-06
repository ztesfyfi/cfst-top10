const FILES = new Set(["ipv4.txt", "ipv6.txt"]);
const MAX_BYTES = 2 * 1024 * 1024;

function response(body, status = 200, extra = {}) {
  return new Response(body, {
    status,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      "Cache-Control": "public, max-age=60",
      ...extra,
    },
  });
}

async function authorized(request, env) {
  const expected = env.CFST_UPLOAD_TOKEN;
  const supplied = request.headers.get("Authorization") || "";
  if (!expected || !supplied.startsWith("Bearer ")) return false;
  const a = new TextEncoder().encode(supplied.slice(7));
  const b = new TextEncoder().encode(expected);
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const filename = url.pathname.replace(/^\/+|\/+$/g, "");

    if (!FILES.has(filename) || url.pathname !== "/" + filename) {
      return response("Not found", 404);
    }

    if (request.method === "GET") {
      const value = await env.CFST_RESULTS.get(filename);
      if (value === null) return response("Not found", 404);
      return response(value, 200, { "Cache-Control": "public, max-age=60" });
    }

    if (request.method === "PUT") {
      if (!(await authorized(request, env))) return response("Unauthorized", 401);
      const declared = Number(request.headers.get("Content-Length") || 0);
      if (declared > MAX_BYTES) return response("Payload too large", 413);
      const body = await request.text();
      if (!body || new TextEncoder().encode(body).byteLength > MAX_BYTES) {
        return response("Empty or oversized result", 413);
      }
      if (!body.endsWith("\n") || body.includes("\r")) {
        return response("Invalid TXT format", 400);
      }
      const lines = body.trimEnd().split("\n");
      if (!lines.length || lines.some((line) => !line || /\s/.test(line))) {
        return response("Invalid TXT lines", 400);
      }
      await env.CFST_RESULTS.put(filename, body, {
        metadata: { updated_at: new Date().toISOString(), count: lines.length },
      });
      return response("OK", 200, { "Cache-Control": "no-store" });
    }

    return response("Method not allowed", 405, { Allow: "GET, PUT" });
  },
};
