-- Client portal schema. Design: docs/design/client-portal.md
--
-- Every table has row-level security ON. A table with no policy for an operation refuses that operation.
-- The one rule behind every client-facing policy: the row's client_id must be a client the signed-in user belongs to.
-- Anything a client must not write (snapshots, permissions) has no write policy at all; only the admin app writes it,
-- with the service key, which bypasses RLS and lives only in the admin app's environment.

-- ── tables ──────────────────────────────────────────────────────────────────

create table public.portal_client (
    id           uuid primary key default gen_random_uuid(),
    display_name text not null check (length(btrim(display_name)) between 1 and 200),
    created_at   timestamptz not null default now()
);

create table public.portal_membership (
    user_id    uuid not null references auth.users (id) on delete cascade,
    client_id  uuid not null references public.portal_client (id) on delete cascade,
    role       text not null default 'client' check (role in ('client', 'admin')),
    created_at timestamptz not null default now(),
    primary key (user_id, client_id)
);
create index portal_membership_client_idx on public.portal_membership (client_id);

-- Latest snapshot per kind: publishing again replaces the row.
create table public.published_snapshot (
    client_id    uuid not null references public.portal_client (id) on delete cascade,
    kind         text not null check (kind in ('audit', 'dashboard')),
    payload      jsonb not null,
    as_of        date,
    published_at timestamptz not null default now(),
    primary key (client_id, kind)
);

create table public.service_request (
    id         bigint generated always as identity primary key,
    client_id  uuid not null references public.portal_client (id) on delete cascade,
    type       text not null check (type in ('new_dashboard', 'research', 'more_access', 'other')),
    note       text not null default '' check (length(note) <= 1000),
    status     text not null default 'requested' check (status in ('requested', 'approved', 'declined', 'done')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index service_request_client_idx on public.service_request (client_id);

create table public.client_permission (
    client_id  uuid not null references public.portal_client (id) on delete cascade,
    feature    text not null check (length(feature) between 1 and 100),
    status     text not null check (status in ('requested', 'granted', 'denied', 'expired')),
    quota      integer check (quota is null or quota >= 0),
    expires_at timestamptz,
    primary key (client_id, feature)
);

create table public.dashboard_preference (
    client_id  uuid primary key references public.portal_client (id) on delete cascade,
    focus      jsonb not null default '{}'::jsonb check (pg_column_size(focus) <= 8192),
    updated_at timestamptz not null default now()
);

create table public.upload_inbox (
    id                bigint generated always as identity primary key,
    client_id         uuid not null references public.portal_client (id) on delete cascade,
    storage_path      text not null,
    original_filename text not null check (length(original_filename) between 1 and 255),
    size_bytes        bigint not null check (size_bytes between 1 and 5242880),  -- 5 MB, as in the admin app
    sha256            text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    status            text not null default 'pending' check (status in ('pending', 'pulled')),
    created_at        timestamptz not null default now(),
    -- A client may only point at its own folder in the bucket.
    check (storage_path like client_id::text || '/%')
);
create index upload_inbox_client_idx on public.upload_inbox (client_id);

-- ── membership lookup ───────────────────────────────────────────────────────
-- A policy on portal_membership that reads portal_membership would recurse, so the lookup is a security definer
-- function: it runs with the owner's rights, but only ever answers "which clients does the caller belong to".

create function public.my_client_ids() returns setof uuid
    language sql stable security definer set search_path = ''
as $$
    select client_id from public.portal_membership where user_id = (select auth.uid())
$$;
revoke all on function public.my_client_ids() from public, anon;
grant execute on function public.my_client_ids() to authenticated;

-- ── privileges: least privilege first, RLS second ───────────────────────────
-- Supabase grants new tables to anon and authenticated by default. Remove that, then grant back only what is used.

revoke all on public.portal_client, public.portal_membership, public.published_snapshot, public.service_request,
    public.client_permission, public.dashboard_preference, public.upload_inbox from anon, authenticated;

grant select on public.portal_client, public.portal_membership, public.published_snapshot,
    public.client_permission, public.upload_inbox to authenticated;
grant select, insert (client_id, type, note) on public.service_request to authenticated;
grant select, insert, update (focus, updated_at) on public.dashboard_preference to authenticated;
grant insert (client_id, storage_path, original_filename, size_bytes, sha256) on public.upload_inbox to authenticated;

-- ── row-level security ──────────────────────────────────────────────────────

alter table public.portal_client        enable row level security;
alter table public.portal_membership    enable row level security;
alter table public.published_snapshot   enable row level security;
alter table public.service_request      enable row level security;
alter table public.client_permission    enable row level security;
alter table public.dashboard_preference enable row level security;
alter table public.upload_inbox         enable row level security;

create policy own_client on public.portal_client
    for select to authenticated using (id in (select public.my_client_ids()));

create policy own_membership on public.portal_membership
    for select to authenticated using (user_id = (select auth.uid()));

create policy own_snapshots on public.published_snapshot
    for select to authenticated using (client_id in (select public.my_client_ids()));

create policy own_requests_read on public.service_request
    for select to authenticated using (client_id in (select public.my_client_ids()));
create policy own_requests_create on public.service_request
    for insert to authenticated with check (client_id in (select public.my_client_ids()) and status = 'requested');

create policy own_permissions on public.client_permission
    for select to authenticated using (client_id in (select public.my_client_ids()));

create policy own_preference_read on public.dashboard_preference
    for select to authenticated using (client_id in (select public.my_client_ids()));
create policy own_preference_create on public.dashboard_preference
    for insert to authenticated with check (client_id in (select public.my_client_ids()));
create policy own_preference_update on public.dashboard_preference
    for update to authenticated using (client_id in (select public.my_client_ids()))
    with check (client_id in (select public.my_client_ids()));

create policy own_inbox_read on public.upload_inbox
    for select to authenticated using (client_id in (select public.my_client_ids()));
create policy own_inbox_create on public.upload_inbox
    for insert to authenticated with check (client_id in (select public.my_client_ids()) and status = 'pending');

-- ── file inbox (storage) ────────────────────────────────────────────────────
-- Files go to <client_id>/<name>. A client may add files under its own folder and nothing else: no listing, reading,
-- overwriting or deleting. Size and type are capped by the bucket itself.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'inbox', 'inbox', false, 5242880,
    array[
        'text/csv',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    ]
)
on conflict (id) do update
    set public = false, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

create policy inbox_add_to_own_folder on storage.objects
    for insert to authenticated
    with check (
        bucket_id = 'inbox'
        and name !~ '(^|/)\.\.(/|$)'  -- no path-traversal segments
        and (storage.foldername(name))[1] in (select client_id::text from public.my_client_ids() as client_id)
    );
