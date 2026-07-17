import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-neutral-500">This route doesn&apos;t exist.</p>
      <Link href="/" className="text-sm text-blue-400 hover:underline">
        Back to home
      </Link>
    </main>
  );
}
