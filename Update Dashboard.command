#!/bin/bash
# Double-click this file in Finder to refresh the dashboard.
#
# It does the whole loop with no typing: sync with GitHub, fetch this week's
# data, publish it to the live site, and optionally open a local preview.
# Every step is explained as it happens and anything that goes wrong stops the
# script with a plain-English message rather than a stack trace.
#
# Publishing is not a question any more. The data files are committed files and
# the live site is a checkout of them, so a refresh that stops on this Mac
# leaves two different dashboards: the one on screen and the one at the URL.
# pipeline.py now syncs, pushes and waits for the deploy as part of the run
# itself -- this script just narrates it.
#
# macOS runs a .command file in Terminal on double-click. Keep the executable
# bit set (chmod +x) or Finder will open it in a text editor instead.

cd "$(dirname "$0")" || exit 1

bold=$(tput bold 2>/dev/null); dim=$(tput dim 2>/dev/null)
red=$(tput setaf 1 2>/dev/null); green=$(tput setaf 2 2>/dev/null)
yellow=$(tput setaf 3 2>/dev/null); off=$(tput sgr0 2>/dev/null)

say()  { printf "\n%s%s%s\n" "$bold" "$1" "$off"; }
ok()   { printf "  %s✓%s %s\n" "$green" "$off" "$1"; }
warn() { printf "  %s!%s %s\n" "$yellow" "$off" "$1"; }
die()  { printf "\n%s✗ %s%s\n\n%s" "$red" "$1" "$off" "Press any key to close. "; read -r -n 1; exit 1; }
ask()  { printf "\n%s%s%s [Y/n] " "$bold" "$1" "$off"; read -r reply; [[ ! $reply =~ ^[Nn] ]]; }

clear
printf "%s╭──────────────────────────────────────────╮\n" "$bold"
printf "│   Markets Dashboard — weekly refresh     │\n"
printf "╰──────────────────────────────────────────╯%s\n" "$off"
printf "%sStores each completed week's Friday close.%s\n" "$dim" "$off"

command -v python3 >/dev/null || die "Python 3 is not installed."

# ---------------------------------------------------------------------------
say "1/4  Checking Python packages"
if ! python3 -c "import pandas, requests, yfinance, openpyxl, xlrd" 2>/dev/null; then
  warn "Something is missing — installing from requirements.txt"
  python3 -m pip install -q -r requirements.txt || die "Could not install the Python packages."
fi
ok "all present"

# ---------------------------------------------------------------------------
# One call does the lot: fast-forward onto GitHub first (the Saturday run
# pushes a newer database, and starting behind it is how you get a conflict on
# a binary file), fetch only what is newer than what is stored, rebuild the
# page data, push it, and wait for GitHub Pages to actually serve it. The
# filter turns the pipeline's log into English.
say "2/4  Fetching this week's data and publishing it"
printf "%s  Only what is newer than what you already have.%s\n" "$dim" "$off"
printf "%s  The push and the site rebuild take a couple of minutes.%s\n\n" "$dim" "$off"
python3 pipeline.py --mode live 2>&1 \
  | grep -E "Sync:|Ingest:|Quality:|Export:|Catalog synced|Wrote|Publish:|status changed|ERROR" \
  | sed 's/^INFO [^:]*: /  /; s/^WARNING [^:]*: /  ! /; s/^ERROR [^:]*: /  x /'
# The status of a pipeline is its LAST command, which here is sed and always
# succeeds -- so read the FIRST one instead. Without this, a crashed refresh
# would be narrated as a successful one.
[ "${PIPESTATUS[0]}" -eq 0 ] || die "The refresh failed. Scroll up for the reason."

# ---------------------------------------------------------------------------
# Asked again on its own, because "is the live site showing what I just
# fetched?" is the entire point of the exercise and should not have to be
# picked out of the log above.
say "3/4  Checking the live site matches"
if python3 publish.py --check 2>&1 | sed 's/^/  /'; then
  ok "the live site is serving this run"
else
  warn "the live site is still behind -- the deploy may simply be slow."
  warn "Give it a minute, then double-click this file again."
fi

# ---------------------------------------------------------------------------
say "4/4  Preview"
if ask "Open the dashboard in your browser?"; then
  ( cd site && python3 -m http.server 8000 >/dev/null 2>&1 ) &
  server=$!
  sleep 2
  open "http://localhost:8000"
  printf "\n%sYour local copy is at http://localhost:8000 and the live site at%s\n" "$dim" "$off"
  printf "%shttps://randaledd.github.io/markets-dashboard/ now holds the same data.%s\n" "$dim" "$off"
  printf "\nPress any key to stop the preview and close. "
  read -r -n 1
  kill $server 2>/dev/null
else
  printf "\nPress any key to close. "; read -r -n 1
fi
printf "\n"
