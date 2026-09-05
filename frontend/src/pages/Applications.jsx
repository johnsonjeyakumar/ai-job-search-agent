import EmptyState from "../components/EmptyState.jsx";
import PageHeader from "../components/PageHeader.jsx";

export default function Applications() {
  return (
    <div>
      <PageHeader title="Applications" description="Track applications, interviews, and outcomes." />
      <EmptyState
        title="No applications yet"
        description="Applications become visible here once submissions are tracked."
      />
    </div>
  );
}