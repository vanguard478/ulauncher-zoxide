# -*- coding: utf-8 -*-
"""Module for zoxide search ulauncher extension.

This module is an extension for ulauncher that searches for directories using
the 'zoxide' command-line tool and displays the results sorted by zoxide's ranking.
"""

import logging
import re
import time
import os
import subprocess
from pathlib import Path
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import (
    KeywordQueryEvent,
    PreferencesEvent,
    PreferencesUpdateEvent,
    ItemEnterEvent,
)
import shlex
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.ExtensionSmallResultItem import ExtensionSmallResultItem
from ulauncher.api.shared.action.ActionList import ActionList
from ulauncher.api.shared.action.ExtensionCustomAction import ExtensionCustomAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from ulauncher.api.shared.action.RunScriptAction import RunScriptAction
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, Gtk

LOG_FORMAT = '%(asctime)s - %(levelname)s - %(module)s.%(funcName)s: %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)



class ZoxideSearchExtension(Extension):
    """The zoxide search extension."""

    def __init__(self):
        """Initialize the base class and subscribe to events."""
        # logger.info("Initializing ZoxideSearchExtension")
        super(ZoxideSearchExtension, self).__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.subscribe(PreferencesEvent, PreferencesLoadListener())
        self.subscribe(PreferencesUpdateEvent, PreferencesChangeListener())
        self.subscribe(ItemEnterEvent, ItemEnterEventListener())
        self.max_results = 10
        self.command_on_select = "xdg-open"

    def search(self, query):
        """Search for entries matching a query using 'zoxide query'.

        Splits the query into words and passes them as separate arguments.
        Returns a list of path strings sorted by zoxide's ranking.
        """
        results = []
        query_words = query.split()

        cmd = ["zoxide", "query"]
        cmd.extend(query_words)
        cmd.append("--list")

        env_vars_to_log = ['HOME', 'USER', 'PATH', 'XDG_DATA_HOME', 'SHELL']
        current_env = os.environ.copy()

        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=
                False,
                encoding='utf-8',
                env=current_env
            )

#            if process.stderr:
#                logger.debug("zoxide query stderr output: %s",
#                             process.stderr.strip())

            if process.returncode != 0:
                if process.stderr:
                    logger.error("zoxide query failed with code %d: %s",
                                 process.returncode, process.stderr.strip())
                return []


            paths = [line for line in process.stdout.splitlines() if line]

            results = paths[:self.max_results]

        except FileNotFoundError:
            logger.error(
                "'zoxide' command not found. Please ensure zoxide is installed and in your PATH."
            )
            return [{
                "error": "zoxide not found"
            }]
        except Exception as e:
            logger.error(
                "An unexpected error occurred during zoxide query: %s",
                e,
                exc_info=True)
            return []

        return results


class PreferencesLoadListener(EventListener):
    """This event listener is called when the extension is loaded."""

    def on_event(self, event, extension):
        """Set extension member variables according to preferences."""
        extension.preferences.update(event.preferences)
        try:
            extension.max_results = int(
                extension.preferences.get("max_results", 10))
        except ValueError:
            logger.warning(
                "Invalid 'max_results' value '%s', using default 10",
                extension.preferences.get("max_results"))
            extension.max_results = 10
        extension.command_on_select = extension.preferences.get(
            "command_on_select", "xdg-open")
        #logger.info(
        #    "Preferences loaded: max_results=%d, command_on_select='%s'",
        #    extension.max_results, extension.command_on_select)


class PreferencesChangeListener(EventListener):
    """This event listener is called when the extension properties are changed."""

    def on_event(self, event, extension):
        """Update extension member variables when preferences change."""

        if event.id == "max_results":
            try:
                extension.max_results = int(event.new_value)
               # logger.info("Preference 'max_results' updated to %d",
               #             extension.max_results)
            except ValueError:
                logger.warning(
                    "Invalid 'max_results' value '%s' during update, keeping previous value %d",
                    event.new_value, extension.max_results)
        elif event.id == "command_on_select":
            extension.command_on_select = event.new_value
            #logger.info("Preference 'command_on_select' updated to '%s'",
            #            extension.command_on_select)


class KeywordQueryEventListener(EventListener):
    """This event listener is called when the extension keyword is typed."""

    def __init__(self):
        """Initialize the base class and members."""
        super(KeywordQueryEventListener, self).__init__()
        self.folder_icon = self.get_folder_icon()

    def on_event(self, event, extension):
        """Run search if query was entered and act on results."""
        query = event.get_argument()
        if not query:
            return RenderResultListAction([
                ExtensionResultItem(
                    icon="images/icon.png",
                    name="Type directory search terms...",
                    description=
                    "Uses zoxide to find frequently used directories",
                    on_enter=DoNothingAction(),
                )
            ])

        # logger.info("Searching zoxide for query: '%s'", query)
        results = extension.search(
            query)

        if results and isinstance(
                results[0],
                dict) and results[0].get("error") == "zoxide not found":
            logger.error("Cannot perform search because zoxide was not found")
            return RenderResultListAction([
                ExtensionResultItem(
                    icon="images/icon.png",
                    name="Error: 'zoxide' not found",
                    description=
                    "Please install zoxide and make sure it's in your PATH.",
                    on_enter=HideWindowAction(),
                )
            ])

        if not results:
            # logger.info("No results found for query: '%s'", query)
            return RenderResultListAction([
                ExtensionResultItem(
                    icon="images/icon.png",
                    name="No results matching '%s'" % query,
                    description="Try different search terms",
                    on_enter=HideWindowAction(),
                )
            ])

        entries = []
        for path_str in results:
            quoted_path = shlex.quote(path_str)

            try:
                command_string = extension.command_on_select.format(quoted_path)
            except Exception as fmt_err:
                logger.error("Error formatting command '%s' with path '%s': %s",
                             extension.command_on_select, quoted_path, fmt_err)
                continue

            script_action = RunScriptAction(command_string, None)

            update_action = ExtensionCustomAction(path_str,
                                                  keep_app_open=False)

            actions = [script_action, update_action]

            entries.append(
                ExtensionSmallResultItem(
                    icon=self.folder_icon,
                    name=self.get_display_path(path_str),
                    on_enter=ActionList(actions),
                ))

        return RenderResultListAction(entries)

    def get_display_path(self, path_str):
        """Strip /home/user from path if appropriate."""
        try:
            path = Path(path_str)
            home = Path.home()
            if path == home:
                return "~"
            elif home in path.parents:
                return "~/" + str(path.relative_to(home))
            else:
                return str(path)
        except Exception as e:
            logger.warning("Could not process path '%s' for display: %s",
                           path_str, e)
            return path_str

    def get_folder_icon(self):
        """Get a path to a reasonable folder icon.

        Fall back to an included one if none is found via GTK.
        """
        try:
            file = Gio.File.new_for_path(str(
                Path.home()))
            folder_info = file.query_info(
                "standard::icon", 0,
                None)
            icon_names = folder_info.get_icon().get_names()

            icon_theme = Gtk.IconTheme.get_default()
            folder_icon_path = None
            for name in icon_names:
                if "-symbolic" not in name:
                    icon_info = icon_theme.lookup_icon(name, 128, 0)
                    if icon_info:
                        folder_icon_path = icon_info.get_filename()
                        break
            if not folder_icon_path:
                for name in icon_names:
                    icon_info = icon_theme.lookup_icon(name, 128, 0)
                    if icon_info:
                        folder_icon_path = icon_info.get_filename()
                        break

            if folder_icon_path and os.path.exists(folder_icon_path):
                return folder_icon_path
            else:
                logger.warning(
                    "Could not find a suitable themed folder icon, falling back."
                )

        except Exception as e:
            logger.error("Error getting themed folder icon: %s. Falling back.",
                         e,
                         exc_info=True)

        fallback_icon = "images/folder.png"
        # logger.info("Falling back to default icon: %s", fallback_icon)
        return fallback_icon


class ItemEnterEventListener(EventListener):
    """This event listener is called when the user selects an entry."""

    def on_event(self, event, extension):
        """Update the zoxide database for the selected path using 'zoxide add'."""
        path_str = event.get_data()
        if not path_str or not isinstance(path_str, str):
            logger.warning("ItemEnterEvent received invalid data: %s",
                           path_str)
            return

        cmd = ["zoxide", "add", path_str]
        # logger.info("Updating zoxide database for path: '%s' (running %s)",
        #             path_str, " ".join(cmd))

        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                encoding='utf-8')
            if process.returncode != 0:
                logger.error(
                    "zoxide add failed with code %d for path '%s': %s",
                    process.returncode, path_str, process.stderr.strip())
        except FileNotFoundError:
            logger.error(
                "'zoxide' command not found during add operation. Cannot update database."
            )
        except Exception as e:
            logger.error(
                "An unexpected error occurred during zoxide add for path '%s': %s",
                path_str,
                e,
                exc_info=True)


if __name__ == "__main__":
    ZoxideSearchExtension().run()
