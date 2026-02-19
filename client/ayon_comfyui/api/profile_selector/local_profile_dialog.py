"""Dialogs for selecting a local launch profile."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from ayon_core.style import load_stylesheet
from ayon_core.tools.publisher.widgets import get_pixmap

from ayon_comfyui.parse_settings import ComfyLocalSettings

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


class LocalProfileDialog(QDialog):
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

    def populate_list(self, settings: ComfyLocalSettings) -> None:
        """Adds profiles to list from settings, with appropriate icons."""
        self._lstProfiles.clear()
        self._settings = settings
        for profile_name in settings.profiles:
            self._add_profile_to_list(settings.get(profile_name))

    def _add_profile_to_list(
        self, item: ComfyLocalSettings.ComfyLocalProfile
    ) -> None:
        """Perform sanity check on profile and add it to QListWidget."""
        text = item.name
        icon = None
        if not item.is_valid:
            icon = get_pixmap(icon_name="warning")
            list_item = QListWidgetItem(text)
            list_item.setIcon(icon)
        else:
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

        profile: ComfyLocalSettings.ComfyLocalProfile = item.data(
            Qt.ItemDataRole.UserRole
        )

        menu = QMenu(self)
        launch_action = menu.addAction(f"Launch ComfyUI with: {profile.name}")
        launch_action.triggered.connect(
            partial(self.confirm_commit_profile, profile)
        )

        menu.addSeparator()

        logs_action = menu.addAction("View logs...")
        logs_action.triggered.connect(partial(self.show_log, profile))

        debug_action = menu.addAction("Debug for all platforms...")
        debug_action.triggered.connect(partial(self.show_debug, profile))

        menu.exec(self._lstProfiles.mapToGlobal(pos))

    def show_log(self, profile: ComfyLocalSettings.ComfyLocalProfile) -> None:
        """Show subwindow with host os debug info about the profile in it."""
        win = LocalProfileDebugDialog(self)
        win.log_profile_current_os(profile)
        win.exec()

    def show_debug(
        self, profile: ComfyLocalSettings.ComfyLocalProfile
    ) -> None:
        """Show subwindow with all os debug info about the profile in it."""
        win = LocalProfileDebugDialog(self)
        win.log_profile_all_os(profile)
        win.exec()

    def confirm_profile(
        self,
        profile: ComfyLocalSettings.ComfyLocalProfile,
    ) -> None:
        """Confirms profile choice, and closes the window."""
        self._profile = profile
        self.close()

    def confirm_commit_profile(
        self,
        profile: ComfyLocalSettings.ComfyLocalProfile,
    ) -> None:
        """Confirms profile choice, and closes the window.

        Additionally commits the state for later recall.
        """
        self._profile = profile
        self._settings.commit(self._profile)
        self.close()

    @property
    def profile(self) -> ComfyLocalSettings.ComfyLocalProfile:
        """Returns chosen profile."""
        return self._profile


class LocalProfileDebugDialog(QDialog):
    """Dialog for validation of settings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Sets up dialog.

        Doesn't add any messages.
        """
        super().__init__(parent=parent)
        self.setStyleSheet(load_stylesheet())
        self.setWindowTitle("Profile debug info")
        self.setMinimumWidth(420)

        layout = QVBoxLayout()

        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(QLabel("Log:"))

        self._lstLogs = QListWidget()
        self._lstLogs.setIconSize(QSize(16, 16))
        self._lstLogs.setSpacing(2)
        layout.addWidget(self._lstLogs)

        self.setLayout(layout)

    def log_profile_current_os(
        self, profile: ComfyLocalSettings.ComfyLocalProfile
    ) -> None:
        """Validation for profile (applies to host OS)."""
        validation = profile.validate_profile()
        errors = validation["errors"]
        logs = validation["logs"]

        os = profile.current_os

        self._lstLogs.clear()

        self._lstLogs.addItem(f"{os}, Profile: {profile.name}")

        for error in errors:
            icon = get_pixmap(icon_name="warning")
            list_item = QListWidgetItem(error)
            list_item.setIcon(icon)
            self._lstLogs.addItem(list_item)

        for log in logs:
            icon = get_pixmap(icon_name="create")
            list_item = QListWidgetItem(log)
            list_item.setIcon(icon)
            self._lstLogs.addItem(list_item)

        if not errors:
            icon = get_pixmap(icon_name="success")
            list_item = QListWidgetItem(f"{os}: Validated & usable!")
            list_item.setIcon(icon)
            self._lstLogs.addItem(list_item)

    def log_profile_all_os(
        self, profile: ComfyLocalSettings.ComfyLocalProfile
    ) -> None:
        """Validation for profile (applies to all OS')."""
        os_list = ["win", "lin", "osx"]
        self._lstLogs.clear()
        for _os in os_list:
            validation = profile._validate_profile_for_os(_os)  # noqa : SLF001
            errors = validation["errors"]
            logs = validation["logs"]

            os = profile._map_internal_os_name(_os)  # noqa : SLF001

            self._lstLogs.addItem(f"{os}:\n{profile.name}")

            for error in errors:
                icon = get_pixmap(icon_name="warning")
                list_item = QListWidgetItem(error)
                list_item.setIcon(icon)
                self._lstLogs.addItem(list_item)

            for log in logs:
                icon = get_pixmap(icon_name="create")
                list_item = QListWidgetItem(log)
                list_item.setIcon(icon)
                self._lstLogs.addItem(list_item)

            if not errors:
                icon = get_pixmap(icon_name="success")
                list_item = QListWidgetItem(f"{os}: Validated & usable!")
                list_item.setIcon(icon)
                self._lstLogs.addItem(list_item)


def _test_window() -> None:
    settings = ComfyLocalSettings()
    win = LocalProfileDialog()
    win.populate_list(settings)
    win.exec()
