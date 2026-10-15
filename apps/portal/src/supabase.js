import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export const configured = Boolean(url && anonKey)

// The anon key is public. What a signed-in user can read is decided by row-level security in the database.
export const supabase = configured ? createClient(url, anonKey) : null
