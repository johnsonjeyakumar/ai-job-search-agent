import EmptyState from "../components/EmptyState.jsx";
import PageHeader from "../components/PageHeader.jsx";

export default function Settings() {
  return (
    <div>
      <PageHeader title="Settings" description="Application, source, and AI provider settings." />
      <EmptyState
        title="No settings yet"
        description="Editable settings (roles, locations, experience, AI provider) arrive in a later phase."
      />
    </div>
  );
}