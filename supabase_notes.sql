-- Notes with folder tree + CRUD
-- Run this in Supabase SQL Editor.

create table if not exists public.note_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  parent_id uuid references public.note_items (id) on delete cascade,
  kind text not null check (kind in ('folder','note')),
  title text not null default '',
  content text not null default '',
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists note_items_user_id_idx on public.note_items (user_id);
create index if not exists note_items_parent_id_idx on public.note_items (parent_id);

create or replace function public.set_note_items_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists note_items_set_updated_at on public.note_items;
create trigger note_items_set_updated_at
before update on public.note_items
for each row
execute procedure public.set_note_items_updated_at();

alter table public.note_items enable row level security;

drop policy if exists "note_items_select_own" on public.note_items;
create policy "note_items_select_own"
on public.note_items
for select
using (auth.uid() = user_id);

drop policy if exists "note_items_insert_own" on public.note_items;
create policy "note_items_insert_own"
on public.note_items
for insert
with check (auth.uid() = user_id);

drop policy if exists "note_items_update_own" on public.note_items;
create policy "note_items_update_own"
on public.note_items
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "note_items_delete_own" on public.note_items;
create policy "note_items_delete_own"
on public.note_items
for delete
using (auth.uid() = user_id);

