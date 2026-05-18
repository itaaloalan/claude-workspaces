"""Builder de prompts para o Claude gerar RunnerConfigs."""

from __future__ import annotations

from pathlib import Path

from ..models import Workspace


def pending_runner_path(workspace: Workspace) -> Path:
    """Caminho onde o Claude deve salvar o JSON gerado.

    O botão 'Recarregar runners' da aba Runners lê desse arquivo e
    importa via runners_io.import_runners.
    """
    return (
        Path.home()
        / ".config"
        / "claude-workspaces"
        / "runner-drafts"
        / f"{workspace.id}.json"
    )


def build_generate_prompt(workspace: Workspace, hint: str = "") -> str:
    folders = "\n".join(f"  - {f}" for f in workspace.folders) or "  (sem pastas)"
    hint_block = f"\nHint do usuário: {hint}\n" if hint.strip() else ""
    out_path = pending_runner_path(workspace)
    return (
        f"Leia `docs/runners-spec.md` deste repositório (claude-workspaces) e "
        f"gere a configuração de um Runner para o workspace abaixo.\n\n"
        f"Workspace: {workspace.name}\n"
        f"Pastas:\n{folders}\n"
        f"{hint_block}\n"
        "ANTES de gerar os comandos, INSPECIONE arquivos de referência em "
        "cada pasta do workspace para descobrir os comandos reais — não "
        "chute. Exemplos do que ler:\n"
        "  - `package.json` (scripts npm/pnpm/yarn, ex: `dev`, `start`)\n"
        "  - `pom.xml` (goals Maven, plugins como spring-boot, tomcat7, "
        "jetty; versão Java em <maven.compiler.source> ou <java.version>)\n"
        "  - `build.gradle` / `build.gradle.kts` (tasks Gradle)\n"
        "  - `pyproject.toml` / `requirements.txt` (entrypoint, framework)\n"
        "  - `Cargo.toml`, `go.mod`, `Gemfile`, `composer.json`, `Makefile`, "
        "`docker-compose.yml`, `.nvmrc`, `.tool-versions`, `README.md`\n"
        "Use o Read/Glob para abrir esses arquivos antes de decidir o "
        "start_cmd. Se a hint do usuário citar versões de runtime (ex: "
        "\"java 8 e java 25\"), confirme no pom.xml/build.gradle qual pasta "
        "usa qual versão e ajuste JAVA_HOME/PATH no comando.\n\n"
        "Gere o JSON do RunnerConfig com os campos: name, start_cmd, "
        "stop_cmd, restart_cmd, cwd (opcional), enabled. Comandos devem ser "
        "foreground quando possível e responder a SIGHUP/SIGTERM. Para "
        "servidores que rodam em background (ex: glassfish), use stop_cmd "
        "e restart_cmd explícitos.\n\n"
        f"IMPORTANTE — salve o resultado no arquivo:\n  {out_path}\n\n"
        "no formato esperado pelo import (envelope com a chave `runners`, "
        "uma lista):\n"
        '  {"runners": [ { ...config... } ]}\n\n'
        "Crie diretórios pai se necessário (mkdir -p). Depois de salvar, "
        "avise ao usuário que ele pode clicar em **Recarregar runners** "
        "na aba Runners do claude-workspaces para importar."
    )
