"""Dialogs for selecting a remote launch profile."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from ayon_core.style import load_stylesheet
from ayon_core.tools.publisher.widgets import get_pixmap

from ayon_comfyui.parse_settings import ComfyRemoteSettings

if TYPE_CHECKING:
    # TEMP: I'm using pyside6-stubs so I don't lose my mind.
    # This is fine to leave in during development.
    # TYPE_CHECKING evaluates to False in runtime.
    from PySide6.QtCore import QPoint, QSize, Qt
    from PySide6.QtWidgets import (
        QDialog,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMenu,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
else:
    from qtpy.QtCore import QPoint, QSize, Qt
    from qtpy.QtWidgets import (
        QDialog,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMenu,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )


class RemoteProfileDialog(QDialog):
    """Window that shows a list of profiles."""

    def __init__(self, parent: QWidget | None = None):
        """Initialize dialog."""
        super().__init__(parent)
        self.setStyleSheet(load_stylesheet())
        self.setWindowTitle("ComfyUI profile")
        self.setMinimumWidth(420)

        # Chosen profile
        self._profile = None
        # keep ref to settings
        self._settings = None

        layout = QVBoxLayout()

        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(QLabel("Select launch profile..."))

        self._lstProfiles = QListWidget()
        self._lstProfiles.setIconSize(QSize(16, 16))
        self._lstProfiles.setSpacing(2)
        self._lstProfiles.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._lstProfiles.customContextMenuRequested.connect(
            self._on_profiles_context_menu
        )

        # dummy args for function signature related failure prevention
        def _button_confirm(*args: list[Any]) -> None:  # noqa: ARG001
            """Button confirm action."""
            profile = self._lstProfiles.currentItem().data(
                Qt.ItemDataRole.UserRole
            )
            if profile:
                self.confirm_commit_profile(profile)

        self._btnConfirm = QPushButton("Select profile!")
        self._btnConfirm.setDefault(True)
        self._btnConfirm.clicked.connect(partial(_button_confirm))
        self._lstProfiles.itemActivated.connect(_button_confirm)
        layout.addWidget(self._lstProfiles)

        layout.addWidget(self._btnConfirm)

        self.setLayout(layout)

    def populate_list(self, settings: ComfyRemoteSettings) -> None:
        """Adds profiles to list from settings, with appropriate icons."""
        self._lstProfiles.clear()
        self._settings = settings
        for profile_name in settings.profiles:
            self._add_profile_to_list(settings.get(profile_name))

    def _add_profile_to_list(
        self, item: ComfyRemoteSettings.ComfyRemoteProfile
    ) -> None:
        """Perform sanity check on profile and add it to QListWidget."""
        text = item.name
        icon = None
        # if not item.is_valid:
        #     icon = get_pixmap(icon_name="warning")
        #     list_item = QListWidgetItem(text)
        #     list_item.setIcon(icon)
        # else:
        #     icon = get_pixmap(icon_name="create")
        #     list_item = QListWidgetItem(text)
        #     list_item.setIcon(icon)

        icon = get_pixmap(icon_name="create")
        list_item = QListWidgetItem(text)
        list_item.setIcon(icon)

        list_item.setData(Qt.ItemDataRole.UserRole, item)
        self._lstProfiles.addItem(list_item)

    def _on_profiles_context_menu(self, pos: QPoint) -> None:
        """Handle context menu for profiles."""
        item = self._lstProfiles.itemAt(pos)
        if not item:
            return

        profile: ComfyRemoteSettings.ComfyRemoteProfile = item.data(
            Qt.ItemDataRole.UserRole
        )

        menu = QMenu(self)
        launch_action = menu.addAction(f"Launch ComfyUI with: {profile.name}")
        launch_action.triggered.connect(
            partial(self.confirm_commit_profile, profile)
        )

        # Disable diagnosis for now.
        # TODO(@sas): implement validation & diagnosis
        # menu.addSeparator()

        # logs_action = menu.addAction("View logs...")
        # logs_action.triggered.connect(partial(self.show_log, profile))

        # debug_action = menu.addAction("Debug for all platforms...")
        # debug_action.triggered.connect(partial(self.show_debug, profile))

        menu.exec(self._lstProfiles.mapToGlobal(pos))

    # def show_log(self, profile: ComfyRemoteSettings.ComfyRemoteProfile) -> None:
    #     """Show subwindow with host os debug info about the profile in it."""
    #     win = RemoteProfileDebugDialog(self)
    #     win.log_profile_current_os(profile)
    #     win.exec()

    # def show_debug(
    #     self, profile: ComfyRemoteSettings.ComfyRemoteProfile
    # ) -> None:
    #     """Show subwindow with all os debug info about the profile in it."""
    #     win = RemoteProfileDebugDialog(self)
    #     win.log_profile_all_os(profile)
    #     win.exec()

    def confirm_profile(
        self,
        profile: ComfyRemoteSettings.ComfyRemoteProfile,
    ) -> None:
        """Confirms profile choice, and closes the window."""
        self._profile = profile
        self.close()

    def confirm_commit_profile(
        self,
        profile: ComfyRemoteSettings.ComfyRemoteProfile,
    ) -> None:
        """Confirms profile choice, and closes the window.

        Additionally commits the state for later recall.
        """
        self._profile = profile
        self._settings.commit(self._profile)
        self.close()

    @property
    def profile(self) -> ComfyRemoteSettings.ComfyRemoteProfile:
        """Returns chosen profile."""
        return self._profile
