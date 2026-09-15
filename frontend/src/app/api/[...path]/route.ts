import { proxyRequest } from "@/lib/server/proxy";

// Resolved per request from BACKEND_INTERNAL_URL; nothing about the backend is built in.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Context = { params: Promise<{ path?: string[] }> };

async function handle(request: Request, context: Context): Promise<Response> {
  const { path = [] } = await context.params;
  return proxyRequest(request, path);
}

export const GET = handle;
export const HEAD = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
export const OPTIONS = handle;
