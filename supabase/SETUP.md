# Ratings — Supabase setup (10 minutes)

One-time setup. After this, every site deploy automatically includes working
walker ratings with magic-link sign-in.

You already have the project: **https://zkwsljtpkdxzsyulenai.supabase.co**

---

## 1. Run the SQL schema (2 min)

1. Open your project: https://zkwsljtpkdxzsyulenai.supabase.co
2. Left sidebar → **SQL Editor** → **New query**
3. Copy-paste the entire contents of [`supabase/schema.sql`](schema.sql)
4. Click **Run**

You should see a success message. This creates the `ratings` table, the
row-level security policies that stop anyone from tampering with other
users' ratings, and the public `walk_rating_aggregates` view the site reads
averages from.

Re-running the script later is safe — every `CREATE` is idempotent.

---

## 2. Configure auth (2 min)

1. Left sidebar → **Authentication** → **Providers**
2. Confirm **Email** is enabled (it is by default). No need to configure any
   other provider.
3. Left sidebar → **Authentication** → **URL Configuration**
4. Set **Site URL** to your live site:
   `https://edition74.github.io/south-wales-walks/`
5. Under **Redirect URLs**, add the same URL plus a localhost entry for
   testing:
   - `https://edition74.github.io/south-wales-walks/`
   - `http://localhost:8000` *(optional — for running `python -m http.server` locally)*

Without these, magic-link emails send fine but the links fail with "redirect
not allowed".

---

## 3. Grab your anon key (1 min)

1. Left sidebar → **Project Settings** → **API**
2. Under **Project API keys** you'll see two keys:
   - `anon` `public` — this is the one we need. Safe to expose in the browser.
   - `service_role` `secret` — **never** put this in the browser or git.
3. Copy the `anon` key.

---

## 4. Add it as a GitHub Actions secret (2 min)

1. Go to your repo: https://github.com/Edition74/south-wales-walks
2. **Settings → Secrets and variables → Actions → New repository secret**
3. Add two secrets:
   - Name: `SUPABASE_URL`     Value: `https://zkwsljtpkdxzsyulenai.supabase.co`
   - Name: `SUPABASE_ANON_KEY` Value: *(paste the anon key from step 3)*
4. Save.

The deploy workflow (`.github/workflows/deploy.yml`) already reads these
two secrets and injects them at build time. On your next push, the live
site will show the ratings widget under each walk's details.

---

## 5. Test it (1 min)

After your next push:

1. Open the live site, expand any walk.
2. Scroll to the bottom of the expanded details — you should see the
   ratings panel with "Sign in to rate this walk".
3. Enter your email, check your inbox for the magic link.
4. Click the link — it takes you back to the site, signed in.
5. Rate a walk. Refresh — the aggregate star count should update.

---

## How to see the data

- **Raw rows**: SQL Editor → `select * from ratings order by updated_at desc;`
- **Averages**: SQL Editor → `select * from walk_rating_aggregates order by n desc;`
- **Unique raters**: `select count(distinct user_id) from ratings;`

---

## If something goes wrong

**Magic-link email never arrives**
- Check Supabase's email quota (free tier: 4 emails/hour). For production
  you'll want to plug in Resend or Postmark — **Authentication → Email
  templates → SMTP settings**.
- Check spam folder.

**"redirect not allowed" after clicking the link**
- Step 2.4/2.5 — the link's target URL must be in the Redirect URLs list.

**Ratings widget shows "Ratings are not yet configured"**
- The secrets haven't been plumbed through. Re-check step 4, then trigger a
  new build (Actions tab → "Build & deploy walks app" → "Run workflow").

**RLS errors when saving** (`new row violates row-level security policy`)
- You're not signed in, or `auth.uid()` isn't matching the `user_id` you're
  sending. Open the browser console and check `await
  supabase.auth.getSession()`.

---

## What it costs

Supabase free tier: **2 projects, 500 MB database, 50k monthly auth users,
2 GB file storage, 5 GB egress, 500k edge function invocations**. Ratings
use ~1 KB per row, so ~500,000 ratings fit free. You'll only hit limits
with scale most founders would kill for.

---

## Editors (task #44)

The same Supabase project also gates access to the `/editor.html` page. The
schema includes a `public.editors` allow-list table; only users whose row
appears there can open the editor.

### One-time: add yourself as the first editor

1. Visit https://edition74.github.io/south-wales-walks/editor.html and sign
   in with your usual editor email (`edition74@outlook.com`). The
   magic-link form will email you a one-time link. Click it. You'll land
   back on the editor page; it'll show "Sorry, you're not on the editors
   list" — that's expected, you haven't been added yet.
2. Open the Supabase SQL Editor and run:
   ```sql
   insert into public.editors (user_id, email, display_name)
   select id, email, 'Jason'
   from auth.users
   where email = 'edition74@outlook.com';
   ```
3. Refresh the editor page. You should pass the gate and be prompted for
   a GitHub Personal Access Token (one-off paste, stored in your browser).

### Adding a future editor

Same flow:

1. They sign in via the editor page (creates their `auth.users` row).
2. You run:
   ```sql
   insert into public.editors (user_id, email, display_name)
   select id, email, 'Their Name'
   from auth.users where email = 'theirs@example.com';
   ```
3. They refresh — they're in.

### Removing an editor

```sql
delete from public.editors where email = 'theirs@example.com';
```

### Why no self-service signup?

The `editors` table has only a SELECT policy and no INSERT/UPDATE/DELETE
policies. Writes are only possible via the SQL Editor with the service-role
key, which only you have. There is deliberately no API surface for someone
to add themselves.
