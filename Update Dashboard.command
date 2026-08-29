#!/bin/bash
# Double-click this file in Finder to refresh the dashboard.
#
# It does the whole loop with no typing: sync with GitHub, fetch this week's
# data, show what came back, optionally publish it, optionally open a local
# preview. Every step is explained as it happens and anything that goes wrong
# stops the script with a plain-English message rather than a stack trace.
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
say "1/5  Checking Python packages"
if ! python3 -c "import pandas, requests, yfinance, openpyxl, xlrd" 2>/dev/null; then
  warn "Something is missing — installing from requirements.txt"
  python3 -m pip install -q -r requirements.txt || die "Could not install the Python packages."
fi
ok "all present"

# ---------------------------------------------------------------------------
# The weekly GitHub run also writes to the database and pushes it. Pulling
# first keeps the local copy in step; skipping this is how you end up with a
# conflict on data/markets.db.
say "2/5  Syncing with GitHub"
if git rev-parse --git-dir >/dev/null 2>&1; then
  if git pull --rebase --autostash 2>&1 | grep -qiE "conflict|error"; then
    die "Git could not sync automatically. Open this folder with Claude and say: 'the dashboard pull conflicted'."
  fi
  ok "up to date with GitHub"
else
  warn "not a git repo — skipping"
fi

# ---------------------------------------------------------------------------
say "3/5  Fetching this week's data"
printf "%s  Only what is newer than what you already have.%s\n\n" "$dim" "$off"
if ! python3 pipeline.py --mode live 2>&1 | grep -E "Ingest:|Quality:|Export:|Catalog synced|Wrote|status changed|ERROR" | sed 's/^INFO [^:]*: /  /; s/^WARNING [^:]*: /  ! /'; then
  die "The pipeline failed. Scroll up for the reason."
fi
ok "done"

# ---------------------------------------------------------------------------
say "4/5  Publishing"
if git rev-parse --git-dir >/dev/null 2>&1 && ! git diff --quiet HEAD -- data/markets.db site/data/latest.json data/DATA-CATALOG.csv 2>/dev/null; then
  if ask "Publish this to the live site?"; then
    git add data/markets.db site/data/latest.json data/DATA-CATALOG.csv
    git commit -q -m "Weekly data refresh $(date -u +%Y-%m-%d) (run from Mac)" \
      && git push -q origin main && ok "pushed to GitHub"
    # Pushing alone does not rebuild the page — the workflow does that.
    if command -v gh >/dev/null 2>&1; then
      gh workflow run "Weekly data refresh" --ref main >/dev/null 2>&1 \
        && ok "site rebuild started — live in about two minutes" \
        || warn "could not start the rebuild; Actions tab → Run workflow"
    else
      warn "install the 'gh' tool to rebuild the site automatically, or use the Actions tab"
    fi
  else
    warn "not published — your local copy is updated, the live site is not"
  fi
else
  ok "nothing new to publish (already up to date)"
fi

# ---------------------------------------------------------------------------
say "5/5  Preview"
if ask "Open the dashboard in your browser?"; then
  ( cd site && python3 -m http.server 8000 >/dev/null 2>&1 ) &
  server=$!
  sleep 2
  open "http://localhost:8000"
  printf "\n%sShowing your local copy at http://localhost:8000%s\n" "$dim" "$off"
  printf "%sLive site: https://randaledd.github.io/markets-dashboard/%s\n" "$dim" "$off"
  printf "\nPress any key to stop the preview and close. "
  read -r -n 1
  kill $server 2>/dev/null
else
  printf "\nPress any key to close. "; read -r -n 1
fi
printf "\n"
