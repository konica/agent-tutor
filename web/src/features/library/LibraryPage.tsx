import { Upload } from "lucide-react";

import { Button } from "../../components/Button/Button";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";

// Static first-run Library (state library-empty@v0.3). US-1 and US-2 make it real.
export function LibraryPage() {
  return (
    <>
      <PageHeader title="Library" description="Your documents. They're private to you, and the tutor answers only from them." />
      <EmptyState
        variant="dropzone"
        icon={Upload}
        title="Upload your first document"
        note="Or drop files anywhere on this page. You can add several at once."
        actions={
          <Button variant="primary" size="lg" icon={Upload} disabled>
            Choose PDFs
          </Button>
        }
      >
        <p>PDFs up to 50 MB and 500 pages. Your documents stay private to you.</p>
      </EmptyState>
    </>
  );
}
