import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <h1 className="text-2xl font-bold text-slate-900">Page not found</h1>
      <p className="max-w-sm text-sm text-muted">The page you&apos;re looking for doesn&apos;t exist or may have moved.</p>
      <Link href="/dashboard" className="rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-white hover:bg-primary-hover">
        Back to dashboard
      </Link>
    </div>
  );
}
