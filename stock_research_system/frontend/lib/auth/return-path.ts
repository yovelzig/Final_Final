/** Only ever redirects to a same-origin, absolute-path `returnTo` -
 * rejects protocol-relative (`//evil.com`) and absolute URLs
 * (`https://evil.com`), which would otherwise let a crafted login link
 * redirect a learner off FinQuest after authenticating. */
export function sanitizeReturnPath(rawPath: string | null): string {
  if (!rawPath) return "/dashboard";
  if (!rawPath.startsWith("/") || rawPath.startsWith("//") || rawPath.includes("://")) return "/dashboard";
  return rawPath;
}
