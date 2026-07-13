"""
A Textual TUI for the ReVanced downloader / patcher.

Run with:  python3 tui.py
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Log,
    SelectionList,
    Static,
    Switch,
)
from textual.widgets.selection_list import Selection

from common import CLI_PATH, OUTPUT_DIR, PATCHES_PATH
from downloader import Downloader
from patcher import Patcher


# --------------------------------------------------------------------------- #
# Helper modal: edit the string/number options of a single patch
# --------------------------------------------------------------------------- #
class OptionsModal(ModalScreen[Optional[Dict[str, Any]]]):
    """Modal dialog for editing a patch's options before patching."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, patch: Dict[str, Any]) -> None:
        super().__init__()
        self.patch = patch
        self._inputs: Dict[str, Input] = {}
        self._switches: Dict[str, Switch] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="options-dialog"):
            yield Label(f"Options for [b]{self.patch['Name']}[/b]", id="options-title")
            with VerticalScroll(id="options-body"):
                options = self.patch.get("Options", [])
                if not options:
                    yield Label("This patch has no configurable options.")
                for opt in options:
                    key = opt["Name"]
                    default = opt.get("Default")
                    yield Label(f"{key}{'  (required)' if opt.get('Required') else ''}")
                    if opt.get("Description"):
                        yield Static(opt["Description"], classes="opt-desc")
                    if isinstance(default, bool) or opt.get("Type", "").lower() == "boolean":
                        sw = Switch(value=bool(default), id=f"sw-{key}")
                        self._switches[key] = sw
                        yield sw
                    else:
                        inp = Input(
                            value="" if default is None else str(default),
                            placeholder=str(default) if default is not None else "",
                            id=f"in-{key}",
                        )
                        self._inputs[key] = inp
                        yield inp
            with Horizontal(id="options-buttons"):
                yield Button("Save", id="save-options", variant="success")
                yield Button("Cancel", id="cancel-options", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-options":
            result: Dict[str, Any] = {}
            for key, sw in self._switches.items():
                result[key] = sw.value
            for key, inp in self._inputs.items():
                if inp.value != "":
                    result[key] = inp.value
            self.dismiss(result)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------- #
# Main app
# --------------------------------------------------------------------------- #
class ReVancedTUI(App):
    """A terminal UI wrapping the Patcher/Downloader classes."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #top-bar {
        height: auto;
        padding: 1 2 0 2;
    }

    #apk-row, #output-row {
        height: 3;
    }

    #apk-input, #output-input {
        width: 1fr;
    }

    #apk-info {
        height: auto;
        padding: 0 2;
        color: $text-muted;
    }

    #body {
        height: 1fr;
        padding: 0 2;
    }

    #patch-list {
        width: 2fr;
        border: round $primary;
    }

    #side-panel {
        width: 1fr;
        border: round $primary;
        padding: 1;
    }

    #log {
        height: 12;
        border: round $secondary;
        margin: 0 2 1 2;
    }

    #button-row {
        height: 3;
        padding: 0 2 1 2;
    }

    #options-dialog {
        width: 70;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #options-body {
        height: auto;
        max-height: 20;
        margin-bottom: 1;
    }

    .opt-desc {
        color: $text-muted;
        margin-bottom: 1;
    }

    #options-buttons {
        height: 3;
        align: right middle;
    }

    #options-buttons Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "download", "Download CLI + Patches"),
        Binding("l", "load_patches", "Load patches"),
        Binding("p", "patch", "Patch APK"),
        Binding("/", "focus_filter", "Filter"),
    ]

    apk_path: reactive[str] = reactive("")
    package_name: reactive[str] = reactive("")

    def __init__(self) -> None:
        super().__init__()
        self.patcher = Patcher()
        self.downloader = Downloader()
        self.all_patches: List[Dict[str, Any]] = []
        # patch name -> option overrides
        self.option_overrides: Dict[str, Dict[str, Any]] = {}

    # ----------------------------------------------------------------- UI --
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="top-bar"):
            with Horizontal(id="apk-row"):
                yield Input(placeholder="Path to APK file...", id="apk-input")
                yield Button("Load patches", id="load-btn", variant="primary")
            yield Label("No APK loaded.", id="apk-info")
            with Horizontal(id="output-row"):
                yield Input(
                    value=OUTPUT_DIR, placeholder="Output directory", id="output-input"
                )
            yield Input(placeholder="Filter patches...", id="filter-input")
        with Horizontal(id="body"):
            yield SelectionList[str](id="patch-list")
            with Vertical(id="side-panel"):
                yield Label("[b]Status[/b]")
                yield Static(self._resource_status(), id="resource-status")
                yield Static("", id="selection-count")
                yield Label("")
                yield Label("[b]Selected patch[/b]")
                yield Static("(none)", id="patch-detail")
                yield Button("Edit options...", id="edit-options-btn", disabled=True)
        yield Log(id="log", highlight=True)
        with Horizontal(id="button-row"):
            yield Button("Download CLI + Patches", id="download-btn", variant="warning")
            yield Button("Patch APK", id="patch-btn", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        self.log_widget = self.query_one("#log", Log)
        self.log_widget.write_line("Ready. Provide an APK path and load patches, or download resources first.")
        self._current_highlighted_index: Optional[int] = None

    def _resource_status(self) -> str:
        cli_ok = "✅" if os.path.exists(CLI_PATH) else "❌"
        patches_ok = "✅" if os.path.exists(PATCHES_PATH) else "❌"
        return f"CLI jar:      {cli_ok}\nPatches rvp:  {patches_ok}"

    # ------------------------------------------------------------ actions --
    def action_focus_filter(self) -> None:
        self.query_one("#filter-input", Input).focus()

    def action_download(self) -> None:
        self.download_resources()

    def action_load_patches(self) -> None:
        self.load_patches()

    def action_patch(self) -> None:
        self.run_patch()

    # ------------------------------------------------------------- events --
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "download-btn":
            self.download_resources()
        elif event.button.id == "load-btn":
            self.load_patches()
        elif event.button.id == "patch-btn":
            self.run_patch()
        elif event.button.id == "edit-options-btn":
            self._open_options_modal()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "apk-input":
            self.load_patches()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            self._apply_filter(event.value)

    def on_selection_list_selection_highlighted(
        self, event: SelectionList.SelectionHighlighted
    ) -> None:
        sel_list = self.query_one("#patch-list", SelectionList)
        try:
            selection = sel_list.get_option_at_index(event.selection_index)
        except Exception:
            return
        name = selection.value
        patch = next((p for p in self.all_patches if p["Name"] == name), None)
        detail = self.query_one("#patch-detail", Static)
        edit_btn = self.query_one("#edit-options-btn", Button)
        if patch:
            desc = patch.get("Description") or "(no description)"
            n_opts = len(patch.get("Options", []))
            detail.update(f"[b]{name}[/b]\n{desc}\n\nOptions: {n_opts}")
            edit_btn.disabled = n_opts == 0
            self._highlighted_patch_name = name
        else:
            detail.update("(none)")
            edit_btn.disabled = True
            self._highlighted_patch_name = None

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        sel_list = self.query_one("#patch-list", SelectionList)
        count = len(sel_list.selected)
        total = len(self.all_patches)
        self.query_one("#selection-count", Static).update(
            f"{count}/{total} patches selected"
        )

    # -------------------------------------------------------------- logic --
    def _apply_filter(self, term: str) -> None:
        sel_list = self.query_one("#patch-list", SelectionList)
        selected_names = set(sel_list.selected)
        sel_list.clear_options()
        term_lower = term.lower().strip()
        for patch in self.all_patches:
            if term_lower and term_lower not in patch["Name"].lower():
                continue
            sel_list.add_option(
                Selection(
                    patch["Name"],
                    patch["Name"],
                    patch["Name"] in selected_names,
                )
            )

    def _open_options_modal(self) -> None:
        name = getattr(self, "_highlighted_patch_name", None)
        if not name:
            return
        patch = next((p for p in self.all_patches if p["Name"] == name), None)
        if not patch:
            return

        def handle_result(result: Optional[Dict[str, Any]]) -> None:
            if result is not None:
                self.option_overrides[name] = result
                self.log_widget.write_line(f"Saved {len(result)} option override(s) for '{name}'.")

        self.push_screen(OptionsModal(patch), handle_result)

    # ------------------------------------------------------------ workers --
    @work(exclusive=True, thread=True, group="download")
    def download_resources(self) -> None:
        self.call_from_thread(self.log_widget.write_line, "Downloading ReVanced CLI...")
        try:
            self.downloader.download_cli()
            self.call_from_thread(self.log_widget.write_line, "CLI downloaded.")
            self.call_from_thread(self.log_widget.write_line, "Downloading patches bundle...")
            self.downloader.download_patches_rvp()
            self.call_from_thread(self.log_widget.write_line, "Patches bundle downloaded.")
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self.log_widget.write_line, f"[red]Download failed: {exc}[/red]")
        finally:
            self.call_from_thread(
                self.query_one("#resource-status", Static).update, self._resource_status()
            )

    @work(exclusive=True, thread=True, group="load")
    def load_patches(self) -> None:
        apk_input = self.query_one("#apk-input", Input)
        apk_path = apk_input.value.strip()
        if not apk_path:
            self.call_from_thread(self.log_widget.write_line, "[red]Please enter an APK path first.[/red]")
            return
        if not os.path.exists(apk_path):
            self.call_from_thread(self.log_widget.write_line, f"[red]APK not found: {apk_path}[/red]")
            return

        self.call_from_thread(self.log_widget.write_line, f"Reading APK metadata: {apk_path}")
        try:
            info = self.patcher.get_apk_info(apk_path)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self.log_widget.write_line, f"[red]Failed to read APK: {exc}[/red]")
            return

        self.apk_path = apk_path
        self.package_name = info["package_name"]
        self.call_from_thread(
            self.query_one("#apk-info", Label).update,
            f"Package: {info['package_name']}   Version: {info['version_name']}",
        )
        self.call_from_thread(
            self.log_widget.write_line,
            f"Fetching compatible patches for {info['package_name']}...",
        )
        try:
            patches = self.patcher.list_patches(package_name=info["package_name"])
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self.log_widget.write_line, f"[red]Failed to list patches: {exc}[/red]")
            return

        self.all_patches = patches
        self.call_from_thread(self._populate_patch_list, patches)
        self.call_from_thread(self.log_widget.write_line, f"Loaded {len(patches)} patch(es).")

    def _populate_patch_list(self, patches: List[Dict[str, Any]]) -> None:
        sel_list = self.query_one("#patch-list", SelectionList)
        sel_list.clear_options()
        for patch in patches:
            sel_list.add_option(
                Selection(patch["Name"], patch["Name"], bool(patch.get("Enabled")))
            )
        self.query_one("#selection-count", Static).update(
            f"{len(sel_list.selected)}/{len(patches)} patches selected"
        )

    @work(exclusive=True, thread=True, group="patch")
    def run_patch(self) -> None:
        if not self.apk_path:
            self.call_from_thread(self.log_widget.write_line, "[red]Load an APK and its patches first.[/red]")
            return
        if not self.all_patches:
            self.call_from_thread(self.log_widget.write_line, "[red]No patches loaded.[/red]")
            return

        sel_list = self.query_one("#patch-list", SelectionList)
        selected = set(sel_list.selected)
        default_enabled = {p["Name"] for p in self.all_patches if p.get("Enabled")}

        enabled_patches = list(selected - default_enabled)
        disabled_patches = list(default_enabled - selected)

        # Flatten per-patch option overrides into -O<key>=value entries.
        # ReVanced CLI options are namespaced per patch via the CLI itself,
        # so we just merge all override dicts (patch name isn't part of the key).
        options: Dict[str, Any] = {}
        for overrides in self.option_overrides.values():
            options.update(overrides)

        output_dir = self.query_one("#output-input", Input).value.strip() or OUTPUT_DIR
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(self.apk_path))[0]
        output_path = os.path.join(output_dir, f"{base_name}-patched.apk")

        self.call_from_thread(self.log_widget.write_line, "")
        self.call_from_thread(self.log_widget.write_line, f"Patching {self.apk_path}")
        self.call_from_thread(self.log_widget.write_line, f"  + enabled : {enabled_patches or '(none)'}")
        self.call_from_thread(self.log_widget.write_line, f"  - disabled: {disabled_patches or '(none)'}")
        self.call_from_thread(self.log_widget.write_line, f"  -> output : {output_path}")

        try:
            for line in self.patcher.patch_apk(
                apk_path=self.apk_path,
                output_path=output_path,
                enabled_patches=enabled_patches,
                disabled_patches=disabled_patches,
                options=options or None,
                stream_output=True,
            ):
                self.call_from_thread(self.log_widget.write_line, line)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self.log_widget.write_line, f"[red]Patching failed: {exc}[/red]")
            return

        self.call_from_thread(self.log_widget.write_line, f"[green]Done! Saved to {output_path}[/green]")


if __name__ == "__main__":
    ReVancedTUI().run()