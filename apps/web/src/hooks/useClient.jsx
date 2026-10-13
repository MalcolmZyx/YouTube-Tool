import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useApi } from './useApi'

const ClientContext = createContext(null)
const STORAGE_KEY = 'yt-studio-client'

// localStorage can be unavailable (private windows, blocked site data); the app must work without it.
const remembered = () => { try { return localStorage.getItem(STORAGE_KEY) } catch { return null } }
const remember = id => { try { id ? localStorage.setItem(STORAGE_KEY, id) : localStorage.removeItem(STORAGE_KEY) } catch { /* ignore */ } }

export function ClientProvider({ children }) {
  const { get, post, del } = useApi()
  const [clients,  setClients]  = useState([])
  const [clientId, setClientId] = useState(remembered)
  const [ready,    setReady]    = useState(false)
  // Bumped after an upload so pages reload the client's data.
  const [version, setVersion] = useState(0)

  const refresh = useCallback(async () => {
    const list = await get('/clients')
    setClients(list)
    setClientId(current => {
      const next = list.some(c => c.id === current) ? current : (list[0]?.id ?? null)
      remember(next)
      return next
    })
    return list
  }, [get])

  useEffect(() => { refresh().catch(() => {}).finally(() => setReady(true)) }, [])  // eslint-disable-line

  const select = id => { remember(id); setClientId(id) }

  const create = async name => {
    const created = await post('/clients', { name })
    await refresh()
    select(created.id)
    return created
  }

  const remove = async id => {
    const result = await del(`/clients/${id}`)
    await refresh()
    return result
  }

  const value = useMemo(() => ({
    clients, clientId, ready, version,
    client: clients.find(c => c.id === clientId) ?? null,
    // Turns '/heatmap' into '/clients/<id>/heatmap' for the selected client.
    scoped: path => `/clients/${clientId}${path}`,
    select, create, remove, refresh,
    dataChanged: () => { setVersion(v => v + 1); return refresh() },
  }), [clients, clientId, ready, version])  // eslint-disable-line

  return <ClientContext.Provider value={value}>{children}</ClientContext.Provider>
}

export const useClient = () => useContext(ClientContext)
