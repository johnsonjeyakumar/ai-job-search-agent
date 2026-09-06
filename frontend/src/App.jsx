import { Route, Routes } from "react-router-dom";
import { AppDataProvider } from "./context/AppDataContext.jsx";
import Layout from "./components/Layout.jsx";
import Applications from "./pages/Applications.jsx";
import Companies from "./pages/Companies.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import JobDetails from "./pages/JobDetails.jsx";
import Jobs from "./pages/Jobs.jsx";
import Logs from "./pages/Logs.jsx";
import Onboarding from "./pages/Onboarding.jsx";
import Preferences from "./pages/Preferences.jsx";
import Profile from "./pages/Profile.jsx";
import Recommendations from "./pages/Recommendations.jsx";
import Recruiters from "./pages/Recruiters.jsx";
import Resumes from "./pages/Resumes.jsx";
import Settings from "./pages/Settings.jsx";

export default function App() {
  return (
    <AppDataProvider>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<JobDetails />} />
          <Route path="/companies" element={<Companies />} />
          <Route path="/recommendations" element={<Recommendations />} />
          <Route path="/applications" element={<Applications />} />
          <Route path="/resumes" element={<Resumes />} />
          <Route path="/recruiters" element={<Recruiters />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/preferences" element={<Preferences />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/logs" element={<Logs />} />
        </Routes>
      </Layout>
    </AppDataProvider>
  );
}