import os
import shutil
import subprocess
from pathlib import Path

HOOK = Path("scripts/git-hooks/pre-push")


def _hook(url):
    return subprocess.run(["bash", str(HOOK), "origin", url], input="", capture_output=True,
                          text=True)


def test_hook_bloqueia_gitlab():
    for url in ("git@gitlab.exemplo.com.br:x/y.git", "https://GitLab.com/x/y.git",
                "ssh://git@gitlab.exemplo.com.br:2222/x/y.git"):
        r = _hook(url)
        assert r.returncode == 1 and "GitLab" in r.stderr, url


def test_hook_permite_github():
    assert _hook("git@github.com:x/y.git").returncode == 0


def test_configurar_git_so_mexe_no_repositorio_local(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts/git-hooks").mkdir(parents=True)
    shutil.copy("scripts/configurar-git.sh", repo / "scripts")
    shutil.copy(HOOK, repo / "scripts/git-hooks")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    ambiente = {**os.environ, "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["bash", "scripts/configurar-git.sh"], cwd=repo, env=ambiente, check=True,
                   capture_output=True)

    def local(chave):
        return subprocess.run(["git", "config", "--local", chave], cwd=repo, env=ambiente,
                              capture_output=True, text=True).stdout.strip()

    assert local("core.hooksPath") == "scripts/git-hooks"
    assert local("user.email") == "igor.capella.a@gmail.com"
    assert not (tmp_path / ".gitconfig").exists()  # nada foi para a configuração global
