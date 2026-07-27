import { JobList } from "@/components/JobList";
import { UploadForm } from "@/components/UploadForm";

export default function HomePage() {
  return (
    <main>
      <h1 className="mb-2 text-2xl font-semibold tracking-tight">Convert a PDF</h1>
      <p className="mb-6 text-sm text-neutral-500">
        Values land in the right cells, with the fonts, borders, merges and
        images of the source.
      </p>

      <UploadForm />
      <JobList />
    </main>
  );
}
