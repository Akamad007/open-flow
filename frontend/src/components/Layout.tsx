import { Outlet, Link, useLocation } from 'react-router-dom'

const navItems = [
  { path: '/', label: '📁 Projects', icon: '📁' },
]

export function Layout() {
  const location = useLocation()

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <h1>StoryVideo</h1>
        </div>
        <nav>
          {navItems.map(item => (
            <Link
              key={item.path}
              to={item.path}
              className={`sidebar-nav-link ${location.pathname === item.path ? 'active' : ''}`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div style={{ marginTop: 'auto', padding: '12px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          v0.1.0 • Multi-Agent Pipeline
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
