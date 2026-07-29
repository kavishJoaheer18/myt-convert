import { JobList } from "@/components/JobList";
import { MytLogo } from "@/components/MytLogo";
import { UploadForm } from "@/components/UploadForm";

export default function HomePage() {
  return (
    <main>
      {/* Dark brand surface: Telecom Blue through myt Blue to Digital Blue. */}
      <section className="relative overflow-hidden rounded-brand bg-myt-gradient px-8 py-12 text-white sm:px-12 sm:py-16">
        <div className="relative max-w-2xl">
          {/* Primary logo: reversed out of a dark brand background. */}
          <MytLogo className="h-9 w-auto text-white" />
          <p className="mt-6 text-xs font-medium uppercase tracking-[0.2em] text-white/60">
            Document conversion
          </p>
          <h1 className="mt-4 text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            Spreadsheets that still look like the page they came from
          </h1>
          <p className="mt-4 text-base font-light leading-relaxed text-white/75">
            Values land in the right cells, merged headings stay merged, and a
            number that read <span className="font-medium">1,234.50</span> on
            the page still reads that way in the sheet.
          </p>
        </div>

        {/* An abstracted crop of the myt shape, kept subtle behind the copy. */}
        <div
          aria-hidden
          className="pointer-events-none absolute -right-16 -top-24 h-80 w-80 rounded-full bg-aqua/25 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-32 right-24 h-72 w-72 rounded-full bg-white/10 blur-3xl"
        />
      </section>

      <div className="mt-10">
        <UploadForm />
      </div>

      <JobList />
    </main>
  );
}
