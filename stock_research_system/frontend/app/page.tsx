import Link from "next/link";

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-6 text-center">
      <h1 className="text-4xl font-bold text-primary">FinQuest</h1>
      <p className="max-w-md text-slate-600">
        Learn to invest with confidence - grounded lessons, adaptive practice, historical market scenarios, and a
        risk-free virtual portfolio.
      </p>
      <div className="flex gap-3">
        <Link
          href="/login"
          className="rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-white hover:bg-primary-hover"
        >
          Log in
        </Link>
        <Link
          href="/register"
          className="rounded-lg border border-border bg-surface px-5 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Create an account
        </Link>
      </div>
    </main>
  );
}
