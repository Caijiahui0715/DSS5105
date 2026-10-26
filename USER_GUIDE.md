# User guide

English | [中文](使用说明.md)

The project has two parts, each run in its own terminal:

- **Backend** `server.py` (repository root): the agent, accounts, listing data, conversations and favorites.
- **Front end** `app/` (Streamlit): the web interface. All its data comes from the backend.

Run the commands below in PowerShell from the repository root.

## 1. What you need

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- An OpenAI API key and a model that supports tool calling
- PostgreSQL (installed and running on your computer, or the one the group shares) and its connection details: listings, accounts and conversations are all stored in it
- The final data files in `output-final-delivery/`, already in the repository and included when you clone it, for the first import into the database

Install the dependencies the first time:

```powershell
uv sync                    # backend, into .venv in the root
uv sync --project app      # front end, into app/.venv
```

## 2. The two .env files

Neither file is committed to Git; copy each from its template:

```powershell
Copy-Item .env.example .env
Copy-Item app\.env.example app\.env
```

When filling them in: one `KEY=value` per line, with comments on lines of their own, never after a value; restart the program concerned after a change.

### Root `.env` (backend)

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Required | The OpenAI API key |
| `OPENAI_MODEL` | Required | The name of a model that supports tool calling |
| `DB_HOST` `DB_PORT` `DB_NAME` `DB_USER` `DB_PASSWORD` | Required | PostgreSQL connection details, shared with the data pipeline (`src/dss5105`); on your own computer usually `localhost` and `5432` |
| `DB_CONNECT_TIMEOUT` | Optional | How many seconds to wait for the database at most, 10 by default |
| `ONEMAP_EMAIL` `ONEMAP_PASSWORD` | Needed to recompute commutes, search by place name, or work out commutes to places such as a gym | Used by `build_commutes.py`, `show_route.py` and the backend |
| `ONEMAP_CALLS_PER_MINUTE` | Optional | The most route queries per minute the backend sends to OneMap, 240 by default; run `check_onemap_rate.py` once and use its suggestion |
| `ONEMAP_TOKEN` | Optional | An existing OneMap token; without it, the email and password above are used to get one |
| `GOOGLE_MAPS_API_KEY` | Only to rerun `fix_transit_google.py` | |

At least these lines:

```
OPENAI_API_KEY=your key
OPENAI_MODEL=model name
DB_HOST=localhost
DB_PORT=5432
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
```

The old `AGENT_DB` is no longer used and can be removed if you have it; the old `sessions.sqlite` is no longer used either, and its accounts and conversations were not carried over, so just register again.

Once these are filled in, prepare the database (the first time, or when the listing data has a new version):

```powershell
.\.venv\Scripts\python.exe .\setup_database.py
```

It creates the database (if it does not exist yet) and the tables, imports the V1 and V2 listings and the commute times, and finally prints how many usable listings there are. It can be rerun; existing accounts and conversations are not affected.

### `app/.env` (front end)

| Variable | Required | Description |
|---|---|---|
| `BACKEND_URL` | Optional | The backend's address, `http://127.0.0.1:8000` by default; no change needed when the backend runs on this computer on the default port |
| `DEMO_USERNAME` `DEMO_PASSWORD` | Optional | With both set, the sign-in page shows "Continue with demo account", which signs in with this account in one click |
| `AGENT_MODE` | Optional | `mock` starts the offline demo: static data and a demo agent, no backend and no real accounts |

Register the demo account in the app first (for example with the username `demo_user`), then put its username and password in `app/.env`. Everyone who uses this button shares the same account, including its conversations and favorites.

## 3. Starting

First make sure PostgreSQL is running.

```powershell
.\.venv\Scripts\python.exe .\server.py                     # terminal 1: backend, http://127.0.0.1:8000
uv run --project app streamlit run app/streamlit_app.py    # terminal 2: front end, http://localhost:8501
```

Open http://localhost:8501 in a browser. The backend has to be running before the front end can sign in and chat.

To let classmates on the same Wi-Fi use it: the backend needs no change; have them open the Network URL Streamlit prints when it starts (`http://192.168.x.x:8501`). This is plain HTTP: passwords and conversations are not encrypted on the local network, so use it only on a network you trust.

## 4. Using it

**Sign in / register**

- Usernames are 3–20 letters, digits or underscores, case-insensitive, and a name already registered cannot be used again; passwords are at least 8 characters, entered twice when registering.
- When registering you can choose your NUS faculty, which commute times are computed to; you can also choose it later in Profile.
- Another commute destination: besides your faculty, you can add one more place, such as a roommate's faculty, a gym or an office. Just say in the conversation something like "my roommate is in the Faculty of Arts and Social Sciences" or "my gym is at Tiong Bahru Plaza, it should be convenient too".
  - It can have its own limit, such as "both within 30 minutes"; when you only say "convenient for both", listings are ranked by the longer of the two trips, so those with neither trip especially long come first.
  - Listing cards, replies and the comparison table show both commute times.
  - Only one more is allowed. When there is one already and you name another, the agent first reminds you that only one more can be added and asks whether to replace it; it replaces it only when you agree.
  - The first time a place is used, its routes are worked out live with OneMap: only for the listings that meet your other criteria, and the results are stored for later. With more than 120 listings to work out, the agent first asks whether you want to wait (30 seconds or more); you can also add a criterion first to narrow them down.
  - Use English place names, addresses or postcodes for places; Chinese place names may not be found.
  - Like other criteria, it belongs only to this conversation; to keep it for later, switch auto-save on or say "save to my profile".
- The budget, whole unit / room, bedrooms, how long a lease you plan to sign and the preferences in the registration form are sent to the agent as the first message, and its reply shows how the agent understood them.
- With "Remember me on this device for 7 days" ticked, opening the page again within 7 days signs you in automatically; signing out cancels it.
- The sign-in page and the conversation sidebar can switch between English and 中文. The agent replies in the language of each message, and in the interface language when a message shows no language (for example just `1000`).

**Home**

- Say what you need in one sentence, for example "budget SGD 2,000, a room in a shared flat, close to the MRT, only 6 months". The agent shows its progress while it works, and "How this reply was made" can be expanded under each reply.
- Ask about costs, for example "how much does the second one cost in total" or "how much do I pay at signing", and the agent lists the total rent, stamp duty, deposit and payment at signing; the first line says which assumptions were used (lease term, deposit, whether there is an agent), and when you say you use an agent or a different lease term, it works them out again.
- "This conversation's criteria", at the top on the right, can be expanded: it shows which criteria the agent is searching with now and which of your sentences each came from. Changing criteria here sends a message to the agent and changes only this conversation. "Save to long-term profile" first lists how the long-term profile would change, and saves only after you confirm.
- Once the conversation has criteria, a bar above the chat input asks "Save the criteria you change in conversations to your long-term profile automatically?": after "Auto-save", criteria changed in conversations are saved to the long-term profile automatically (and the changes so far are saved at once), and replies say the criteria were updated and saved to the long-term profile automatically; × stops the question for good.
- The map on the right shows the recommended listings, with a graduation cap for your faculty. The enlarge button at the map's top-right corner opens it in a large window: the recommended listings, your favorites (red hearts), the compared listings (numbers) and your faculty are all in it, with a legend below; clicking a listing shows its photo and a short summary, and you can open the original listing, save it, add it to compare or see its details. The listing panel below switches between the recommended listings, each showing:
  - a photo of the listing, with "Photo from the original PropertyGuru listing" below it, which opens the original listing; a placeholder note when the photo cannot load
  - its rank, and whether it "Meets your conditions" or "Needs confirmation" (listing the conditions to check with the landlord)
  - monthly rent, MRT, the commute time to your faculty, the lease term (the shortest lease the landlord accepts) and the link check result
- On a listing card: "Open ↗" opens the original listing in a new tab, "Save" adds it to favorites, and "Add to compare" puts it in this conversation's compare box (up to three; no need to save first, and nothing is compared yet).
- Comparing: put the listings to compare in the compare box first, then press "Compare"; only then is "Compare A, B and C" sent in the conversation, the agent explains the differences and trade-offs in its reply, and once the reply is in, the comparison table pops up by itself, once (the key differences and the full table). The compare box is at the top of Favorites: on the left the favorites not in the box yet, on the right the box; drag with the mouse, or on a phone hold the ⠿ on the left of a listing and drag, to put listings in or take them out. The order in the box is the order of the table's columns, and "Clear" empties it at once. The "Compare" bar between the map and the recommended listings on Home has "Compare" too. When the box holds exactly the listings compared last, the button becomes "View comparison", which opens the table without asking the agent again; when the box holds other listings, "Last comparison" shows the previous table. After comparing, the box keeps those listings, so swapping one takes a single drag. The map marks the compared listings 1, 2, 3 (the same as the table's column numbers) and frames them together with your faculty. While the agent is replying, the compare box and its buttons wait. You can also just say "compare the first and the third" in the conversation; the box then holds those listings, and the "Compare" bar's button pulses with a "New" mark. Comparisons are saved with the conversation and are still there when it is reopened.
- The conversation sidebar on the left: start a new conversation or open an earlier one. Conversations are all saved with the account. A conversation the agent is replying in has a spinning icon before its title; it keeps spinning when you switch to another conversation mid-reply, and goes once the reply is in, which you see when you open it again. The open conversation's row has a bin on the right that asks once before deleting the conversation (the long-term profile, favorites and exclusions are not affected; it cannot be deleted while a reply is being generated), and a new conversation takes its place. While long-term memory is on, a new conversation starts with the long-term profile's criteria already set, and the first message says which ones.
- In the conversation you can also say "save to my profile", "what is my long-term profile", "use my long-term profile", "turn off long-term memory", "turn auto-save on / off" and "forget my information".

**Favorites**: favorites belong to the account, are shared by all its conversations and are visible to the agent, so you can ask it in chat to compare or explain them. New searches don't recommend favorites again, and when a favorite fully meets the criteria, the end of the reply mentions it. To compare favorites, use the compare box at the top of the Favorites page.

**Profile**:
- Choose your faculty (saved to the account straight away).
- Long-term profile: the criteria new conversations start from. Long-term memory can be switched on or off (off is only a pause: the saved criteria remain, but new conversations don't use them and they cannot be changed); with "Auto-save" below it switched on, criteria changed in conversations are saved here automatically (paused while long-term memory is off). Change the form directly and save; under each criterion it says where it came from; criteria the form does not have are listed under "Other criteria" and can be removed one by one; the long-term profile can also be deleted (the switch stays as it is).
- Excluded listings: listings excluded by saying "not this one" in a conversation can be restored here.
- Delete all my data: deletes all conversations, the long-term profile, favorites, exclusions and the faculty, and signs out; the account is kept. A confirmation must be ticked first.

## 5. Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests    # backend, including the endpoints the front end calls
uv run --project app pytest app/tests                        # front end (offline demo mode, no backend needed)
```

The backend tests use a `<DB_NAME>_test` database on the same PostgreSQL server (created automatically the first time) and never touch the real database. When PostgreSQL cannot be reached, the tests that need the database show as skipped with the reason, and the rest run as usual.

## 6. Common problems

| What you see | What to do |
|---|---|
| The backend says `Set OPENAI_API_KEY and OPENAI_MODEL in .env first` at startup | These two are missing from the root `.env` |
| The backend or `setup_database.py` says `.env is missing DB_USER. Add it and run again` (or another `DB_*` setting) | That setting is empty in the root `.env`; all five `DB_*` settings are needed |
| The backend says at startup that it cannot connect to PostgreSQL, followed by `connection timeout expired` or `Connection refused` | The PostgreSQL service is not running; see "PostgreSQL is not running" below |
| The backend says at startup that it cannot connect to PostgreSQL, followed by `password authentication failed` | `DB_USER` or `DB_PASSWORD` in `.env` is wrong |
| The backend says at startup that the listing tables are incomplete or there are no usable listings | Run `setup_database.py` |
| Listing cards have no photo | After a new data version (for example `rental_data_v2.csv` gaining the `photos` column), rerun `setup_database.py` and restart the backend and Streamlit; the photos are on PropertyGuru's servers, so an internet connection is needed |
| The chat replies "The database cannot be reached right now. Try again in a moment." | The database disconnected; make sure PostgreSQL is running, and the next message reconnects automatically |
| The page says it cannot reach the agent backend | Start `server.py` first; when the backend is not at the default address, change `BACKEND_URL` in `app/.env` |
| The sign-in page has no "Continue with demo account" | `app/.env` needs both `DEMO_USERNAME` and `DEMO_PASSWORD`; restart Streamlit after changing it |
| A card says "Choose your faculty in Profile to see commute times." | Choose your faculty in Profile |
| A reply says commute times to a place could not be worked out for some listings right now | OneMap is unreachable or rate-limiting for now, and the next search tries again; if it keeps happening, check `ONEMAP_EMAIL` / `ONEMAP_PASSWORD` in `.env` |
| The budget changed in a conversation but the long-term profile did not | Without auto-save, criteria changed in a conversation belong only to that conversation: press "Save to long-term profile" in "This conversation's criteria", or say "save to my profile"; to save automatically from now on, switch "Auto-save" on |
| A change to `.env` has no effect | Restart the program concerned (the backend or Streamlit) |
| It says your sign-in has ended | Tokens expire after 7 days, or you signed out elsewhere; sign in again |

### PostgreSQL is not running

Once installed, PostgreSQL is a Windows service that starts with the computer, but sometimes it is stopped: its startup type was changed to manual, or it failed to start at boot. Check its status in PowerShell; `Status` should be `Running`:

```powershell
Get-Service postgresql*
```

When it is not `Running`, open PowerShell **as administrator**:

```powershell
Start-Service postgresql*                                      # start it now
Get-Service postgresql* | Set-Service -StartupType Automatic   # start it with the computer from now on
```

You can also open Services (`services.msc`), find a name like `postgresql-x64-16` (the number is the version), right-click it and choose Start, then set its startup type to Automatic under Properties.

- If it fails to start: read PostgreSQL's log, usually in `C:\Program Files\PostgreSQL\16\data\log` (with your installed version number).
- If the service is running but still cannot be reached: check that `DB_HOST` and `DB_PORT` in `.env` match the port chosen when installing PostgreSQL (5432 by default).

Before a demo, run `Get-Service postgresql*` once, then start `server.py`; only when it prints "Open http://127.0.0.1:8000" is the database connected and are the listings there.

For more details (data sources, the API, the agent's rules), see `README.md`; for the front end's structure, see `app/README.md`.
