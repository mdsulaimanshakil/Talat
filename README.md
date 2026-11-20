# TALAT

A three-player, three-board AI strategy game, based on the board game *Talat* by Bruce Whitehill.
CSE 3210 Artificial Intelligence Lab final project, KUET.

Three AI agents play it: Greedy Best-First Search, Max^n / Paranoid alpha-beta, and Monte Carlo Tree Search (UCB1).
The rules and the build steps are in [BUILD_PLAN.md](BUILD_PLAN.md).

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
pytest                                          # run the tests
python -m talat.cli                             # text-mode game
python -m talat.tournament --agents greedy,paranoid,mcts   # AI tournament, CSVs in results/
flet run                                        # the app, in a desktop window
```

## On your phone

### Quick test, no build needed

1. Install the free **Flet** app on your phone (Google Play, or the App Store on an iPhone).
2. Connect the phone and the computer to the same Wi-Fi.
3. In this folder run `flet run --android` (or `flet run --ios`) and scan the QR code with the Flet app.

### Installable Android app (APK)

```bash
flet build apk --arch arm64-v8a
```

- The APK lands in `build/apk/`. Copy it to the phone (USB cable, Google Drive, …), open it, and allow "install unknown apps" when Android asks.
- With USB debugging switched on, `adb install build/apk/*.apk` installs it directly.
- `--arch arm64-v8a` builds for 64-bit ARM phones, which is almost every Android phone from the last 7 years. Leave it out to build one bigger APK that also runs on older 32-bit phones and emulators.
- The first build downloads the Flutter SDK (to `~/flutter`) and Java 17 (to `~/java`), several GB in total, and takes 10–20 minutes. Later builds are much faster.
- App name, package id (`bd.ac.kuet.cse.talat`), icon (`assets/icon.png`) and which files stay out of the APK are set in `pyproject.toml`.
- If the build stops with `CERTIFICATE_VERIFY_FAILED` (common with the python.org installer on macOS), run it like this so Python uses the certificates from the `certifi` package:
  ```bash
  SSL_CERT_FILE="$(python -c 'import certifi; print(certifi.where())')" flet build apk --arch arm64-v8a
  ```
- To reuse an Android SDK you already have (e.g. from Android Studio), set `ANDROID_HOME=~/Library/Android/sdk` first.

## Layout

```
main.py          app entry point (flet run / flet build)
assets/          app icon and the title font (Libre Baskerville, OFL licence)
talat/
  engine.py      game rules
  ai/            the three AI agents
  cli.py         text-mode game
  tournament.py  AI vs AI matches and metrics
  session.py     one game as the app sees it (no UI code)
  app.py         Flet UI
tests/           pytest tests
```
