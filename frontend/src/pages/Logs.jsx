import EmptyState from "../components/EmptyState.jsx";
import PageHeader from "../components/PageHeader.jsx";

export default function Logs() {
  return (
    <div>
      <PageHeader title="Logs" description="Automation runs and captured errors." />
      <EmptyState
        title="No logs yet"
        description="Automation run logs and error tracking will appear in a later phase."
      />
    </div>
  );
}