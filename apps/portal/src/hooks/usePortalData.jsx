import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { supabase } from '../supabase'
import { useAuth } from './useAuth'

const DataContext = createContext(null)

// Everything here is one query per table. Which rows come back is decided by the database, not by this code:
// a signed-in user only ever receives their own client's rows.
export function PortalDataProvider({ children }) {
  const { user } = useAuth()
  const [clients, setClients] = useState([])
  const [clientId, setClientId] = useState(null)
  const [snapshots, setSnapshots] = useState({})     // kind -> { payload, as_of, published_at }
  const [state, setState] = useState('loading')      // loading | ready | error

  const load = useCallback(async () => {
    setState('loading')
    const { data: list, error } = await supabase.from('portal_client').select('id, display_name').order('display_name')
    if (error) { setState('error'); return }
    setClients(list)
    setClientId(current => (list.some(c => c.id === current) ? current : list[0]?.id ?? null))
    if (!list.length) { setSnapshots({}); setState('ready') }
  }, [])

  useEffect(() => { if (user) load() }, [user, load])

  useEffect(() => {
    if (!clientId) return
    let cancelled = false
    supabase.from('published_snapshot').select('kind, payload, as_of, published_at').eq('client_id', clientId)
      .then(({ data, error }) => {
        if (cancelled) return
        if (error) { setState('error'); return }
        setSnapshots(Object.fromEntries(data.map(r => [r.kind, r])))
        setState('ready')
      })
    return () => { cancelled = true }
  }, [clientId])

  const value = useMemo(() => ({
    clients, clientId, setClientId, snapshots, state, reload: load,
    client: clients.find(c => c.id === clientId) ?? null,
  }), [clients, clientId, snapshots, state, load])

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>
}

export const usePortalData = () => useContext(DataContext)
