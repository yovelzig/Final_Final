import { handleSessionBootstrap } from "@/lib/auth/session-handler";

export async function POST(request: Request): Promise<Response> {
  return handleSessionBootstrap(request);
}
