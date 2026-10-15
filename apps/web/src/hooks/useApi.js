import { useState, useCallback } from 'react'
import axios from 'axios'

const BASE = '/api'

export function useApi() {
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const request = useCallback(async (method, path, data = null, config = {}) => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios({ method, url: `${BASE}${path}`, data, ...config })
      return res.data
    } catch (err) {
      const msg = err?.response?.data?.error || err.message || 'Unknown error'
      setError(msg)
      throw new Error(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  const get  = useCallback((path, params = {}) => request('get',  path, null, { params }), [request])
  const post = useCallback((path, body)         => request('post', path, body),              [request])
  const upload = useCallback((path, formData)   => request('post', path, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }), [request])

  const put  = useCallback((path, body)         => request('put',  path, body),              [request])
  const del = useCallback(path => request('delete', path), [request])

  return { get, post, put, del, upload, loading, error }
}
