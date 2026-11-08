#!/bin/sh
# render-fast.sh: rasterize one SVG with rsvg-convert, for the inner loop of
# vector work. It needs no browser and about 10 MB of memory, so it does not
# go through tools/heavy.py.
#
# Usage: tools/art/render-fast.sh in.svg SIZE out.png [bg-colour] [ink-colour]
#
#   SIZE        the output box in pixels (width and height); the aspect ratio
#               is kept, so a non-square SVG fits inside the box
#   bg-colour   background, any CSS colour (default: transparent)
#   ink-colour  the colour that currentColor resolves to (default: black);
#               pass a light one with a dark background
#
# Examples:
#   tools/art/render-fast.sh web/src/lib/icons/svg/coin.svg 512 /tmp/coin.png
#   tools/art/render-fast.sh coin.svg 24 /tmp/coin-24-dark.png '#1c1915' '#f4ecdc'
#
# librsvg differs from Chrome in places (CSS support, filters, text). Check
# a finished batch in the browser with tools/chrome/svg-render.mjs.

set -eu

prog=$(basename "$0")

usage() {
  printf 'Usage: %s in.svg SIZE out.png [bg-colour] [ink-colour]\n' "$prog" >&2
  exit 2
}

die() {
  printf '%s: %s\n' "$prog" "$1" >&2
  exit "${2:-1}"
}

[ $# -ge 3 ] && [ $# -le 5 ] || usage
in=$1
size=$2
out=$3
bg=${4:-}
ink=${5:-}

case $size in
'' | *[!0-9]*) die "SIZE must be a positive integer, got '$size'" 2 ;;
esac
[ "$size" -gt 0 ] || die "SIZE must be a positive integer, got '$size'" 2
[ -f "$in" ] || die "no such file: $in"
command -v rsvg-convert >/dev/null 2>&1 ||
  die 'rsvg-convert not found (macOS: brew install librsvg; Debian: apt install librsvg2-bin)' 127

outdir=$(dirname -- "$out")
command mkdir -p -- "$outdir"

css=
cleanup() {
  if [ -n "$css" ]; then command rm -f -- "$css"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

set -- --width "$size" --height "$size" --keep-aspect-ratio
if [ -n "$bg" ]; then
  set -- "$@" --background-color "$bg"
fi
if [ -n "$ink" ]; then
  css=$(command mktemp "${TMPDIR:-/tmp}/render-fast.XXXXXX")
  printf 'svg { color: %s; }\n' "$ink" >"$css"
  set -- "$@" --stylesheet "$css"
fi

command rsvg-convert "$@" --output "$out" -- "$in"
