# source this: sets the server, key and CA bundle for the kit
_here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
set -a; . "$_here/.env"; set +a
export SPREAD_URL=https://spread.bahnexpress.com
_py="$(cd "$_here/../.venv/bin" && pwd -P)/python"
export SPREAD_PYTHON="$_py"
# NixOS: pip wheels (numpy, sklearn) need a 64-bit libstdc++ on the library path
if [ -d /nix/store ] && ! "$_py" -c 'import numpy' 2>/dev/null; then
  for _lib in '*gcc*-lib/lib/libstdc++.so.6' '*zlib*/lib/libz.so.1'; do
    for _f in /nix/store/$_lib; do
      if file -L "$_f" | grep -q 64-bit; then export LD_LIBRARY_PATH="$(dirname "$_f")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"; break; fi
    done
  done
fi
export SSL_CERT_FILE="$("$_py" -c 'import certifi;print(certifi.where())')"
unset _here _py _f _lib
