#!/bin/sh
# Resolve this installation, never the caller's current directory.
HERE=$(CDPATH= cd -P "$(dirname "$0")" && pwd) || exit 2
PYTHON=${ARCHIVIST_PYTHON:-python3}
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 12))' >/dev/null 2>&1; then
    printf '%s\n' 'Archivist requires Python 3.12 or newer. See START-HERE.txt.' >&2
    if [ -t 0 ]; then printf 'Press Enter to close. '; read answer; fi
    exit 2
fi
"$PYTHON" "$HERE/../archivist.py" gui "$@"
status=$?
if [ "$status" -ne 0 ] && [ -t 0 ]; then
    printf 'Stopped with error %s. Press Enter to close. ' "$status" >&2
    read answer
fi
exit "$status"
