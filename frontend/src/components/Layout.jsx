import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/jobs", label: "Jobs" },
  { to: "/recommendations", label: "Recommendations" },
  { to: "/applications", label: "Applications" },
  { to: "/resumes", label: "Resumes" },
  { to: "/recruiters", label: "Recruiters" },
  { to: "/profile", label: "Profile" },
  { to: "/preferences", label: "Preferences" },
  { to: "/settings", label: "Settings" },
  { to: "/logs", label: "Logs" },
];

export default function Layout({ children }) {
  return (
    <div className="flex min-h-screen bg-slate-100">
      <aside className="w-60 shrink-0 border-r border-slate-800 bg-slate-900 text-slate-100">
        <div className="border-b border-slate-800 px-5 py-5">
          <h1 className="text-lg font-semibold">Job Agent</h1>
          <p className="mt-1 text-xs text-slate-400">Personal Job Search Assistant</p>
        </div>
        <nav className="space-y-1 px-3 py-4">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block rounded px-3 py-2 text-sm font-medium ${
                  isActive
                    ? "bg-slate-800 text-white"
                    : "text-slate-400 hover:bg-slate-800 hover:text-white"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-x-hidden">
        <div className="p-8">{children}</div>
      </main>
    </div>
  );
}