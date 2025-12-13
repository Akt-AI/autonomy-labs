-- Simple per-user notes storage (single row per user).
-- Run this in Supabase SQL Editor.

create table if not exists public.user_notes (
  user_id uuid primary key references auth.users (id) on delete cascade,
  content text not null default '',
  updated_at timestamptz not null default now()
);

create or replace function public.set_notes_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists user_notes_set_updated_at on public.user_notes;
create trigger user_notes_set_updated_at
before update on public.user_notes
for each row
execute procedure public.set_notes_updated_at();

alter table public.user_notes enable row level security;

drop policy if exists "user_notes_select_own" on public.user_notes;
create policy "user_notes_select_own"
on public.user_notes
for select
using (auth.uid() = user_id);

drop policy if exists "user_notes_insert_own" on public.user_notes;
create policy "user_notes_insert_own"
on public.user_notes
for insert
with check (auth.uid() = user_id);

drop policy if exists "user_notes_update_own" on public.user_notes;
create policy "user_notes_update_own"
on public.user_notes
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

