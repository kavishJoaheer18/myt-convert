# Deploying myt convert — step by step

This guide assumes you have never set up a Linux server before. Every command
shows what you should see afterwards, so you can tell at each point whether it
worked.

Follow it top to bottom. It takes about 30 minutes, most of which is waiting for
downloads.

---

## What you are building

Five programs running together on one server:

| Piece | What it does |
| --- | --- |
| **frontend** | The web page you open in a browser |
| **api** | Receives uploads, answers the web page |
| **worker** | Does the actual converting, including OCR |
| **postgres** | Remembers jobs, cells and corrections |
| **redis** | The queue the api uses to hand work to the worker |

You do not install these individually. Docker downloads and runs all five from
one command.

---

## Part 1 — Get a server

If you already have a Linux server, skip to Part 2.

### What to buy

Any provider works. These are the common ones:

| Provider | Plan that fits | Roughly |
| --- | --- | --- |
| Hetzner | CPX21 — 3 vCPU, 4 GB | €8/month |
| Hetzner | CPX31 — 4 vCPU, 8 GB | €15/month |
| DigitalOcean | Basic 4 GB / 2 vCPU | $24/month |
| Contabo | VPS S — 4 vCPU, 8 GB | €6/month |

**Recommended: 4 vCPU and 8 GB RAM.** It runs on 2 vCPU / 4 GB, but scanned
pages take 30–60 seconds each instead of about 10.

### When creating it

- **Operating system:** choose **Ubuntu 24.04** (or 22.04). Not CentOS, not
  Debian — the commands below assume Ubuntu.
- **Authentication:** choose **SSH key** if offered, otherwise **password**. If
  you pick password, the provider emails it to you or shows it once.
- **Disk:** 40 GB or more.

When it finishes, the provider shows you an **IP address** — four numbers like
`91.99.14.203`. Write it down. You need it in Part 2.

---

## Part 2 — Connect to the server from Windows

Open **PowerShell** (press Start, type `powershell`, press Enter) and run this,
replacing the IP with yours:

```bash
ssh root@91.99.14.203
```

The first time it asks:

```
The authenticity of host '91.99.14.203' can't be established.
Are you sure you want to continue connecting (yes/no)?
```

Type `yes` and press Enter. Then enter the password your provider gave you. The
password will **not appear as you type** — no dots, nothing. That is normal.
Type it and press Enter.

When you are in, the prompt changes to something like:

```
root@ubuntu-4gb-hel1-1:~#
```

**Everything from here on is typed into this window**, not into PowerShell on
your PC.

> If it says `Connection refused` or hangs, the server is probably still
> starting. Wait two minutes and try again.

---

## Part 3 — Install Docker

Docker is the program that runs the five pieces. Install it:

```bash
curl -fsSL https://get.docker.com | sh
```

This prints a lot of text for about a minute. When it finishes, check it worked:

```bash
docker --version
```

You should see something like:

```
Docker version 27.3.1, build ce12230
```

If you see `command not found`, the install failed — run the install line again
and read the last few lines for the error.

---

## Part 4 — Download the app

```bash
git clone https://github.com/kavishJoaheer18/myt-convert.git
```

You should see:

```
Cloning into 'myt-convert'...
remote: Enumerating objects: 200, done.
Receiving objects: 100% (200/200), done.
```

Move into the folder it created:

```bash
cd myt-convert
```

Your prompt now ends with `/myt-convert#`.

---

## Part 5 — Configure it

Copy the example settings into a real settings file:

```bash
cp .env.prod.example .env
```

### Generate a database password

```bash
openssl rand -base64 32
```

This prints a long random string, for example:

```
kJ8vN2mQ4xR7pL1sT6wY9bC3dF5gH0aE8iU2oP4nZ6k=
```

**Select it with your mouse and copy it** (in PowerShell, selecting text copies
it automatically). You will paste it in a moment.

### Edit the settings file

```bash
nano .env
```

A text editor opens inside the terminal. Use the **arrow keys** to move — the
mouse does not work here.

Find this line:

```
POSTGRES_PASSWORD=
```

Put the cursor at the end of it and paste your password (**right-click** pastes
in PowerShell). It should end up looking like:

```
POSTGRES_PASSWORD=kJ8vN2mQ4xR7pL1sT6wY9bC3dF5gH0aE8iU2oP4nZ6k=
```

**Optional:** if you want the AI double-check on conversions, also find
`ANTHROPIC_API_KEY=` and paste a key after it. Leave it empty if you do not have
one — everything still works, there is just no second opinion.

Now save and exit:

1. Press **Ctrl+O** (the letter O) — it asks `File Name to Write: .env`
2. Press **Enter** — it says `Wrote 30 lines`
3. Press **Ctrl+X** to leave the editor

You are back at the prompt.

---

## Part 6 — Start it

```bash
docker compose -f docker-compose.prod.yml up -d
```

**This takes 5–15 minutes the first time.** It downloads about 4 GB. You will
see many lines like:

```
[+] Running 5/5
 ✔ Container myt-convert-postgres-1  Started
 ✔ Container myt-convert-redis-1     Started
 ✔ Container myt-convert-api-1       Started
 ✔ Container myt-convert-worker-1    Started
 ✔ Container myt-convert-frontend-1  Started
```

If it stops with `required variable POSTGRES_PASSWORD is missing a value`, the
password did not save in Part 5. Run `nano .env` again and check the line.

---

## Part 7 — Check it works

```bash
docker compose -f docker-compose.prod.yml ps
```

All five should say `running`:

```
NAME                        STATUS
myt-convert-api-1           Up 2 minutes (healthy)
myt-convert-frontend-1      Up 2 minutes
myt-convert-postgres-1      Up 2 minutes (healthy)
myt-convert-redis-1         Up 2 minutes (healthy)
myt-convert-worker-1        Up 2 minutes
```

Then ask the app if it is alive:

```bash
curl -s localhost:3000/api/health
```

You want exactly this:

```
{"status":"ok","service":"myt convert"}
```

**If you see that, the app is working.** It is just not reachable from the
internet yet — that is Part 8.

> Anything says `Restarting` or `Exited`? See Troubleshooting at the bottom.

---

## Part 8 — Make it reachable from the internet

Right now the app only answers on the server itself. Pick **one** of these.

### Option A — Cloudflare Tunnel (recommended)

No firewall changes, no certificates, and it works even if the server has no
public IP. This is the same approach as ClinicFlow.

**On your PC, in a browser:**

1. Go to <https://one.dash.cloudflare.com>
2. Left menu → **Networks** → **Tunnels** → **Create a tunnel**
3. Choose **Cloudflared**, name it `myt-convert`, click **Save tunnel**
4. On the next screen you see a long token in the install command. Copy just the
   token — the long string after `--token`.
5. Do **not** close the page. Scroll to **Route tunnel** and fill in:
   - **Subdomain:** `convert`
   - **Domain:** pick your domain
   - **Service Type:** `HTTP`
   - **URL:** `frontend:3000`
6. Click **Save tunnel**

**Back on the server**, run this with your token pasted in place of `YOUR_TOKEN`:

```bash
docker run -d --name myt-cloudflared --restart unless-stopped --network myt-convert_default cloudflare/cloudflared:latest tunnel --no-autoupdate run --token YOUR_TOKEN
```

Wait about 30 seconds, then open `https://convert.yourdomain.com` in a browser.
The app should load with TLS already working.

### Option B — Caddy, if you have a domain pointed at the server

First, at your domain registrar, create an **A record** pointing
`convert.yourdomain.com` at your server's IP address. Then:

```bash
sudo apt install -y caddy
```

```bash
sudo nano /etc/caddy/Caddyfile
```

Delete everything in the file (hold **Ctrl+K** to cut lines) and type:

```
convert.yourdomain.com {
    reverse_proxy localhost:3000
}
```

Save with **Ctrl+O**, **Enter**, **Ctrl+X**, then:

```bash
sudo systemctl restart caddy
```

Caddy gets the HTTPS certificate itself within a minute.

---

## Part 9 — Using it day to day

### Watch what it is doing

```bash
docker compose -f docker-compose.prod.yml logs -f worker
```

Press **Ctrl+C** to stop watching. Every line carries the `job_id`, so one
conversion can be followed from start to finish.

### Update to the newest version

Whenever the code changes on GitHub, new images build automatically. To take
them:

```bash
docker compose -f docker-compose.prod.yml pull
```

```bash
docker compose -f docker-compose.prod.yml up -d
```

Only what changed is downloaded, and it takes a few seconds.

### Restart everything

```bash
docker compose -f docker-compose.prod.yml restart
```

### Stop everything

```bash
docker compose -f docker-compose.prod.yml down
```

Your data is safe — it lives in volumes, not in the containers.

### Back up

Two things matter: the database, and the uploaded and produced files.

```bash
docker run --rm -v myt-convert_postgres-data:/data -v $PWD:/backup alpine tar czf /backup/db-$(date +%F).tar.gz -C /data .
```

```bash
docker run --rm -v myt-convert_job-data:/data -v $PWD:/backup alpine tar czf /backup/files-$(date +%F).tar.gz -C /data .
```

Both land in the current folder as `.tar.gz` files. Copy them off the server with
`scp` from your PC.

---

## Troubleshooting

| What you see | What it means | What to do |
| --- | --- | --- |
| `required variable POSTGRES_PASSWORD is missing` | The password line in `.env` is empty | `nano .env`, set it, save, start again |
| A container says `Restarting` | It is crashing on startup | `docker compose -f docker-compose.prod.yml logs api` and read the last 20 lines |
| `curl: (7) Failed to connect` | The frontend is not up yet | Wait a minute, then `docker compose -f docker-compose.prod.yml ps` |
| Browser shows nothing at your domain | Tunnel or DNS not routing | Check the tunnel shows **Healthy** in Cloudflare |
| First scanned PDF takes minutes | OCR models downloading (~200 MB) | Normal, once only. Later ones are fast |
| `no space left on device` | Disk full | `docker system prune -a` clears old images |
| `error from registry: denied` | Usually a stale GHCR login. Docker sends a saved credential instead of falling back to anonymous, and a rejected one reads as "denied" | `docker logout ghcr.io` then pull again |
| `denied` straight after a push to GitHub | The images are still building | Watch the run at github.com/kavishjoaheer18/myt-convert/actions and retry when it goes green |

> GHCR answers `denied` for a package that does not exist as well as for one
> you cannot see — it hides the difference on purpose. So the same message means
> "still building", "wrong name", and "bad credential". Check in that order.

### Getting help

Collect this and send it to me:

```bash
docker compose -f docker-compose.prod.yml ps
```

```bash
docker compose -f docker-compose.prod.yml logs --tail 50
```

---

## Things to be aware of

- **There is no login.** Anyone who can reach the address can upload and
  download. Before sharing the URL, put Cloudflare Access in front of it
  (Zero Trust → Access → Applications), or keep the address private.
- **Uploaded files stay on the server** in the `job-data` volume, indefinitely.
  If you convert anything confidential, keep that in mind.
- **Restarting during a conversion** loses that job. Re-upload it.
