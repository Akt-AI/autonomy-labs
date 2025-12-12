-- Provider config storage for per-user API keys and base URLs.
-- Run this in Supabase SQL Editor.

create table if not exists public.provider_configs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  name text not null,
  api_key text not null default '',
  base_url text not null default '',
  model text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, name)
);

-- Keep updated_at current
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists provider_configs_set_updated_at on public.provider_configs;
create trigger provider_configs_set_updated_at
before update on public.provider_configs
for each row
execute procedure public.set_updated_at();

alter table public.provider_configs enable row level security;

drop policy if exists "provider_configs_select_own" on public.provider_configs;
create policy "provider_configs_select_own"
on public.provider_configs
for select
using (auth.uid() = user_id);

drop policy if exists "provider_configs_insert_own" on public.provider_configs;
create policy "provider_configs_insert_own"
on public.provider_configs
for insert
with check (auth.uid() = user_id);

drop policy if exists "provider_configs_update_own" on public.provider_configs;
create policy "provider_configs_update_own"
on public.provider_configs
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "provider_configs_delete_own" on public.provider_configs;
create policy "provider_configs_delete_own"
on public.provider_configs
for delete
using (auth.uid() = user_id);

