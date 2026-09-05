import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth';
import LoginPage from './pages/LoginPage';
import JobListPage from './pages/JobListPage';
import JobDetailPage from './pages/JobDetailPage';
import NewJobPage from './pages/NewJobPage';
import NewCustomerPage from './pages/NewCustomerPage';
import JobLookupPage from './pages/JobLookupPage';
import StaffAdminPage from './pages/StaffAdminPage';
import StaffIntakePage from './pages/StaffIntakePage';
import SitesAdminPage from './pages/SitesAdminPage';
import SettlementPage from './pages/SettlementPage';

const NAV_ITEMS = [
  { to: '/', label: 'Jobs' },
  { to: '/customers/new', label: 'New Customer' },
  { to: '/lookup', label: 'Look Up RO' },
  { to: '/settlement', label: 'PDR Settlement' },
];

const ADMIN_NAV_ITEM = { to: '/staff', label: 'Staff' };
const SITES_ADMIN_NAV_ITEM = { to: '/sites', label: 'Sites' };

function AppShell() {
  const { staff, logout } = useAuth();
  const location = useLocation();

  if (!staff) return <LoginPage />;

  const isAdmin = staff.role === 'owner' || staff.role === 'manager';
  const navItems = isAdmin ? [...NAV_ITEMS, ADMIN_NAV_ITEM, SITES_ADMIN_NAV_ITEM] : NAV_ITEMS;

  const activeLabel =
    navItems.find((n) => n.to === location.pathname)?.label ??
    (location.pathname === '/jobs/new' ? 'New Job'
      : location.pathname === '/customers/new' ? 'New Customer'
      : location.pathname === '/staff/new' ? 'Onboard Staff'
      : location.pathname.startsWith('/jobs/') ? 'Job Detail'
      : 'Complete Collision');

  return (
    <div className="cc-app">
      <aside className="cc-sidebar">
        <div className="cc-brand-logo">
          Complete<br />Collision<span>.</span>
        </div>
        <nav className="cc-nav">
          {navItems.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={location.pathname === item.to ? 'active' : ''}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="cc-main">
        <div className="cc-topbar">
          <h1>{activeLabel}</h1>
          <div>
            <span className="cc-user-chip">{staff.google_email} · {staff.role}</span>
            <button className="cc-signout" onClick={logout}>Sign out</button>
          </div>
        </div>
        <Routes>
          <Route path="/" element={<JobListPage />} />
          <Route path="/jobs/new" element={<NewJobPage />} />
          <Route path="/customers/new" element={<NewCustomerPage />} />
          <Route path="/jobs/:roNumber" element={<JobDetailPage />} />
          <Route path="/lookup" element={<JobLookupPage />} />
          <Route path="/settlement" element={<SettlementPage />} />
          <Route path="/staff" element={<StaffAdminPage />} />
          <Route path="/staff/new" element={<StaffIntakePage />} />
          <Route path="/sites" element={<SitesAdminPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppShell />
      </AuthProvider>
    </BrowserRouter>
  );
}
