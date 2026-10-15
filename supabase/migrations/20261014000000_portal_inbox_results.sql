-- Client uploads: let the admin app report back what happened to a file, and widen the accepted file types.

-- A pulled file is either imported ('pulled') or refused ('rejected'). The admin app writes the short message the
-- client reads; the client can never set either (its insert privilege stays limited to the descriptive columns).
alter table public.upload_inbox drop constraint upload_inbox_status_check;
alter table public.upload_inbox add constraint upload_inbox_status_check
    check (status in ('pending', 'pulled', 'rejected'));
alter table public.upload_inbox add column message text check (message is null or length(message) <= 300);

-- Windows reports a .csv as application/vnd.ms-excel when Excel is installed, so a strict text/csv rule would refuse a
-- genuine CSV from many users. The type is a first filter only: the admin app checks the real content on import.
update storage.buckets
set allowed_mime_types = array[
    'text/csv',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
]
where id = 'inbox';
