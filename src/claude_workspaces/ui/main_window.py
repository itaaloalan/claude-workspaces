from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..launchers import LauncherError, find_app_repo_root, launch_claude_in_dir
from ..models import Workspace
from ..settings import Settings
from ..storage import load_workspaces, save_workspaces
from .settings_panel import SettingsPanel
from .workspace_details import WorkspaceDetailsPanel
from .workspace_dialog import WorkspaceDialog


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Claude Workspaces")
        self.resize(1180, 740)

        self.settings = Settings.load()
        self.workspaces: list[Workspace] = load_workspaces()

        tabs = QTabWidget()
        tabs.addTab(self._build_workspaces_tab(), "Workspaces")

        self.settings_panel = SettingsPanel(self.settings)
        tabs.addTab(self.settings_panel, "Configurações")

        self.setCentralWidget(tabs)
        self.refresh_list()

    def _build_workspaces_tab(self) -> QWidget:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(6, 4, 6, 4)
        self.toggle_sidebar_btn = QPushButton("☰")
        self.toggle_sidebar_btn.setFixedWidth(32)
        self.toggle_sidebar_btn.setToolTip("Esconder / mostrar a barra lateral")
        self.toggle_sidebar_btn.clicked.connect(self._toggle_sidebar)
        toolbar.addWidget(self.toggle_sidebar_btn)
        toolbar.addStretch()
        outer.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setHandleWidth(6)
        self._sidebar = self._build_sidebar()
        self.splitter.addWidget(self._sidebar)

        self.details = WorkspaceDetailsPanel(self.settings)
        self.details.edit_requested.connect(self.edit_workspace)
        self.details.delete_requested.connect(self.delete_workspace)
        self.splitter.addWidget(self.details)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([280, 900])
        outer.addWidget(self.splitter, stretch=1)
        return container

    def _toggle_sidebar(self) -> None:
        sizes = self.splitter.sizes()
        if sizes[0] == 0:
            self.splitter.setSizes([280, max(sizes[1] - 280, 600)])
        else:
            self.splitter.setSizes([0, sum(sizes)])

    def _build_sidebar(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        layout.addWidget(QLabel("<b>Workspaces</b>"))

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget, stretch=1)

        actions = QHBoxLayout()
        add_btn = QPushButton("+ Novo")
        add_btn.clicked.connect(self.add_workspace)
        actions.addWidget(add_btn)
        actions.addStretch()
        layout.addLayout(actions)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #3a3a3a;")
        layout.addWidget(sep)

        self.self_dev_btn = QPushButton("🔧 Hack este app")
        self.self_dev_btn.setToolTip(
            "Abre o Claude no diretório do próprio claude-workspaces pra iterar nele"
        )
        self.self_dev_btn.clicked.connect(self._launch_self_dev)
        layout.addWidget(self.self_dev_btn)

        return wrapper

    def refresh_list(self) -> None:
        current_name = None
        current_item = self.list_widget.currentItem()
        if current_item:
            current_name = current_item.data(Qt.ItemDataRole.UserRole).name

        self.list_widget.clear()
        for ws in self.workspaces:
            item = QListWidgetItem(ws.name)
            item.setData(Qt.ItemDataRole.UserRole, ws)
            if ws.description:
                item.setToolTip(ws.description)
            self.list_widget.addItem(item)

        if current_name:
            for i in range(self.list_widget.count()):
                if self.list_widget.item(i).data(Qt.ItemDataRole.UserRole).name == current_name:
                    self.list_widget.setCurrentRow(i)
                    return

        if self.workspaces:
            self.list_widget.setCurrentRow(0)
        else:
            self.details.show_empty()

    def _on_selection_changed(self, current, _previous) -> None:
        if current is None:
            self.details.show_empty()
            return
        ws = current.data(Qt.ItemDataRole.UserRole)
        self.details.show_workspace(ws)

    def _launch_self_dev(self) -> None:
        repo = find_app_repo_root()
        if not repo:
            QMessageBox.warning(
                self,
                "Não foi possível localizar o repo",
                "Esse botão só funciona quando o app está rodando direto do código-fonte "
                "(com pyproject.toml acessível).",
            )
            return
        try:
            launch_claude_in_dir(repo, self.settings)
        except LauncherError as e:
            QMessageBox.warning(self, "Falha ao abrir Claude", str(e))

    def add_workspace(self) -> None:
        dialog = WorkspaceDialog(parent=self)
        if dialog.exec():
            ws = dialog.workspace()
            if not ws.name:
                QMessageBox.warning(self, "Workspace inválido", "O nome não pode ficar vazio.")
                return
            self.workspaces.append(ws)
            save_workspaces(self.workspaces)
            self.refresh_list()

    def edit_workspace(self, workspace: Workspace) -> None:
        dialog = WorkspaceDialog(workspace=workspace, parent=self)
        if dialog.exec():
            updated = dialog.workspace()
            idx = self.workspaces.index(workspace)
            self.workspaces[idx] = updated
            save_workspaces(self.workspaces)
            self.refresh_list()

    def delete_workspace(self, workspace: Workspace) -> None:
        reply = QMessageBox.question(
            self,
            "Remover workspace",
            f"Remover o workspace '{workspace.name}'?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.workspaces.remove(workspace)
            save_workspaces(self.workspaces)
            self.refresh_list()
