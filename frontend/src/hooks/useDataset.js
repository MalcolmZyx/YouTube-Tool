import { useState, useCallback } from 'react'

// Minimal global store without Redux – just a module-level ref + listeners
let _dataset = null
const _listeners = new Set()

function notify() { _listeners.forEach(fn => fn(_dataset)) }

export function useDataset() {
  const [dataset, _setLocal] = useState(_dataset)

  // Register this component as a listener
  const subscribe = useCallback(() => {
    const handler = d => _setLocal({ ...d })
    _listeners.add(handler)
    return () => _listeners.delete(handler)
  }, [])

  const setDataset = useCallback(d => {
    _dataset = d
    notify()
  }, [])

  return { dataset, setDataset, subscribe }
}
