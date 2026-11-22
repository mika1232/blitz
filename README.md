# Times Blitz

A minimalist times-tables blitz app for Year 4 (tables 2–12), built with Flask and SQLite.
No build step, no database server, no JavaScript framework.

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>.

On the **first run** the console prints a randomly generated admin password. To choose your own instead, set
`ADMIN_PASSWORD` before the first run:

```bash
ADMIN_PASSWORD="something-long" python app.py
```

Then go to <http://127.0.0.1:5000/admin/login>.

## Using it

**Admin panel (`/admin`)**

- Add a player with a name and a password you choose, or leave the password blank / press *Generate* for a friendly one such as `bravefox42`.
- Paste a list of names to add a whole class at once; passwords are generated for you.
- Edit a name or password inline, pause/resume a player, or delete them (their scores go too).
- *Print password slips* gives you a cut-out sheet to hand to each child.
- *Scores* on each player shows their history and their most-missed facts.
- Change the admin password at the bottom of the page.

Players sign in with **just their password** (not case sensitive, so tablet auto-capitalisation doesn't matter), so every password must be unique.

**Players**

- Choose **Questions** (preset or custom, 5–100) or **Time** (preset or custom, 15–600 seconds).
- Choose which times tables to practise (2–12).
- Answer on the keyboard (Enter to submit) or the on-screen keypad.
- Every fact from the chosen tables is asked once before any repeat. Mistakes are listed at the end, and a new personal best is flagged against earlier runs with the same settings.

## Configuration (environment variables)

| Variable | Purpose | Default |
| --- | --- | --- |
| `ADMIN_PASSWORD` | Admin password used on first run only | random, printed to console |
| `SECRET_KEY` | Session signing key | generated and saved in `instance/secret_key` |
| `BLITZ_DB` | SQLite file path | `instance/blitz.db` |
| `HOST` / `PORT` | Bind address / port | `127.0.0.1` / `5000` |
| `BLITZ_HTTPS` | Set to `1` when served over HTTPS (secure cookies) | off |

To let tablets on the same Wi-Fi connect, run with `HOST=0.0.0.0 python app.py`.

Forgot the admin password?

```bash
flask --app app set-admin-password
```

## Deploying

For real use, run behind a proper server rather than `python app.py`:

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```

Put it behind HTTPS (for example with Caddy or nginx) and set `BLITZ_HTTPS=1`. Back up the `instance/` folder.

## Good to know

- Player passwords are stored in plain text so you can read them back out and hand them to children. They are low-stakes access codes; don't reuse real passwords. The admin password is hashed.
- Scores are calculated in the browser and sent to the server, which sanity-checks them. That is fine for a classroom, but not tamper-proof.
- Login attempts are rate limited per IP address, and all forms are CSRF-protected.

## Project layout

```
app.py              Flask app, routes, database, admin logic
templates/          Jinja templates (login, menu, quiz, admin, slips)
static/style.css    All styling (light and dark mode)
static/quiz.js      The quiz engine
static/menu.js      Settings screen
instance/           Created on first run: database and secret key
```
