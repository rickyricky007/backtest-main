# Git pull & permissions (VPS / `ubuntu` vs `algotrading`)

## What goes wrong

`/opt/algotrading/app` is owned by **`algotrading`**. If you run **`git pull`** as **`ubuntu`**, Git must write `.git/FETCH_HEAD` and fails with:

`error: cannot open .git/FETCH_HEAD: Permission denied`

This is expected: **two users, one working tree**.

## Permanent rule

| Who owns `/opt/algotrading/app` | Who runs `git pull` |
|--------------------------------|---------------------|
| **`algotrading`**              | **`algotrading`** (or `sudo -u algotrading`) |

Do **not** mix **`sudo git`** as root in that directory without fixing ownership after.

## Daily workflow (pick one)

### A — Recommended: one script (pull + deps + restart)

After you deploy this repo to the server:

```bash
sudo bash /opt/algotrading/app/deploy/update.sh
```

`update.sh` runs **`git pull` and `pip`** as **`algotrading`**, then restarts services.

### B — Pull only (no pip / no restart)

```bash
sudo bash /opt/algotrading/app/deploy/git_pull.sh
```

### C — Interactive shell as deploy user

```bash
sudo -iu algotrading
cd /opt/algotrading/app
git pull
exit
```

## One-time repair (ownership messed up)

From `fix_vps.sh` (already does `chown -R algotrading:algotrading`):

```bash
sudo bash /opt/algotrading/app/deploy/fix_vps.sh
```

Or minimal:

```bash
sudo chown -R algotrading:algotrading /opt/algotrading/app
```

## Optional: passwordless `sudo -u algotrading` for `ubuntu`

Only if you want `ubuntu` to run pulls without typing a password — use **`sudo visudo`** and a **narrow** rule (example pattern; adjust group/user to match your server):

```text
ubuntu ALL=(algotrading) NOPASSWD: /usr/bin/git, /bin/bash
```

Prefer **scripts** (`update.sh` / `git_pull.sh`) over broad NOPASSWD.

## Clone / deploy convention

- Clone or extract the app as **`algotrading`**, or immediately after clone:  
  `sudo chown -R algotrading:algotrading /opt/algotrading/app`
- CI/CD should run **`git pull`** as **`algotrading`** (same as above).

## “Divergent branches” / dashboard still shows **old** UI

If you see:

`fatal: Need to specify how to reconcile divergent branches`

then **`git pull` did not update files** — Streamlit is still running old code. A script that **ignores** the failure and still runs `pip` + `restart` made this easy to miss; use the current **`deploy/update.sh`** (it uses **`set -e`** and **`git config pull.rebase false`** + **`git pull --no-rebase`**).

**Option 1 — merge (keeps any local VPS commits, may create a merge commit):**

```bash
sudo -u algotrading -H bash -c 'cd /opt/algotrading/app && git config pull.rebase false && git pull --no-rebase'
sudo bash /opt/algotrading/app/deploy/restart.sh
```

**Option 2 — VPS should match GitHub exactly (wipe local server-only changes):**

```bash
# replace `main` with your default branch if different
sudo bash /opt/algotrading/app/deploy/vps_sync_origin.sh main
sudo bash /opt/algotrading/app/deploy/update.sh
```

Non-interactive reset: `SKIP_CONFIRM=1 sudo -E bash /opt/algotrading/app/deploy/vps_sync_origin.sh main`

After a successful pull, **hard-refresh the browser** (Ctrl+Shift+R) or open an incognito window to avoid cached old UI.
