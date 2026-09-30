# README - Ophio

Yeah you guessed it right—— ***Ophio***​ allow you to control your PC in another device through LAN—— An upgrade for ***NoGame***!


**Blivno**

**19.4.2026**

---

Dearest U: ***Ophio2*** coming!

At ***Ophio***, we removed the control of mouse moving, for the reason that the server developed by **JavaScript** is slow and inefficient.

At the past 3 weeks, so much **schoolwork** dragged me a lot. I was too tired to go on improving ***Ophio***.

Finally on yesterday, I picked a cherished time to fasten my improvement—— rebuilding the server with **Go**, which ended at midnight.

I was filled with sorrows and sentiments of being touched—— Yes, I got down recently, since hurried schoolwork, parting with old friends, teachers, parents, and my **Lover Sis**.

I'm not sure if I've fallen in love with her, that's such an unbelievable news, but truly happening on me, rising a strong wave in my deepest heart. I get no idea to pour my emotion at midnight, so much complicated feelings, to anyone. I can not, influence others because of my own messes.

*Github* & ***Ophio*** somehow become my outlet... Probably I'd spend some time on schoolwork and **self-development**—— **Never count on love😭**

I'll buy me so many pretty dresses, run on the playground circle by circle, and pass my hospitality to everyone. That's not their faults. I'll farewell to my Lover Sis, we'll be **most glued** friends from on.


**Blinvo is Blinvo, eternally revive from despair.**

**10.5.2026**

---

**Update 6.8.2026**

Ophio is back — now shipped as source code instead of a rar. The repo is re-organized:

- `app/` — PyQt5 client (main window, screen capture, web assets)
- `server/` — Go server (rebuild via `build.bat`, outputs `ophio-server.exe`)
- `legacy/` — the old JavaScript server implementation, kept for history

What changed this round:

- **Binary frames** — screen frames are sent as raw JPEG bytes over WebSocket instead of base64 text (~33% less bandwidth, less CPU on both ends)
- **Idle skipping** — no frame is sent while the screen and mouse stay still
- **Frame dropping** — when the network falls behind, stale frames are dropped instead of queuing up
- **Single instance** — launching Ophio again wakes the existing window instead of spawning a second copy
- **Build chain fixed** — the Go `server/` package lives inside the module again, `go build` works out of the box

**Update 30.9.2026**

A desktop remote-control page joins the mobile one:

- **`pc.html`** — from a PC, open the server address and you land here: one shared screen, no buttons. Hover the screen to take over — real mouse (left / right / middle, drag, wheel) and keyboard are sent straight to the host, like sitting in front of it
- **Esc** releases every held key and pauses control; move the cursor out of the screen and back to resume
- **UA routing** — desktop browsers get `pc.html`, phones get `index.html`; force either with `?view=pc` / `?view=mobile`
- **Protocol** — control messages now carry `dx/dy`, `button`, `amount`, `clicks`; zero coordinates survive the relay; mouse-move traffic is no longer logged or acked, so the console stays quiet at 60 Hz
- **Host input** — cursor moves are instant (the old 100 ms animation is gone), press/release pairs enable drags, wheel is signed notches, and `KeyboardEvent.code` maps the full keyboard (Home / End / PageUp / F13-24 …)
- **Gates** — `ruff check .` and `pytest` run from the repo root, config in `pyproject.toml`, tests in `tests/`
- **Repo layout** — `app/` is gone; the client (`Ophio.pyw`, `screen_capture.py`, `pc_protocol.py`, `public/`) now sits at the repo root, next to `server/` and `legacy/`

Run: build the Go server with `server/build.bat`, then `python Ophio.pyw`. Or package the client via `package.bat` (PyInstaller).
