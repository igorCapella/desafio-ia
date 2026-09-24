#!/usr/bin/env bash
# Reaplica a configuração LOCAL do git deste projeto (spec §10.1). Nunca altera a configuração global.
set -euo pipefail
cd "$(dirname "$0")/.."
git config --local user.name "Igor Capella de Azevedo"
git config --local user.email "igor.capella.a@gmail.com"
git config --local core.hooksPath scripts/git-hooks
git config --local credential.helper ""  # a global usa "store"; aqui não se guarda credencial
chave="$HOME/.ssh/id_ed25519_desafio_ia"
if [ -f "$chave" ]; then
  git config --local core.sshCommand "ssh -i $chave -o IdentitiesOnly=yes"
fi
chmod +x scripts/git-hooks/pre-push
echo "Configuração local do git aplicada (hook anti-GitLab ativo)."
