import EmptyState from "../components/EmptyState.jsx";
import PageHeader from "../components/PageHeader.jsx";

export default function Recommendations() {
  return (
    <div>
      <PageHeader
        title="Recommendations"
        description="AI-based job analysis with transparent match scores."
      />
      <EmptyState
        title="No recommendations yet"
        description="Match scoring will be generated once jobs exist and a profile is configured."
      />
    </div>
  );
}