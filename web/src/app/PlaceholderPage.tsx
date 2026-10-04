import { PageHeader } from "../components/PageHeader/PageHeader";

// Header-only page for screens later slices build.
export function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return <PageHeader title={title} description={description} />;
}
