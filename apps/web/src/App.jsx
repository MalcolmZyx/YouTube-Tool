import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import StatusAlerts from './components/StatusAlerts'
import Dashboard    from './pages/Dashboard'
import Audit        from './pages/Audit'
import Requests     from './pages/Requests'
import Heatmap      from './pages/Heatmap'
import Keywords     from './pages/Keywords'
import Descriptions from './pages/Descriptions'
import Researcher   from './pages/Researcher'
import Settings     from './pages/Settings'

export default function App() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 ml-56 overflow-auto">
        <div className="max-w-(--breakpoint-2xl) mx-auto px-8 py-8">
          <StatusAlerts />
          <Routes>
            <Route path="/"             element={<Dashboard />}    />
            <Route path="/audit"        element={<Audit />}        />
            <Route path="/requests"     element={<Requests />}     />
            <Route path="/heatmap"      element={<Heatmap />}      />
            <Route path="/keywords"     element={<Keywords />}     />
            <Route path="/descriptions" element={<Descriptions />} />
            <Route path="/researcher"   element={<Researcher />}   />
            <Route path="/settings"     element={<Settings />}     />
          </Routes>
        </div>
      </main>
    </div>
  )
}
