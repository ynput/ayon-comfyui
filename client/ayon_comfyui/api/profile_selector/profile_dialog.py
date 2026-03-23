"""Dialogs for selecting a local/remote launch profile."""

from __future__ import annotations

from enum import Enum
from functools import partial
from threading import Thread
from typing import TYPE_CHECKING, Any

from ayon_core.style import load_stylesheet
from ayon_core.tools.publisher.widgets import get_pixmap

from ayon_comfyui.parse_settings import ComfyLocalSettings, ComfyRemoteSettings

ComfyLocalProfile = ComfyLocalSettings.ComfyLocalProfile

ComfyRemoteProfile = ComfyRemoteSettings.ComfyRemoteProfile

if TYPE_CHECKING:
    # TEMP: I'm using pyside6-stubs so I don't lose my mind.
    # This is fine to leave in during development.
    # TYPE_CHECKING evaluates to False in runtime.
    from PySide6.QtCore import QPoint, QSize, Qt, Signal
    from PySide6.QtWidgets import (
        QDialog,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMenu,
        QPushButton,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
else:
    from qtpy.QtCore import QPoint, QSize, Qt, Signal
    from qtpy.QtWidgets import (
        QDialog,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMenu,
        QPushButton,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )


class ProfileTypeEnum(Enum):
    """Enum to pass to result of ProfileDialog for further scheduling."""

    UNDECIDED = 0
    LOCAL = 1
    REMOTE = 2


class ProfileDialog(QDialog):
    """Window that shows a list of profiles."""

    sig_confirm = Signal()

    def __init__(self, parent: QWidget | None = None):
        """Initialize Local/Remote launch dialog."""
        super().__init__(parent)
        self.setStyleSheet(load_stylesheet())
        self.setWindowTitle("ComfyUI profile")
        self.setMinimumWidth(420)

        # Chosen profile
        self._profile = None
        # keep ref to settings
        self.settings_local = None
        self.settings_remote = None

        mainlayout = QVBoxLayout()

        mainlayout.setAlignment(Qt.AlignmentFlag.AlignTop)

        mainlayout.addWidget(QLabel("Select launch profile..."))

        self.tabs = QTabWidget()

        self.tab_local = LocalSelectionWidget(dialog=self)
        self.tab_remote = RemoteSelectionWidget(dialog=self)
        self.tabs.addTab(self.tab_local, "Local")
        self.tabs.addTab(self.tab_remote, "Remote")
        self.index_to_tab = [self.tab_local, self.tab_remote]

        self.__result = ProfileTypeEnum.UNDECIDED

        # dummy args for function signature related failure prevention
        def _button_confirm(*args: list[Any]) -> None:  # noqa: ARG001
            """Button confirm action."""
            tab: LocalSelectionWidget | RemoteSelectionWidget = (
                self.index_to_tab[self.tab_index]
            )
            profile = tab.lstProfiles.currentItem().data(
                Qt.ItemDataRole.UserRole
            )
            if profile:
                self.confirm_commit_profile(profile)

        self._btnConfirm = QPushButton("Select profile!")
        self._btnConfirm.setDefault(True)
        self._btnConfirm.clicked.connect(partial(_button_confirm))

        self.sig_confirm.connect(partial(_button_confirm))

        mainlayout.addWidget(self.tabs)
        mainlayout.addWidget(self._btnConfirm)
        self.setLayout(mainlayout)

    @property
    def tab_index(self) -> int:
        """Return tab index."""
        return self.tabs.currentIndex()

    @property
    def dialog_result(self) -> ProfileTypeEnum:
        """Return chosen profile."""
        return self.__result

    def populate_list(self, project_name: str | None = None) -> None:
        """Adds profiles to lists from settings, with appropriate icons."""
        self.settings_local = ComfyLocalSettings(project_name=project_name)
        self.settings_remote = ComfyRemoteSettings(project_name=project_name)
        self.tab_local.populate_list(self.settings_local)
        self.tab_remote.populate_list(self.settings_remote)

    @property
    def settings(self) -> ComfyLocalSettings | ComfyRemoteSettings:
        """Returns current relevant settings instance."""
        if self.tab_index == 0:
            return self.settings_local
        return self.settings_remote

    def confirm_profile(
        self,
        profile: ComfyLocalProfile | ComfyRemoteProfile,
    ) -> None:
        """Confirms profile choice, and closes the window."""
        self._profile = profile
        self.__result = ProfileDialog.profile_enum_from_profile(profile)
        self.accept()

    def confirm_commit_profile(
        self,
        profile: ComfyLocalProfile | ComfyRemoteProfile,
    ) -> None:
        """Confirms profile choice, and closes the window.

        Additionally commits the state for later recall.
        """
        self._profile = profile
        self.__result = ProfileDialog.profile_enum_from_profile(profile)

        self.settings.commit(self._profile)
        self.accept()

    @property
    def profile(self) -> ComfyLocalProfile | ComfyRemoteProfile:
        """Returns chosen profile."""
        return self._profile

    @staticmethod
    def profile_enum_from_profile(
        profile: ComfyLocalProfile | ComfyRemoteProfile,
    ) -> ProfileTypeEnum:
        """Return associated profile type with profile."""
        if isinstance(profile, ComfyLocalProfile):
            return ProfileTypeEnum.LOCAL
        if isinstance(profile, ComfyRemoteProfile):
            return ProfileTypeEnum.REMOTE
        return ProfileTypeEnum.UNDECIDED


class LocalSelectionWidget(QWidget):
    """Class that defines contents/logic of local launch tab."""

    def __init__(
        self,
        dialog: ProfileDialog | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent=parent)

        self.dialog = dialog

        # Chosen profile
        self._profile = None
        # keep ref to settings
        self._settings = None

        layout = QVBoxLayout()

        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.lstProfiles = QListWidget()
        self.lstProfiles.setIconSize(QSize(16, 16))
        self.lstProfiles.setSpacing(2)
        self.lstProfiles.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.lstProfiles.customContextMenuRequested.connect(
            self._on_profiles_context_menu
        )

        # forward signal upstairs
        def _confirm(*args: list[Any]) -> None:  # noqa: ARG001
            self.dialog.sig_confirm.emit()

        self.lstProfiles.itemActivated.connect(_confirm)
        layout.addWidget(self.lstProfiles)

        self.setLayout(layout)

    def populate_list(self, settings: ComfyLocalSettings) -> None:
        """Adds profiles to list from settings, with appropriate icons."""
        self.lstProfiles.clear()
        self._settings = settings
        for profile_name in settings.profiles:
            self._add_profile_to_list(settings.get(profile_name))

    def _add_profile_to_list(self, item: ComfyLocalProfile) -> None:
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
        self.lstProfiles.addItem(list_item)

    def _on_profiles_context_menu(self, pos: QPoint) -> None:
        """Handle context menu for profiles."""
        item = self.lstProfiles.itemAt(pos)
        if not item:
            return

        profile: ComfyLocalProfile = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        launch_action = menu.addAction(f"Launch ComfyUI with: {profile.name}")
        launch_action.triggered.connect(
            partial(self.dialog.confirm_commit_profile, profile)
        )

        menu.addSeparator()

        logs_action = menu.addAction("View logs...")
        logs_action.triggered.connect(partial(self.show_log, profile))

        debug_action = menu.addAction("Debug for all platforms...")
        debug_action.triggered.connect(partial(self.show_debug, profile))

        menu.exec(self.lstProfiles.mapToGlobal(pos))

    def show_log(self, profile: ComfyLocalProfile) -> None:
        """Show subwindow with host os debug info about the profile in it."""
        win = ProfileDebugDialog(self)
        win.log_profile_current_os(profile)
        win.exec()

    def show_debug(self, profile: ComfyLocalProfile) -> None:
        """Show subwindow with all os debug info about the profile in it."""
        win = ProfileDebugDialog(self)
        win.log_profile_all_os(profile)
        win.exec()


class ProfileDebugDialog(QDialog):
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

    def log_profile_current_os(self, profile: ComfyLocalProfile) -> None:
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

    def log_profile_remote(self, profile: ComfyRemoteProfile) -> None:
        """Validation for profile (applies to remote hosted site)."""
        validation = profile.validate_profile()
        errors = validation["errors"]
        logs = validation["logs"]

        self._lstLogs.clear()

        self._lstLogs.addItem(f"Remote Profile: {profile.name}")

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
            list_item = QListWidgetItem(
                f"{profile.comfy_url}: Validated & usable!"
            )
            list_item.setIcon(icon)
            self._lstLogs.addItem(list_item)

    def log_profile_all_os(self, profile: ComfyLocalProfile) -> None:
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


class RemoteSelectionWidget(QWidget):
    """Tab widget for Remote Profile selection."""

    def __init__(
        self,
        dialog: ProfileDialog | None = None,
        parent: QWidget | None = None,
    ):
        """Initialize dialog."""
        super().__init__(parent)

        # Chosen profile
        self._profile = None
        # keep ref to settings
        self._settings = None
        self.dialog = dialog

        layout = QVBoxLayout()

        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.lstProfiles = QListWidget()
        self.lstProfiles.setIconSize(QSize(16, 16))
        self.lstProfiles.setSpacing(2)
        self.lstProfiles.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.lstProfiles.customContextMenuRequested.connect(
            self._on_profiles_context_menu
        )

        # dummy args for function signature related failure prevention
        def _confirm(*args: list[Any]) -> None:  # noqa: ARG001
            """Button confirm action."""
            self.dialog.sig_confirm.emit()

        self.lstProfiles.itemActivated.connect(_confirm)
        layout.addWidget(self.lstProfiles)

        self.setLayout(layout)

    def populate_list(self, settings: ComfyRemoteSettings) -> None:
        """Adds profiles to list from settings, with appropriate icons."""
        self.lstProfiles.clear()
        self._settings = settings
        for profile_name in settings.profiles:
            self._add_profile_to_list(settings.get(profile_name))

    def _add_profile_to_list(self, item: ComfyRemoteProfile) -> None:
        """Perform sanity check on profile and add it to QListWidget."""
        text = item.name
        icon = None

        icon = get_pixmap(icon_name="create")
        list_item = QListWidgetItem(text)
        list_item.setIcon(icon)

        def _validate() -> None:
            item.validate_profile(rerun=True)
            icon_valid = get_pixmap(icon_name="create")
            icon_err = get_pixmap(icon_name="warning")

            if item.is_valid:
                list_item.setIcon(icon_valid)
            else:
                list_item.setIcon(icon_err)

        Thread(target=_validate).start()

        list_item.setData(Qt.ItemDataRole.UserRole, item)
        self.lstProfiles.addItem(list_item)

    def _on_profiles_context_menu(self, pos: QPoint) -> None:
        """Handle context menu for profiles."""
        item = self.lstProfiles.itemAt(pos)
        if not item:
            return

        profile: ComfyRemoteProfile = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        launch_action = menu.addAction(
            f"Connect to ComfyUI with: {profile.name}"
        )
        launch_action.triggered.connect(
            partial(self.dialog.confirm_commit_profile, profile)
        )

        # Disable diagnosis for now.
        # TODO(@sas): implement validation & diagnosis
        menu.addSeparator()

        ogs_action = menu.addAction("View logs...")
        ogs_action.triggered.connect(partial(self.show_log, profile))

        def _revalidate() -> None:
            profile.validate_profile(rerun=True)
            icon_valid = get_pixmap(icon_name="create")
            icon_err = get_pixmap(icon_name="warning")

            if profile.is_valid:
                item.setIcon(icon_valid)
            else:
                item.setIcon(icon_err)

        def _do_revalidate() -> None:
            Thread(target=_revalidate).start()

        revalidate_action = menu.addAction("Rerun validation...")
        revalidate_action.triggered.connect(_do_revalidate)

        menu.exec(self.lstProfiles.mapToGlobal(pos))

    def show_log(
        self, profile: ComfyRemoteSettings.ComfyRemoteProfile
    ) -> None:
        """Show subwindow with host os debug info about the profile in it."""
        win = ProfileDebugDialog(self)
        win.log_profile_remote(profile)
        win.exec()
