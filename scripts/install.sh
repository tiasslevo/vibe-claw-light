#!/usr/bin/env bash
set -euo pipefail

# Do not overwrite VIBE_CLAW_ROOT: it may belong to a calling agent instance.
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
provider="${1:-}"
skip_setup="${2:-}"
download_directory=""

cleanup() {
  if [[ -n "$download_directory" && -d "$download_directory" ]]; then
    rm -rf -- "$download_directory"
  fi
}
trap cleanup EXIT
trap 'printf "Installation interrompue. Corrige cette etape puis relance le script. Les donnees existantes sont conservees.\n" >&2' ERR

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) printf 'Utilise install.cmd sur Windows natif.\n' >&2; exit 1 ;;
esac
if [[ ! -f "$project_root/run.py" ]]; then
  printf 'Le projet est incomplet. Extrais toute l archive avant de lancer le script.\n' >&2
  exit 1
fi
if [[ -z "$provider" ]]; then
  read -r -p 'Moteur auquel tu as acces (codex/claude) : ' provider
fi
case "$provider" in
  codex|claude) ;;
  *) printf 'Choisis codex ou claude : bash scripts/install.sh codex\n' >&2; exit 1 ;;
esac
if [[ -n "$skip_setup" && "$skip_setup" != '--skip-setup' ]]; then
  printf 'Option inconnue : %s\n' "$skip_setup" >&2
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  printf 'curl est necessaire. Installe-le avec le gestionnaire de paquets de ton systeme.\n' >&2
  exit 1
fi

export PATH="${UV_INSTALL_DIR:-$HOME/.local/bin}:${CODEX_INSTALL_DIR:-$HOME/.local/bin}:$PATH"
download_directory="$(mktemp -d "${TMPDIR:-/tmp}/vibe-claw-light.XXXXXXXX")"

if ! command -v uv >/dev/null 2>&1; then
  printf 'Installation de uv depuis astral.sh...\n'
  curl --fail --silent --show-error --location 'https://astral.sh/uv/install.sh' --output "$download_directory/uv-install.sh"
  UV_NO_MODIFY_PATH=1 sh "$download_directory/uv-install.sh"
fi
uv --version

if ! command -v "$provider" >/dev/null 2>&1; then
  printf 'Installation du moteur choisi : %s\n' "$provider"
  if [[ "$provider" == 'codex' ]]; then
    curl --fail --silent --show-error --location 'https://chatgpt.com/codex/install.sh' --output "$download_directory/codex-install.sh"
    CODEX_NON_INTERACTIVE=1 sh "$download_directory/codex-install.sh"
  else
    curl --fail --silent --show-error --location 'https://claude.ai/install.sh' --output "$download_directory/claude-install.sh"
    bash "$download_directory/claude-install.sh"
  fi
fi
if ! command -v "$provider" >/dev/null 2>&1; then
  printf '%s reste introuvable. Consulte docs/INSTALLATION.md.\n' "$provider" >&2
  exit 1
fi
"$provider" --version

cd -- "$project_root"
printf 'Preparation de Python 3.11 et de l environnement local...\n'
uv sync --python 3.11
python_executable="$project_root/.venv/bin/python"
if [[ ! -x "$python_executable" ]]; then
  printf 'Python local introuvable apres uv sync.\n' >&2
  exit 1
fi
if [[ "$skip_setup" == '--skip-setup' ]]; then
  printf 'Dependances installees. Lance ensuite : .venv/bin/python run.py setup --provider %s\n' "$provider"
  exit 0
fi
"$python_executable" run.py setup --provider "$provider"
printf 'Assistant pret. Ecris a ton bot dans Telegram.\n'
printf 'Pour les prochains demarrages : bash start.sh. Pour arreter : bash start.sh stop.\n'
