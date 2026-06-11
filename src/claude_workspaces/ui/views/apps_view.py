"""Apps auxiliares — PWAs/sites embutidos via QtWebEngine.

Lista lateral de apps configurados (Taskis, ClickUp etc) + webview à
direita. Cada app ganha um perfil isolado em ~/.config/claude-workspaces/
apps_profiles/<slug>/ — assim cookies/login persistem entre sessões e um
app não enxerga os cookies do outro.

Settings.apps é uma lista de dicts {name, url, icon?, slug?} que pode
ser editada via diálogo "Adicionar app" ou direto no settings.json.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...settings import Settings, config_dir

log = logging.getLogger(__name__)


DEFAULT_APPS: list[dict] = [
    {
        "name": "Taskis",
        "url": "https://taskis.sipesistemas.com/",
        "icon": "⏱",
        "slug": "taskis",
    },
    {
        "name": "ClickUp",
        "url": "https://app.clickup.com/",
        "icon": "✅",
        "slug": "clickup",
    },
]


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "app"


def _profiles_dir() -> Path:
    p = config_dir() / "apps_profiles"
    p.mkdir(parents=True, exist_ok=True)
    return p


class _AppEditDialog(QDialog):
    """Diálogo simples pra criar/editar entrada de app."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        name: str = "",
        url: str = "",
        icon: str = "🌐",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("App auxiliar")
        self.setMinimumWidth(420)

        form = QFormLayout(self)
        self._name = QLineEdit(name)
        self._name.setPlaceholderText("Ex: Taskis")
        self._url = QLineEdit(url)
        self._url.setPlaceholderText("https://...")
        self._icon = QLineEdit(icon)
        self._icon.setPlaceholderText("Emoji ou letra (ex: ⏱)")
        self._icon.setMaxLength(4)
        form.addRow("Nome", self._name)
        form.addRow("URL", self._url)
        form.addRow("Ícone", self._icon)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def data(self) -> dict:
        name = self._name.text().strip()
        url = self._url.text().strip()
        icon = self._icon.text().strip() or "🌐"
        return {
            "name": name,
            "url": url,
            "icon": icon,
            "slug": _slugify(name),
        }


class _SameViewPage(QWebEnginePage):
    """QWebEnginePage que redireciona `window.open()` (e clicks com
    target=_blank / "Abrir em nova guia") pra mesma view, em vez de
    deixar o Qt criar uma janela top-level vazia. Sem isso, web apps
    como ClickUp/Taskis disparam popups de OAuth/preview que aparecem
    como retângulos brancos extras na barra de tarefas e voltam a abrir
    sozinhos quando fechados (o JS da página re-chama window.open).
    """

    def createWindow(self, _type):  # type: ignore[override]
        # Página descartável que existe só pra capturar a primeira URL
        # solicitada e jogar na página principal — depois se autodestrói.
        temp = QWebEnginePage(self.profile(), self)

        def _redirect(url):
            self.setUrl(url)
            temp.deleteLater()

        temp.urlChanged.connect(_redirect)
        return temp


class _AppPage(QWidget):
    """Wrapper com toolbar (back/forward/reload/url) + webview."""

    def __init__(self, app_cfg: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = app_cfg

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar de navegação
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 6, 8, 6)
        toolbar.setSpacing(4)

        self._back_btn = QPushButton("←")
        self._back_btn.setFixedWidth(32)
        self._back_btn.setToolTip("Voltar")
        self._fwd_btn = QPushButton("→")
        self._fwd_btn.setFixedWidth(32)
        self._fwd_btn.setToolTip("Avançar")
        self._reload_btn = QPushButton("↻")
        self._reload_btn.setFixedWidth(32)
        self._reload_btn.setToolTip("Recarregar")
        self._home_btn = QPushButton("🏠")
        self._home_btn.setFixedWidth(32)
        self._home_btn.setToolTip("Página inicial do app")
        for b in (self._back_btn, self._fwd_btn, self._reload_btn, self._home_btn):
            toolbar.addWidget(b)

        self._url_label = QLabel("")
        self._url_label.setStyleSheet("color: #888; font-size: 11px;")
        self._url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        toolbar.addWidget(self._url_label, stretch=1)

        layout.addLayout(toolbar)

        # Perfil isolado por app (cookies/storage persistentes)
        slug = app_cfg.get("slug") or _slugify(app_cfg.get("name", "app"))
        profile_path = _profiles_dir() / slug
        profile_path.mkdir(parents=True, exist_ok=True)
        self._state_file = profile_path / "state.json"
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._persist_state)
        self._profile = QWebEngineProfile(f"app-{slug}", self)
        self._profile.setPersistentStoragePath(str(profile_path))
        self._profile.setCachePath(str(profile_path / "cache"))
        self._profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )

        self._view = QWebEngineView(self)
        page = _SameViewPage(self._profile, self._view)
        self._view.setPage(page)

        layout.addWidget(self._view, stretch=1)

        self._back_btn.clicked.connect(self._view.back)
        self._fwd_btn.clicked.connect(self._view.forward)
        self._reload_btn.clicked.connect(self._view.reload)
        self._home_btn.clicked.connect(self._go_home)
        self._view.urlChanged.connect(self._on_url_changed)

        # Restaura última URL navegada (se houver) — senão cai na home
        last = self._load_last_url()
        if last:
            self._view.setUrl(QUrl(last))
        else:
            self._go_home()

    def _go_home(self) -> None:
        url = self._cfg.get("url") or ""
        if url:
            self._view.setUrl(QUrl(url))

    def _on_url_changed(self, qurl: QUrl) -> None:
        self._url_label.setText(qurl.toString())
        self._back_btn.setEnabled(self._view.history().canGoBack())
        self._fwd_btn.setEnabled(self._view.history().canGoForward())
        # about:blank aparece como estado intermediário de redirect — ignora
        if qurl.scheme() in ("http", "https"):
            self._save_timer.start()

    def _load_last_url(self) -> str:
        try:
            if self._state_file.is_file():
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                u = data.get("last_url")
                if isinstance(u, str) and u.startswith(("http://", "https://")):
                    return u
        except Exception:
            log.exception("Falha lendo state.json do app %s", self._cfg.get("slug"))
        return ""

    def _persist_state(self) -> None:
        url = self._view.url().toString()
        if not url.startswith(("http://", "https://")):
            return
        try:
            self._state_file.write_text(
                json.dumps({"last_url": url}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Falha salvando state.json do app %s", self._cfg.get("slug"))

    def set_lifecycle(self, state: QWebEnginePage.LifecycleState) -> None:
        """Move o renderer Chromium da webview pra um estado de ciclo de vida.

        `Discarded` libera o processo renderer inteiro (o app web some da RAM)
        e o Qt recarrega sozinho da URL atual quando a página volta a `Active`
        — como o tab-discarding do Chrome. Cookies/login persistem no profile
        em disco, então é transparente. SPAs pesados embutidos (ClickUp,
        Taskis) seguravam GBs vivos mesmo fora de vista; descartar quando o
        usuário não está olhando a aba Apps devolve essa memória.

        `Discarded`/`Frozen` só são aceitos pelo Qt quando a página NÃO está
        visível — o chamador garante isso (só descarta páginas não-ativas /
        no hideEvent). `Active` é sempre permitido."""
        try:
            page = self._view.page()
            if page is not None and page.lifecycleState() != state:
                page.setLifecycleState(state)
        except Exception:
            log.debug("setLifecycleState falhou", exc_info=True)


class AppsView(QWidget):
    """View top-level pra apps auxiliares (PWAs embutidos)."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._pages: dict[str, _AppPage] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar topo
        topbar = QHBoxLayout()
        topbar.setContentsMargins(16, 8, 16, 4)
        title = QLabel("<h2 style='margin:0;'>🧰 Apps</h2>")
        topbar.addWidget(title)
        topbar.addStretch()
        hint = QLabel(
            "<span style='color:#888;'>PWAs auxiliares com sessão persistente "
            "(cookies isolados por app)</span>"
        )
        topbar.addWidget(hint)
        root.addLayout(topbar)

        # Split: lista de apps à esquerda + stack de webviews à direita
        body = QHBoxLayout()
        body.setContentsMargins(8, 0, 8, 8)
        body.setSpacing(6)

        left = QVBoxLayout()
        left.setSpacing(4)
        self._list = QListWidget()
        self._list.setFixedWidth(180)
        self._list.setStyleSheet(
            "QListWidget { background: #181818; border: 1px solid #2c2c2c; "
            "border-radius: 6px; color: #d4d4d4; padding: 4px; }"
            "QListWidget::item { padding: 8px 6px; border-radius: 4px; }"
            "QListWidget::item:selected { background: #3d6ea8; color: #fff; }"
            "QListWidget::item:hover { background: #232323; }"
        )
        self._list.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self._list, stretch=1)

        # Ações
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._add_btn = QPushButton("+ App")
        self._add_btn.setToolTip("Adicionar novo app")
        self._add_btn.clicked.connect(self._add_app)
        self._edit_btn = QPushButton("✎")
        self._edit_btn.setFixedWidth(32)
        self._edit_btn.setToolTip("Editar selecionado")
        self._edit_btn.clicked.connect(self._edit_app)
        self._del_btn = QPushButton("🗑")
        self._del_btn.setFixedWidth(32)
        self._del_btn.setToolTip("Remover selecionado")
        self._del_btn.clicked.connect(self._remove_app)
        btn_row.addWidget(self._add_btn, stretch=1)
        btn_row.addWidget(self._edit_btn)
        btn_row.addWidget(self._del_btn)
        left.addLayout(btn_row)

        body.addLayout(left)

        # Stack de páginas
        self._stack = QStackedWidget()
        self._empty = QLabel(
            "<div style='color:#888; padding:32px; text-align:center;'>"
            "Nenhum app configurado.<br>Clique em <b>+ App</b> pra adicionar."
            "</div>"
        )
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(self._empty)
        body.addWidget(self._stack, stretch=1)

        root.addLayout(body, stretch=1)

        # Atalhos: Ctrl+R recarrega app atual
        QShortcut(QKeySequence("Ctrl+R"), self, self._reload_current)

        self.refresh()

    # ---------- Settings ----------

    def _apps(self) -> list[dict]:
        cfg = list(self._settings.apps or [])
        if not cfg:
            cfg = [dict(a) for a in DEFAULT_APPS]
            self._settings.apps = cfg
            try:
                self._settings.save()
            except Exception:
                log.exception("Falha salvando apps default")
        return cfg

    def _save_apps(self, apps: list[dict]) -> None:
        self._settings.apps = apps
        try:
            self._settings.save()
        except Exception:
            log.exception("Falha salvando apps")

    # ---------- Render ----------

    def refresh(self) -> None:
        prev_slug = None
        current = self._list.currentItem()
        if current is not None:
            prev_slug = current.data(Qt.ItemDataRole.UserRole)

        self._list.clear()
        apps = self._apps()
        for app in apps:
            icon = app.get("icon") or "🌐"
            name = app.get("name") or "(sem nome)"
            item = QListWidgetItem(f"{icon}  {name}")
            item.setData(Qt.ItemDataRole.UserRole, app.get("slug") or _slugify(name))
            item.setToolTip(app.get("url") or "")
            self._list.addItem(item)

        # Restaura seleção anterior se ainda existir
        if prev_slug:
            for i in range(self._list.count()):
                if self._list.item(i).data(Qt.ItemDataRole.UserRole) == prev_slug:
                    self._list.setCurrentRow(i)
                    return
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        else:
            self._stack.setCurrentWidget(self._empty)

    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            self._stack.setCurrentWidget(self._empty)
            return
        item = self._list.item(row)
        if not item:
            return
        slug = item.data(Qt.ItemDataRole.UserRole)
        apps = self._apps()
        cfg = next((a for a in apps if (a.get("slug") or _slugify(a.get("name", ""))) == slug), None)
        if not cfg:
            return
        page = self._pages.get(slug)
        if page is None:
            page = _AppPage(cfg, self)
            self._pages[slug] = page
            self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)
        self._apply_lifecycle(active=page)

    def _apply_lifecycle(self, active: _AppPage | None) -> None:
        """Mantém só a página `active` com renderer vivo; descarta as demais.

        Chamado ao trocar de app e no showEvent. Sem isso, todo app já
        visitado seguia rodando um Chromium completo pra sempre — a causa
        de RAM cheia / travadas com ClickUp e Taskis embutidos."""
        active_state = QWebEnginePage.LifecycleState.Active
        discarded = QWebEnginePage.LifecycleState.Discarded
        for p in self._pages.values():
            p.set_lifecycle(active_state if p is active else discarded)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Usuário saiu da aba Apps (foi pros terminais / outra view): descarta
        TODOS os renderers dos apps pra devolver a RAM. Voltam sozinhos da URL
        persistida quando a aba Apps reaparece (showEvent).

        O discard é adiado um tick do event loop: a troca de visibilidade do
        QtWebEngine é assíncrona e `Discarded` só é aceito quando a página já
        não está visível — descartar no mesmo instante do hide deixaria o app
        ativo preso em Active."""
        super().hideEvent(event)
        QTimer.singleShot(0, self._discard_all_if_hidden)

    def _discard_all_if_hidden(self) -> None:
        if self.isVisible():
            return  # voltou a aparecer antes do tick — mantém vivo
        discarded = QWebEnginePage.LifecycleState.Discarded
        for p in self._pages.values():
            p.set_lifecycle(discarded)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Aba Apps voltou a aparecer: reativa só o app atualmente selecionado
        (recarrega se tinha sido descartado); os outros seguem descartados."""
        super().showEvent(event)
        cur = self._stack.currentWidget()
        self._apply_lifecycle(active=cur if isinstance(cur, _AppPage) else None)

    def _reload_current(self) -> None:
        widget = self._stack.currentWidget()
        if isinstance(widget, _AppPage):
            widget._view.reload()

    # ---------- CRUD ----------

    def _add_app(self) -> None:
        dlg = _AppEditDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.data()
        if not data["name"] or not data["url"]:
            QMessageBox.warning(self, "App inválido", "Nome e URL são obrigatórios.")
            return
        apps = self._apps()
        # Slug único
        base_slug = data["slug"]
        existing = {a.get("slug") for a in apps}
        slug = base_slug
        n = 2
        while slug in existing:
            slug = f"{base_slug}-{n}"
            n += 1
        data["slug"] = slug
        apps.append(data)
        self._save_apps(apps)
        self.refresh()
        # Seleciona o recém-criado
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == slug:
                self._list.setCurrentRow(i)
                break

    def _edit_app(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        slug = item.data(Qt.ItemDataRole.UserRole)
        apps = self._apps()
        cfg = next((a for a in apps if a.get("slug") == slug), None)
        if not cfg:
            return
        dlg = _AppEditDialog(
            self,
            name=cfg.get("name", ""),
            url=cfg.get("url", ""),
            icon=cfg.get("icon", "🌐"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new = dlg.data()
        if not new["name"] or not new["url"]:
            QMessageBox.warning(self, "App inválido", "Nome e URL são obrigatórios.")
            return
        # Mantém slug original pra preservar perfil/cookies
        new["slug"] = slug
        cfg.update(new)
        self._save_apps(apps)
        # Limpa página em cache pra recarregar com nova URL
        if slug in self._pages:
            old_page = self._pages.pop(slug)
            self._stack.removeWidget(old_page)
            old_page.deleteLater()
        self.refresh()

    def _remove_app(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        slug = item.data(Qt.ItemDataRole.UserRole)
        apps = self._apps()
        cfg = next((a for a in apps if a.get("slug") == slug), None)
        if not cfg:
            return
        resp = QMessageBox.question(
            self,
            "Remover app",
            f"Remover \"{cfg.get('name')}\" da lista?\n\n"
            "Cookies/sessão ficam no disco — pra apagar tudo, "
            f"remova {_profiles_dir() / slug} manualmente.",
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        apps = [a for a in apps if a.get("slug") != slug]
        self._save_apps(apps)
        if slug in self._pages:
            page = self._pages.pop(slug)
            self._stack.removeWidget(page)
            page.deleteLater()
        self.refresh()
