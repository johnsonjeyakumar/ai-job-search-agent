export default function PageHeader({ title, description }) {
  return (
    <header className="mb-6">
      <h2 className="text-2xl font-semibold text-slate-900">{title}</h2>
      {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
    </header>
  );
}