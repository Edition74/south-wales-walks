-- South Wales Walks — ratings schema
-- Run this once in the Supabase SQL Editor (left sidebar -> SQL -> New query -> paste -> Run).
-- Re-running is safe: every CREATE uses IF NOT EXISTS and policies use DROP+CREATE.

-- ---------------------------------------------------------------------------
-- Table: one row per (user, walk). A user rating a walk twice updates their row.
-- ---------------------------------------------------------------------------
create table if not exists public.ratings (
  user_id      uuid        not null references auth.users(id) on delete cascade,
  walk_id      integer     not null check (walk_id between 1 and 100000),
  -- 1-5 star scales. Only `overall` is required; the rest are optional so
  -- users can skip dimensions they don't have an opinion on.
  overall      smallint    not null check (overall between 1 and 5),
  scenery      smallint    check (scenery     between 1 and 5),
  family       smallint    check (family      between 1 and 5),
  dogs         smallint    check (dogs        between 1 and 5),
  value        smallint    check (value       between 1 and 5),
  comment      text        check (comment is null or char_length(comment) <= 500),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  primary key (user_id, walk_id)
);

-- Keep updated_at fresh on upsert.
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists ratings_touch_updated_at on public.ratings;
create trigger ratings_touch_updated_at
before update on public.ratings
for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- Row Level Security — the whole point of Supabase. Without these, every
-- visitor could read or tamper with every user's rating.
-- ---------------------------------------------------------------------------
alter table public.ratings enable row level security;

-- Drop then recreate so re-running this script is safe.
drop policy if exists ratings_select_own on public.ratings;
drop policy if exists ratings_insert_own on public.ratings;
drop policy if exists ratings_update_own on public.ratings;
drop policy if exists ratings_delete_own on public.ratings;

-- Users can only see their OWN individual rows. The public site reads
-- aggregates (below), not raw rows.
create policy ratings_select_own on public.ratings
  for select using (auth.uid() = user_id);

create policy ratings_insert_own on public.ratings
  for insert with check (auth.uid() = user_id);

create policy ratings_update_own on public.ratings
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy ratings_delete_own on public.ratings
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Public aggregate function — anyone (anon + authenticated) can read
-- per-walk averages and counts, but never individual rows.
--
-- Why a SECURITY DEFINER function instead of a view?
--   The view-based pattern needed `security_invoker = false` to bypass the
--   ratings_select_own policy (otherwise anon visitors saw zero rows and
--   every walk showed ☆☆☆☆☆ (0) forever). But Supabase's linter — correctly
--   — flags definer-mode views as risky. A SECURITY DEFINER function is
--   the modern Supabase pattern: same behaviour (runs as the function owner,
--   bypassing RLS), but scoped to its explicit return columns so it can
--   never leak comments/user_ids.
--
-- Drop the old view if it exists, so re-running this script after the
-- view-based version is clean.
-- ---------------------------------------------------------------------------
drop view if exists public.walk_rating_aggregates;

create or replace function public.walk_rating_aggregates()
returns table (
  walk_id     integer,
  n           integer,
  avg_overall numeric,
  avg_scenery numeric,
  avg_family  numeric,
  avg_dogs    numeric,
  avg_value   numeric
)
language sql
security definer
stable
set search_path = public, pg_temp
as $$
  select
    walk_id,
    count(*)::int                  as n,
    round(avg(overall)::numeric, 2) as avg_overall,
    round(avg(scenery)::numeric, 2) as avg_scenery,
    round(avg(family)::numeric,  2) as avg_family,
    round(avg(dogs)::numeric,    2) as avg_dogs,
    round(avg(value)::numeric,   2) as avg_value
  from public.ratings
  group by walk_id;
$$;

-- Lock down the default-PUBLIC execute grant, then re-grant to the two
-- Supabase roles that should be able to call it.
revoke all on function public.walk_rating_aggregates() from public;
grant execute on function public.walk_rating_aggregates() to anon, authenticated;

-- ---------------------------------------------------------------------------
-- Helpful index for "show me the latest comments on walk X" (future feature).
-- ---------------------------------------------------------------------------
create index if not exists ratings_walk_id_updated_idx
  on public.ratings (walk_id, updated_at desc);
