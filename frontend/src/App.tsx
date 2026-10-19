import { type ReactNode, useEffect, useState } from 'react'
import { Routes, Route, NavLink, Navigate, useNavigate, Link } from 'react-router-dom'
import Login from './pages/Login'
import Experiment from './pages/Experiment'
import Setup from './pages/Setup'
import Dashboard from './pages/Dashboard'
import Settings from './pages/Settings'
import { ToastProvider } from './components/Toast'

interface AuthState { checked: boolean; loggedIn: boolean; user: Record<string, unknown> | null }
function ProtectedRoute({ auth, children }: { auth: AuthState; children: ReactNode }) {
  if (!auth.checked) return <div className="console-empty">正在读取账号…</div>
  if (!auth.loggedIn) return <Navigate to="/login" replace />
  return <>{children}</>
}
export default function App() {
  const navigate = useNavigate()
  const [auth, setAuth] = useState<AuthState>({ checked: false, loggedIn: false, user: null })
  const refreshAuth = () => fetch('/api/auth/status').then(r => r.json()).then(data => setAuth({ checked: true, loggedIn: data.logged_in, user: data.user })).catch(() => setAuth({ checked: true, loggedIn: false, user: null }))
  useEffect(() => { refreshAuth(); const timer = setInterval(refreshAuth, 15000); return () => clearInterval(timer) }, [])
  const logout = async () => { await fetch('/api/auth/logout', { method: 'POST' }); setAuth({ checked: true, loggedIn: false, user: null }); navigate('/login') }
  return <ToastProvider><div className="app">
    <header className="sticky-header"><nav className="navbar">
      <Link to="/experiment" className="navbar-brand"><span className="brand-symbol" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M5 7h14M8 11v3m4-3v6m4-6v3M5 19h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/><path d="M7 3h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg></span>雨课堂助手<span className="brand-edition">DESKTOP</span></Link>
      <div className="navbar-links"><NavLink to="/experiment" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>运行台</NavLink><NavLink to="/setup" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>配置向导</NavLink>{auth.loggedIn && <NavLink to="/settings" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>高级设置</NavLink>}</div>
      <div className="navbar-actions">{auth.loggedIn ? <><div className="navbar-user"><span className="account-dot"/><span className="navbar-username">{String(auth.user?.name || '账号已连接')}</span></div><button className="text-button" onClick={logout}>退出</button></> : <Link className="console-button small" to="/login">扫码登录</Link>}</div>
    </nav></header>
    <main className="main-content"><Routes>
      <Route path="/" element={<Navigate to="/experiment" replace />} />
      <Route path="/experiment" element={<Experiment />} />
      <Route path="/setup" element={<Setup onAuthChange={refreshAuth} />} />
      <Route path="/login" element={auth.checked && auth.loggedIn ? <Navigate to="/experiment" replace /> : <Login onSuccess={refreshAuth} />} />
      <Route path="/dashboard" element={<ProtectedRoute auth={auth}><Dashboard /></ProtectedRoute>} />
      <Route path="/settings" element={<ProtectedRoute auth={auth}><Settings /></ProtectedRoute>} />
      <Route path="*" element={<Navigate to="/experiment" replace />} />
    </Routes></main>
  </div></ToastProvider>
}
