#!/usr/bin/env python3
"""
GTK GUI for HoG Peripheral - Steam Deck friendly interface.

Shows controller state, connection status, and input visualization.
"""

import logging
import os
import sys
import threading
from enum import Enum

import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gdk, GLib, Gtk


class ConnectTypeEnum(Enum):
    BLUETOOTH = 'bluetooth'
    WIRED = 'wired'


# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hogp.adv import Advertisement
from hogp.bluez import (
    ensure_adapter_powered_and_discoverable,
    find_adapter_path,
    get_adapter_index,
    get_primary_connected_device,
    get_system_bus,
    register_advertisement_async,
    register_application_async,
    reset_adapter_to_default_state,
    set_adapter_alias,
    set_static_ble_address,
    unregister_advertisement_async,
    unregister_application_async,
)
from hogp.gatt_app import GattApplication
from hogp.input_handler import InputHandler
from hogp.usb_gadget import USBGadgetHID

logger = logging.getLogger(__name__)

# HID Keyboard key codes
HID_KEY_CODES = {
    'a': 0x04,
    'b': 0x05,
    'c': 0x06,
    'd': 0x07,
    'e': 0x08,
    'f': 0x09,
    'g': 0x0A,
    'h': 0x0B,
    'i': 0x0C,
    'j': 0x0D,
    'k': 0x0E,
    'l': 0x0F,
    'm': 0x10,
    'n': 0x11,
    'o': 0x12,
    'p': 0x13,
    'q': 0x14,
    'r': 0x15,
    's': 0x16,
    't': 0x17,
    'u': 0x18,
    'v': 0x19,
    'w': 0x1A,
    'x': 0x1B,
    'y': 0x1C,
    'z': 0x1D,
    '1': 0x1E,
    '2': 0x1F,
    '3': 0x20,
    '4': 0x21,
    '5': 0x22,
    '6': 0x23,
    '7': 0x24,
    '8': 0x25,
    '9': 0x26,
    '0': 0x27,
    'Enter': 0x28,
    'Escape': 0x29,
    'Backspace': 0x2A,
    'Tab': 0x2B,
    'Space': 0x2C,
    '-': 0x2D,
    '=': 0x2E,
    '[': 0x2F,
    ']': 0x30,
    '\\': 0x31,
    ';': 0x33,
    "'": 0x34,
    '`': 0x35,
    ',': 0x36,
    '.': 0x37,
    '/': 0x38,
    'F1': 0x3A,
    'F2': 0x3B,
    'F3': 0x3C,
    'F4': 0x3D,
    'F5': 0x3E,
    'F6': 0x3F,
    'F7': 0x40,
    'F8': 0x41,
    'F9': 0x42,
    'F10': 0x43,
    'F11': 0x44,
    'F12': 0x45,
    'Left': 0x50,
    'Right': 0x4F,
    'Up': 0x52,
    'Down': 0x51,
    # Media/Volume keys
    'VolUp': 0x80,
    'VolDown': 0x81,
    'Mute': 0x7F,
    'PlayPause': 0xCD,
    'Stop': 0xB7,
    'NextTrack': 0xB5,
    'PrevTrack': 0xB6,
}

# Modifier keys (bitmask)
MOD_LCTRL = 0x01
MOD_LSHIFT = 0x02
MOD_LALT = 0x04
MOD_LGUI = 0x08


class ControllerVisualizer(Gtk.Box):
    """Placeholder widget for controller tab."""

    def __init__(self, hid_output_getter):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(50)
        self.set_margin_bottom(50)
        self.set_margin_start(50)
        self.set_margin_end(50)

        self.hid_output_getter = hid_output_getter

        button_box = Gtk.CenterBox()
        button_box.set_margin_top(30)
        button_box.set_hexpand(True)

        self.home_button = Gtk.Button(label='⌂ Home')
        self.home_button.add_css_class("amoled-btn")
        self.home_button.set_size_request(150, 150)
        self.home_button.connect('clicked', self._send_home)
        button_box.set_start_widget(self.home_button)

        self.qam_button = Gtk.Button(label='⋯ QAM')
        self.qam_button.add_css_class("amoled-btn")
        self.qam_button.set_size_request(150, 150)
        self.qam_button.connect('clicked', self._send_qam)
        button_box.set_end_widget(self.qam_button)

        button_box.set_center_widget(None)

        self.append(button_box)

    def _send_home(self, button=None):
        """Send Ctrl+1 for Home button."""
        hid_output = self.hid_output_getter()
        logger.info(f'Home button clicked. hid_output={hid_output}')
        if hid_output:
            if hasattr(hid_output, 'notifying') and hid_output.notifying:
                # Bluetooth mode (GATT)
                hid_output._kbd_modifiers = MOD_LCTRL
                hid_output._kbd_keys = [0x1E, 0, 0, 0, 0, 0]  # '1' key
                hid_output._send_keyboard_notification()
                logger.info('Home: Sent Ctrl+1 press')
                # Release after 50ms
                GLib.timeout_add(50, self._release_keys)
            elif hasattr(hid_output, 'send_key'):
                # Wired mode (USB Gadget)
                hid_output.send_key(0x1E, MOD_LCTRL)
                logger.info('Home: Sent Ctrl+1 press (wired)')

    def _send_qam(self, button=None):
        """Send Ctrl+2 for QAM button."""
        hid_output = self.hid_output_getter()
        logger.info(f'QAM button clicked. hid_output={hid_output}')
        if hid_output:
            if hasattr(hid_output, 'notifying') and hid_output.notifying:
                # Bluetooth mode (GATT)
                hid_output._kbd_modifiers = MOD_LCTRL
                hid_output._kbd_keys = [0x1F, 0, 0, 0, 0, 0]  # '2' key
                hid_output._send_keyboard_notification()
                logger.info('QAM: Sent Ctrl+2 press')
                # Release after 50ms
                GLib.timeout_add(50, self._release_keys)
            elif hasattr(hid_output, 'send_key'):
                # Wired mode (USB Gadget)
                hid_output.send_key(0x1F, MOD_LCTRL)
                logger.info('QAM: Sent Ctrl+2 press (wired)')

    def _release_keys(self):
        """Release all keyboard keys."""
        hid_output = self.hid_output_getter()
        if hid_output and hasattr(hid_output, '_send_keyboard_notification'):
            hid_output._kbd_modifiers = 0
            hid_output._kbd_keys = [0, 0, 0, 0, 0, 0]
            hid_output._send_keyboard_notification()
            logger.info('Released keyboard keys')
        return False  # Don't repeat

    def update_state(self, buttons, axes, triggers, hat):
        """Placeholder method for compatibility."""
        pass


class HoGPeripheralGUI(Gtk.ApplicationWindow):
    """Main GUI window."""

    def __init__(self, app):
        super().__init__(application=app)
        self.set_default_size(1280, 800)
        self.set_resizable(True)

        # default mode
        self._mode = ConnectTypeEnum.BLUETOOTH

        # State
        self._bus = None
        self._adapter_path = None
        self._gatt_app = None
        self._advertisement = None
        self._input_handler = None
        self._main_loop = None
        self._registered = False
        self._running = False
        self._update_timeout_id = None

        # Build UI
        self._build_ui()

    def _set_black_theme(self):
        css_provider = Gtk.CssProvider()
        css_path = os.path.join(os.path.dirname(__file__), '../style/app.css')
        css_provider.load_from_path(css_path)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self):
        """Build the user interface."""

        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        main_box.set_margin_top(6)
        main_box.set_margin_bottom(6)
        main_box.set_margin_start(6)
        main_box.set_margin_end(6)

        # Mode selection
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        mode_box.set_halign(Gtk.Align.CENTER)

        mode_label = Gtk.Label(label='Mode:')
        mode_box.append(mode_label)

        self.bluetooth_radio = Gtk.CheckButton(label='Bluetooth')
        self.bluetooth_radio.set_active(True)
        self.bluetooth_radio.connect('toggled', self._on_bluetooth_toggled)
        mode_box.append(self.bluetooth_radio)

        self.wired_radio = Gtk.CheckButton(label='Wired USB')
        self.wired_radio.set_group(self.bluetooth_radio)
        self.wired_radio.connect('toggled', self._on_wired_toggled)
        mode_box.append(self.wired_radio)

        main_box.append(mode_box)

        # Status box
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)

        self.status_label = Gtk.Label(label='Status: Stopped')
        self.status_label.set_markup('<big><b>Status: Stopped</b></big>')
        status_box.append(self.status_label)

        self.connection_label = Gtk.Label(label='Not connected')
        status_box.append(self.connection_label)

        self.device_info_label = Gtk.Label(label='')
        self.device_info_label.set_wrap(True)
        status_box.append(self.device_info_label)

        main_box.append(status_box)

        # Helper to get active HID output (either Bluetooth GATT or USB Gadget)
        def get_hid_output():
            return self._gatt_app or self._usb_gadget

        self.visualizer = ControllerVisualizer(get_hid_output)
        main_box.append(self.visualizer)

        # Control buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_halign(Gtk.Align.CENTER)

        self.start_button = Gtk.Button(label='Start Service')
        self.start_button.connect('clicked', self._on_start_clicked)
        button_box.append(self.start_button)

        self.stop_button = Gtk.Button(label='Stop Service')
        self.stop_button.set_sensitive(False)
        self.stop_button.connect('clicked', self._on_stop_clicked)
        button_box.append(self.stop_button)

        main_box.append(button_box)

        self.set_child(main_box)

        self._set_black_theme()

    def _on_bluetooth_toggled(self, button):
        """Handle Bluetooth mode selection."""
        if button.get_active() and not self._running:
            self._mode = ConnectTypeEnum.BLUETOOTH
            logger.info('Mode: Bluetooth')

    def _on_wired_toggled(self, button):
        """Handle Wired mode selection."""
        if button.get_active() and not self._running:
            self._mode = ConnectTypeEnum.WIRED
            logger.info('Mode: Wired USB')

    def _on_start_clicked(self, button):
        """Start the controller service."""
        self.start_button.set_sensitive(False)
        self.bluetooth_radio.set_sensitive(False)
        self.wired_radio.set_sensitive(False)
        self.status_label.set_markup('<big><b>Status: Starting...</b></big>')

        if self._mode == ConnectTypeEnum.BLUETOOTH:
            threading.Thread(target=self._start_bluetooth_service, daemon=True).start()
        else:
            threading.Thread(target=self._start_wired_service, daemon=True).start()

    def _on_stop_clicked(self, button):
        """Stop the controller service."""
        self.stop_button.set_sensitive(False)
        self.status_label.set_markup('<big><b>Status: Stopping...</b></big>')
        GLib.idle_add(self._stop_service)

    def _start_bluetooth_service(self):
        """Start the BLE HoG service (runs in thread)."""
        try:
            # Get D-Bus connection
            self._bus = get_system_bus()

            # Find adapter
            self._adapter_path = find_adapter_path(self._bus, 'hci0')
            if not self._adapter_path:
                GLib.idle_add(self._show_error, 'Bluetooth adapter not found')
                return

            # Set adapter alias to match our device name
            set_adapter_alias(self._bus, self._adapter_path, 'SteamDeckPad')

            # Set static address
            adapter_idx = get_adapter_index('hci0')
            set_static_ble_address(adapter_idx, 'C2:12:34:56:78:9A')

            # Ensure adapter is powered
            if not ensure_adapter_powered_and_discoverable(self._bus, self._adapter_path):
                GLib.idle_add(self._show_error, 'Failed to power on Bluetooth')
                return

            # Create GATT application
            self._gatt_app = GattApplication(self._bus, device_name='SteamDeckPad', verbose=False)
            self._gatt_app.set_report_rate(60)

            if not self._gatt_app.register():
                GLib.idle_add(self._show_error, 'Failed to register GATT service')
                return

            # Create advertisement
            self._advertisement = Advertisement(self._bus, 'SteamDeckPad', verbose=False)
            if not self._advertisement.register():
                GLib.idle_add(self._show_error, 'Failed to register advertisement')
                return

            # Register with BlueZ
            GLib.idle_add(self._register_with_bluez)

        except Exception as e:
            logger.error(f'Failed to start bluetooth service: {e}')
            GLib.idle_add(self._show_error, f'Error: {e}')

    def _start_wired_service(self):
        """Start the USB Gadget wired mode service (runs in thread)."""
        try:
            logger.info('Starting USB Gadget HID in wired mode...')

            # Check if USB gadget is already set up
            import os
            import subprocess

            if not (os.path.exists('/dev/hidg0') and os.path.exists('/dev/hidg1') and os.path.exists('/dev/hidg2')):
                logger.info('USB gadget not configured, running setup script...')
                GLib.idle_add(self._show_info, 'Setting up USB gadget (requires password)...')

                # Find script directory (relative to this file)
                script_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts')
                script_path = os.path.join(script_dir, 'setup-usb-gadget.sh')

                # Run setup script with pkexec (GUI sudo prompt)
                try:
                    result = subprocess.run(['pkexec', 'bash', script_path], capture_output=True, text=True, timeout=30)
                    if result.returncode != 0:
                        GLib.idle_add(self._show_error, f'USB gadget setup failed: {result.stderr}')
                        return
                    logger.info('USB gadget setup successful')
                except subprocess.TimeoutExpired:
                    GLib.idle_add(self._show_error, 'USB gadget setup timed out')
                    return
                except Exception as e:
                    GLib.idle_add(self._show_error, f'Failed to run setup script: {e}')
                    return

            # Create USB gadget HID instance
            self._usb_gadget = USBGadgetHID(verbose=False)

            if not self._usb_gadget.open():
                GLib.idle_add(self._show_error, 'Failed to open USB gadget devices. Setup may have failed.')
                return

            self._running = True
            self._start_input_handler()

            GLib.idle_add(self._update_status_wired_active)

        except Exception as e:
            logger.error(f'Failed to start wired service: {e}')
            GLib.idle_add(self._show_error, f'Error: {e}')

    def _update_status_wired_active(self):
        """Update UI for wired mode active state."""
        self.status_label.set_markup('<big><b>Status: Active - Wired USB</b></big>')
        self.connection_label.set_label('Connected via USB')
        self.device_info_label.set_label('HID devices: /dev/hidg0 (gamepad), /dev/hidg1 (keyboard), /dev/hidg2 (mouse)')
        self.stop_button.set_sensitive(True)
        # Start update loop
        self._update_timeout_id = GLib.timeout_add(50, self._update_visualizer)

    def _register_with_bluez(self):
        """Register application and advertisement with BlueZ."""

        def on_app_registered(success, error):
            if not success:
                self._show_error(f'GATT registration failed: {error}')
                return

            register_advertisement_async(
                self._bus,
                self._adapter_path,
                Advertisement.ADV_PATH,
                on_adv_registered,
            )

        def on_adv_registered(success, error):
            if not success:
                self._show_error(f'Advertisement failed: {error}')
                return

            self._registered = True
            self._running = True
            self._start_input_handler()
            self.status_label.set_markup('<big><b>Status: Active - Discoverable</b></big>')
            self.connection_label.set_label('Waiting for connection...')
            self.stop_button.set_sensitive(True)

            # Start update loop
            self._update_timeout_id = GLib.timeout_add(50, self._update_visualizer)

        register_application_async(
            self._bus,
            self._adapter_path,
            GattApplication.APP_PATH,
            on_app_registered,
        )

    def _start_input_handler(self):
        """Start forwarding physical controller input."""
        self._input_handler = InputHandler(
            device_path=None,  # Auto-detect
            on_button_change=self._on_button,
            on_axis_change=self._on_axis,
            on_trigger_change=self._on_trigger,
            on_hat_change=self._on_hat,
            verbose=False,
        )

        if self._input_handler.start():
            logger.info('Input forwarding started')
            GLib.idle_add(self._update_connection_label, 'Input device connected')
        else:
            logger.warning('No input device detected')
            GLib.idle_add(self._update_connection_label, 'No physical controller found')

    def _on_button(self, index, pressed):
        """Handle button event from physical controller."""
        if self._gatt_app:
            self._gatt_app.set_button(index, pressed)
        elif self._usb_gadget:
            self._usb_gadget.set_button(index, pressed)

    def _on_axis(self, index, value):
        """Handle axis event from physical controller."""
        if self._gatt_app:
            self._gatt_app.set_axis(index, value)
        elif self._usb_gadget:
            self._usb_gadget.set_axis(index, value)

    def _on_trigger(self, index, value):
        """Handle trigger event from physical controller."""
        if self._gatt_app:
            self._gatt_app.set_trigger(index, value)
        elif self._usb_gadget:
            self._usb_gadget.set_trigger(index, value)

    def _on_hat(self, direction):
        """Handle HAT/D-pad event from physical controller."""
        if self._gatt_app:
            self._gatt_app.set_hat(direction)
        elif self._usb_gadget:
            self._usb_gadget.set_hat(direction)

    def _update_visualizer(self):
        """Update the controller visualization."""
        if not self._running:
            return False

        # Get active HID output
        hid_output = self._gatt_app or self._usb_gadget
        if not hid_output:
            return False

        self.visualizer.update_state(
            hid_output._buttons,
            hid_output._axes,
            hid_output._triggers,
            hid_output._hat,
        )

        # Update connection status (Bluetooth mode only)
        if self._gatt_app:
            if self._gatt_app.notifying:
                # Query connected device info
                if self._bus and self._adapter_path:
                    device_info = get_primary_connected_device(self._bus, self._adapter_path)
                    if device_info:
                        self.connection_label.set_label('✓ Connected and sending data')
                        self.device_info_label.set_markup(
                            f'<b>Device:</b> {device_info["name"]}\n<b>Address:</b> {device_info["address"]}'
                        )
                    else:
                        self.connection_label.set_label('✓ Sending data')
                        self.device_info_label.set_label('')
                else:
                    self.connection_label.set_label('✓ Sending data')
            elif self._registered:
                self.connection_label.set_label('Waiting for connection...')
                self.device_info_label.set_label('')

        return True

    def _update_connection_label(self, text):
        """Update connection label."""
        self.connection_label.set_label(text)

    def _stop_service(self):
        """Stop the HoG service (Bluetooth or Wired)."""
        self._running = False

        if self._update_timeout_id:
            GLib.source_remove(self._update_timeout_id)
            self._update_timeout_id = None

        if self._input_handler:
            self._input_handler.stop()
            self._input_handler = None

        # Stop Bluetooth mode
        if self._registered and self._bus and self._adapter_path:
            unregister_advertisement_async(self._bus, self._adapter_path, Advertisement.ADV_PATH)
            unregister_application_async(self._bus, self._adapter_path, GattApplication.APP_PATH)
            self._registered = False

        if self._advertisement:
            self._advertisement.unregister()
            self._advertisement = None

        if self._gatt_app:
            self._gatt_app.unregister()
            self._gatt_app = None

        # Reset adapter to default state (restore normal Bluetooth operation)
        if self._bus and self._adapter_path:
            try:
                reset_adapter_to_default_state(self._bus, self._adapter_path)
                logger.info('Adapter restored to default state')
            except Exception as e:
                logger.warning(f'Could not reset adapter state: {e}')

        # Stop Wired mode
        if self._usb_gadget:
            self._usb_gadget.close()
            self._usb_gadget = None

        self.status_label.set_markup('<big><b>Status: Stopped</b></big>')
        self.connection_label.set_label('Not connected')
        self.device_info_label.set_label('')
        self.start_button.set_sensitive(True)
        self.stop_button.set_sensitive(False)
        self.bluetooth_radio.set_sensitive(True)
        self.wired_radio.set_sensitive(True)

    def _show_error(self, message):
        """Show error message."""
        logger.error(message)
        self.status_label.set_markup(f'<big><b>Error: {message}</b></big>')
        self.start_button.set_sensitive(True)

    def _show_info(self, message):
        """Show info message."""
        logger.info(message)
        self.status_label.set_markup(f'<big><b>{message}</b></big>')
        self.stop_button.set_sensitive(False)


class HoGApp(Gtk.Application):
    """Main application."""

    def __init__(self):
        super().__init__(application_id='com.steamdeck.hogp.gui')

    def do_activate(self):
        """Application activated."""
        window = HoGPeripheralGUI(self)
        window.fullscreen()
        window.present()


def main():
    """Main entrypoint for GUI."""
    logging.basicConfig(
        level=logging.DEBUG,  # Changed to DEBUG for more verbose logging
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    )

    app = HoGApp()
    return app.run(None)


if __name__ == '__main__':
    import sys

    sys.exit(main())
