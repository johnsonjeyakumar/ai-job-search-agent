import EmptyState from "../components/EmptyState.jsx";
import PageHeader from "../components/PageHeader.jsx";

export default function Recruiters() {
  return (
    <div>
      <PageHeader title="Recruiters" description="Contacts and follow-ups with recruiters." />
      <EmptyState
        title="No recruiters yet"
        description="Recruiter contact tracking will be added in a later phase."
      />
    </div>
  );
}