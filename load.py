from typing import Tuple, Optional, Dict, Any, Union, List
import json
import logging
import os
import re
import sys
import threading
import queue
import time
from datetime import datetime, timedelta, timezone

import requests  # type: ignore
import tkinter as tk
from tkinter import ttk, messagebox

from companion import CAPIData, SERVER_LIVE, SERVER_LEGACY, SERVER_BETA
from config import config, appname
from theme import theme
import myNotebook as nb

# Initialize module reference
this = sys.modules[__name__]
this.plugin_name = "CarrierComm"
this.version_info = (0, 2, 0)
this.version = ".".join(map(str, this.version_info))
this.logger = logging.getLogger(f'{appname}.{this.plugin_name}')

if not this.logger.hasHandlers():
    this.logger.setLevel(logging.INFO)
    logger_channel = logging.StreamHandler()
    logger_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d: %(message)s'
    )
    logger_formatter.default_time_format = '%Y-%m-%d %H:%M:%S'
    logger_formatter.default_msec_format = '%s.%03d'
    logger_channel.setFormatter(logger_formatter)
    this.logger.addHandler(logger_channel)

# State file configuration and migration
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(PLUGIN_DIR, "carrier_state.json")
LEGACY_STATE_FILE = os.path.join(PLUGIN_DIR, this.plugin_name, "carrier_state.json")

# Migrate legacy nested carrier_state.json if it exists and current does not
if not os.path.exists(STATE_FILE) and os.path.exists(LEGACY_STATE_FILE):
    try:
        import shutil
        shutil.move(LEGACY_STATE_FILE, STATE_FILE)
        this.logger.info("Migrated legacy state file to plugin root.")
        # Attempt to remove empty legacy folder if possible
        try:
            os.rmdir(os.path.dirname(LEGACY_STATE_FILE))
        except OSError:
            pass
    except Exception as e:
        this.logger.warning(f"Could not migrate legacy state file: {e}")

DEFAULT_IMAGE_URL = (
    "https://static.wikia.nocookie.net/elite-dangerous/images/c/cd/"
    "ED-Drake-Class-Carrier.png/revision/latest/scale-to-width-down/1000?cb=20200326223341"
)
DISCORD_WEBHOOK_PATTERN = re.compile(
    r"^https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/\S+$"
)
USER_AGENT = f"CarrierComm/{this.version} (EDMC)"

# Tkinter variables - initialized in plugin_start3 or on demand
this.webhookURL: Optional[tk.StringVar] = None
this.carrierImageURL: Optional[tk.StringVar] = None
this.departureMessage: Optional[tk.BooleanVar] = None
this.cancelledMessage: Optional[tk.BooleanVar] = None
this.arrivalMessage: Optional[tk.BooleanVar] = None

# UI label references for reactive updates
this.carrier_label: Optional[tk.Label] = None
this.location_label: Optional[tk.Label] = None
this.status_label: Optional[tk.Label] = None
this.app_frame: Optional[tk.Frame] = None

# Background asynchronous worker queue
worker_queue: queue.Queue = queue.Queue()
worker_thread: Optional[threading.Thread] = None
stop_worker_event: threading.Event = threading.Event()


def is_valid_discord_webhook(url: Optional[str]) -> bool:
    """Validate whether the given string is a valid Discord webhook URL."""
    if not url or not isinstance(url, str):
        return False
    return bool(DISCORD_WEBHOOK_PATTERN.match(url.strip()))


def load_state() -> Dict[str, Any]:
    """Load the carrier state from the JSON file safely."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            this.logger.error(f"Failed to load state: {e}")
    return {}


def save_state(state: Dict[str, Any]) -> None:
    """Save the carrier state atomically to prevent file corruption."""
    try:
        temp_file = f"{STATE_FILE}.tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(state, file, indent=2)
        os.replace(temp_file, STATE_FILE)
    except Exception as e:
        this.logger.error(f"Failed to save state: {e}")


# Initialize global carrier state
carrier_state: Dict[str, Any] = load_state()


def _worker_loop() -> None:
    """Background worker loop to execute asynchronous tasks (webhooks, API lookups)."""
    this.logger.info("CarrierComm background worker started.")
    while not stop_worker_event.is_set():
        try:
            task = worker_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if task is None:
            worker_queue.task_done()
            break

        func, args, kwargs = task
        try:
            func(*args, **kwargs)
        except Exception as e:
            this.logger.error(f"Error in async task {getattr(func, '__name__', str(func))}: {e}", exc_info=True)
        finally:
            worker_queue.task_done()
    this.logger.info("CarrierComm background worker stopped.")


def _ensure_worker_running() -> None:
    """Ensure the background worker thread is alive."""
    global worker_thread
    if worker_thread is None or not worker_thread.is_alive():
        stop_worker_event.clear()
        worker_thread = threading.Thread(target=_worker_loop, name="CarrierCommWorker", daemon=True)
        worker_thread.start()


def enqueue_task(func, *args, **kwargs) -> None:
    """Enqueue a callable to be executed asynchronously in the background thread."""
    _ensure_worker_running()
    worker_queue.put((func, args, kwargs))


def build_discord_payload(
    title: str,
    description: str,
    fields: Optional[List[Dict[str, Any]]] = None,
    color: int = 0x3498db,
    image_url: Optional[str] = None,
    cmdr_name: Optional[str] = None
) -> Dict[str, Any]:
    """Construct a clean Discord embed payload, omitting empty image URLs to avoid 400 Bad Request."""
    formatted_time = datetime.now(timezone.utc).strftime("%H:%M:%S")
    footer_text = f"Galactic Time: {formatted_time} UTC"
    if cmdr_name:
        footer_text += f" | CMDR {cmdr_name}"

    embed: Dict[str, Any] = {
        "title": title,
        "description": description,
        "color": color,
        "footer": {"text": footer_text},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    if fields:
        embed["fields"] = fields

    # Discord rejects payloads if embed['image']['url'] is empty or malformed
    if image_url and isinstance(image_url, str):
        clean_image = image_url.strip()
        if clean_image.startswith("http://") or clean_image.startswith("https://"):
            embed["image"] = {"url": clean_image}

    return {"embeds": [embed]}


def _do_send_webhook(webhook_url: str, payload: Dict[str, Any]) -> bool:
    """Perform the HTTP POST to Discord webhook with timeout and rate-limit handling."""
    if not is_valid_discord_webhook(webhook_url):
        this.logger.warning("Skipping webhook: Invalid or missing Discord webhook URL.")
        return False

    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
    }

    for attempt in range(2):
        try:
            response = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
            if response.status_code in (200, 204):
                this.logger.info("Discord notification sent successfully.")
                return True
            elif response.status_code == 429:
                # Handle Discord rate limit
                retry_after = 1.0
                try:
                    retry_after = float(response.json().get('retry_after', 1.0))
                except Exception:
                    pass
                this.logger.warning(f"Discord rate limit encountered. Retrying in {retry_after:.1f}s...")
                time.sleep(retry_after)
                continue
            else:
                this.logger.error(f"Failed to send Discord webhook ({response.status_code}): {response.text}")
                return False
        except requests.RequestException as e:
            this.logger.error(f"Network error sending Discord webhook: {e}")
            return False
    return False


def send_embed_to_discord(
    title: str,
    description: str,
    fields: Optional[List[Dict[str, Any]]] = None,
    color: int = 0x3498db,
    image: Optional[str] = None
) -> None:
    """Asynchronously send an embed notification to Discord."""
    webhook_url = (this.webhookURL.get() if this.webhookURL else "").strip()
    if not webhook_url:
        this.logger.debug("No webhook URL configured; skipping notification.")
        return

    if not is_valid_discord_webhook(webhook_url):
        this.logger.warning(f"Cannot send notification: Webhook URL format is invalid.")
        return

    cmdr_name = carrier_state.get('commander')
    img_url = (image or (this.carrierImageURL.get() if this.carrierImageURL else "")).strip() or None

    payload = build_discord_payload(
        title=title,
        description=description,
        fields=fields,
        color=color,
        image_url=img_url,
        cmdr_name=cmdr_name
    )

    enqueue_task(_do_send_webhook, webhook_url, payload)


def _do_fetch_edsm_system(market_id: int) -> None:
    """Query EDSM API asynchronously for a carrier's current system name."""
    url = f"https://www.edsm.net/api-system-v1/stations/market?marketId={market_id}"
    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code == 200:
            data = response.json()
            system_name = data.get('name')
            if system_name and carrier_state.get('current_system') != system_name:
                carrier_state['current_system'] = system_name
                save_state(carrier_state)
                update_ui_labels()
                this.logger.info(f"Retrieved carrier location from EDSM: {system_name}")
        else:
            this.logger.debug(f"EDSM station query returned status {response.status_code}")
    except requests.RequestException as e:
        this.logger.debug(f"EDSM query failed: {e}")


def request_edsm_system_lookup(market_id: Optional[int]) -> None:
    """Enqueue an EDSM system name lookup if market_id is provided."""
    if market_id:
        enqueue_task(_do_fetch_edsm_system, market_id)


def update_ui_labels() -> None:
    """Thread-safe update of plugin labels in EDMC main window."""
    if this.app_frame is None:
        return

    def _update():
        if this.carrier_label is None or this.location_label is None:
            return

        carrier_name = carrier_state.get('name', 'Unknown Carrier')
        carrier_callsign = carrier_state.get('callsign', 'N/A')
        current_system = carrier_state.get('current_system', 'Unknown System')
        current_planet = carrier_state.get('current_planet')

        this.carrier_label.config(text=f"Carrier: {carrier_name} ({carrier_callsign})")
        if current_planet and current_planet != current_system:
            this.location_label.config(text=f"Location: {current_system} ({current_planet})")
        else:
            this.location_label.config(text=f"Location: {current_system}")

        if this.status_label:
            webhook_url = (this.webhookURL.get() if this.webhookURL else "").strip()
            if not webhook_url:
                this.status_label.config(text="Status: Webhook Not Set", fg="gray")
            elif is_valid_discord_webhook(webhook_url):
                this.status_label.config(text="Status: Active", fg="green")
            else:
                this.status_label.config(text="Status: Invalid Webhook URL", fg="red")

    try:
        this.app_frame.after(0, _update)
    except Exception:
        pass


def plugin_start3(plugin_dir: str) -> str:
    """Initialize plugin variables and settings from EDMC config."""
    this.plugin_dir = plugin_dir
    global carrier_state
    carrier_state = load_state()

    # Initialize Tkinter variables with stored preferences
    if this.webhookURL is None:
        this.webhookURL = tk.StringVar()
    this.webhookURL.set(config.get_str('discord_webhook_url') or '')

    if this.carrierImageURL is None:
        this.carrierImageURL = tk.StringVar()
    this.carrierImageURL.set(config.get_str('carrier_image_url') or '')

    if this.departureMessage is None:
        this.departureMessage = tk.BooleanVar()
    dep_val = config.get_bool('departure_message', default=True)
    this.departureMessage.set(True if dep_val is None else dep_val)

    if this.cancelledMessage is None:
        this.cancelledMessage = tk.BooleanVar()
    can_val = config.get_bool('cancelled_message', default=True)
    this.cancelledMessage.set(True if can_val is None else can_val)

    if this.arrivalMessage is None:
        this.arrivalMessage = tk.BooleanVar()
    arr_val = config.get_bool('arrival_message', default=False)
    this.arrivalMessage.set(False if arr_val is None else arr_val)

    _ensure_worker_running()
    return this.plugin_name


def plugin_app(parent: tk.Frame) -> Union[tk.Widget, Tuple[tk.Widget, tk.Widget]]:
    """Build the compact EDMC main window UI."""
    this.app_frame = tk.Frame(parent)
    this.app_frame.columnconfigure(0, weight=1)

    this.carrier_label = tk.Label(this.app_frame, text="Carrier: Unknown Carrier (N/A)", anchor=tk.W, justify=tk.LEFT)
    this.carrier_label.grid(row=0, column=0, sticky=tk.W, padx=2, pady=1)

    this.location_label = tk.Label(this.app_frame, text="Location: Unknown System", anchor=tk.W, justify=tk.LEFT)
    this.location_label.grid(row=1, column=0, sticky=tk.W, padx=2, pady=1)

    this.status_label = tk.Label(this.app_frame, text="Status: Checking...", anchor=tk.W, justify=tk.LEFT, fg="gray")
    this.status_label.grid(row=2, column=0, sticky=tk.W, padx=2, pady=1)

    theme.apply(this.app_frame)
    update_ui_labels()
    return this.app_frame


def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> Optional[tk.Frame]:
    """Create the settings frame for the plugin in EDMC settings dialog."""
    PADX = 10
    PADY = 3
    cur_row = 0

    frame = nb.Frame(parent)
    frame.columnconfigure(1, weight=1)

    nb.Label(frame, text=f"{this.plugin_name} v{this.version}", font=("Helvetica", 10, "bold")).grid(
        row=cur_row, column=0, columnspan=3, padx=PADX, pady=(6, 2), sticky=tk.W
    )
    cur_row += 1

    nb.Checkbutton(
        frame, text="Notify when Carrier Jump is Requested (Departure)", variable=this.departureMessage
    ).grid(row=cur_row, column=0, columnspan=3, padx=PADX, pady=PADY, sticky=tk.W)
    cur_row += 1

    nb.Checkbutton(
        frame, text="Notify when Carrier Jump is Cancelled", variable=this.cancelledMessage
    ).grid(row=cur_row, column=0, columnspan=3, padx=PADX, pady=PADY, sticky=tk.W)
    cur_row += 1

    nb.Checkbutton(
        frame, text="Notify when Carrier Arrives at Destination", variable=this.arrivalMessage
    ).grid(row=cur_row, column=0, columnspan=3, padx=PADX, pady=PADY, sticky=tk.W)
    cur_row += 1

    nb.Label(
        frame,
        text="Note: Arrival notifications only fire if you are docked or present in system upon arrival.",
        fg="gray"
    ).grid(row=cur_row, column=0, columnspan=3, padx=PADX, pady=0, sticky=tk.W)
    cur_row += 1

    ttk.Separator(frame, orient=tk.HORIZONTAL).grid(
        row=cur_row, column=0, columnspan=3, padx=PADX, pady=8, sticky=tk.EW
    )
    cur_row += 1

    nb.Label(frame, text="Discord Webhook URL:").grid(row=cur_row, column=0, padx=PADX, pady=PADY, sticky=tk.W)
    webhook_entry = nb.Entry(frame, textvariable=this.webhookURL, show="*")
    webhook_entry.grid(row=cur_row, column=1, padx=PADX, pady=PADY, sticky=tk.EW)

    def toggle_webhook_vis():
        if webhook_entry.cget('show') == '*':
            webhook_entry.config(show='')
            btn_webhook_vis.config(text='Hide')
        else:
            webhook_entry.config(show='*')
            btn_webhook_vis.config(text='Show')

    btn_webhook_vis = nb.Button(frame, text='Show', command=toggle_webhook_vis)
    btn_webhook_vis.grid(row=cur_row, column=2, padx=PADX, pady=PADY, sticky=tk.W)
    cur_row += 1

    nb.Label(frame, text="Carrier Image URL:").grid(row=cur_row, column=0, padx=PADX, pady=PADY, sticky=tk.W)
    image_entry = nb.Entry(frame, textvariable=this.carrierImageURL)
    image_entry.grid(row=cur_row, column=1, padx=PADX, pady=PADY, sticky=tk.EW)

    btn_default_image = nb.Button(
        frame, text='Default', command=lambda: this.carrierImageURL.set(DEFAULT_IMAGE_URL)
    )
    btn_default_image.grid(row=cur_row, column=2, padx=PADX, pady=PADY, sticky=tk.W)
    cur_row += 1

    test_status_label = nb.Label(frame, text="", fg="gray")

    def run_webhook_test():
        url = this.webhookURL.get().strip()
        if not url:
            test_status_label.config(text="Error: Discord Webhook URL is empty.", fg="red")
            return
        if not is_valid_discord_webhook(url):
            test_status_label.config(text="Error: Invalid Discord Webhook URL format.", fg="red")
            return

        test_status_label.config(text="Sending test notification...", fg="blue")

        def _test_task():
            carrier_name = carrier_state.get('name', 'CarrierComm Test')
            callsign = carrier_state.get('callsign', 'TEST-01')
            test_payload = build_discord_payload(
                title=f"{carrier_name} ({callsign}) | Test Notification",
                description="This is a test notification from the CarrierComm EDMC plugin.",
                fields=[
                    {"name": "Status", "value": "CarrierComm is operational.", "inline": True},
                    {"name": "Version", "value": f"v{this.version}", "inline": True}
                ],
                color=0x2ecc71,
                image_url=this.carrierImageURL.get().strip() or None,
                cmdr_name=carrier_state.get('commander')
            )
            success = _do_send_webhook(url, test_payload)

            def _on_result():
                if success:
                    test_status_label.config(text="Success! Test message delivered to Discord.", fg="green")
                else:
                    test_status_label.config(text="Failed to deliver test message. Check logs.", fg="red")

            try:
                frame.after(0, _on_result)
            except Exception:
                pass

        enqueue_task(_test_task)

    btn_test = nb.Button(frame, text="Test Discord Webhook", command=run_webhook_test)
    btn_test.grid(row=cur_row, column=0, padx=PADX, pady=6, sticky=tk.W)
    test_status_label.grid(row=cur_row, column=1, columnspan=2, padx=PADX, pady=6, sticky=tk.W)
    cur_row += 1

    theme.apply(frame)
    return frame


def prefs_changed(cmdr: str, is_beta: bool) -> None:
    """Save preferences when EDMC settings dialog is closed."""
    if this.webhookURL:
        config.set('discord_webhook_url', this.webhookURL.get().strip())
    if this.carrierImageURL:
        config.set('carrier_image_url', this.carrierImageURL.get().strip())
    if this.departureMessage:
        config.set('departure_message', this.departureMessage.get())
    if this.cancelledMessage:
        config.set('cancelled_message', this.cancelledMessage.get())
    if this.arrivalMessage:
        config.set('arrival_message', this.arrivalMessage.get())

    if hasattr(config, 'save'):
        config.save()

    update_ui_labels()


def capi_fleetcarrier(data: Dict[str, Any]) -> None:
    """Process Frontier Companion API fleet carrier data safely."""
    if not isinstance(data, dict):
        return

    name_data = data.get('name')
    carrier_name = None
    if isinstance(name_data, dict):
        carrier_name = name_data.get('vanityName') or name_data.get('name')
    elif isinstance(name_data, str):
        carrier_name = name_data

    callsign = data.get('callsign')
    current_system = data.get('currentStarSystem')
    fuel = data.get('fuel')
    market_id = data.get('marketId') or data.get('carrierId')

    changed = False
    if carrier_name and carrier_state.get('name') != carrier_name:
        carrier_state['name'] = carrier_name
        changed = True
    if callsign and carrier_state.get('callsign') != callsign:
        carrier_state['callsign'] = callsign
        changed = True
    if current_system and carrier_state.get('current_system') != current_system:
        carrier_state['current_system'] = current_system
        changed = True
    if fuel is not None and carrier_state.get('fuel_level') != fuel:
        carrier_state['fuel_level'] = fuel
        changed = True
    if market_id and carrier_state.get('carrierId') != market_id:
        carrier_state['carrierId'] = market_id
        changed = True

    if changed:
        save_state(carrier_state)
        update_ui_labels()


def journal_entry(
    cmdrname: str,
    is_beta: bool,
    system: str,
    station: str,
    entry: dict,
    state: dict
) -> None:
    """Process incoming Elite Dangerous journal events."""
    event_type = entry.get('event')
    if not event_type:
        return

    # Filter for relevant carrier events to avoid unnecessary processing on thousands of game events
    CARRIER_EVENTS = {
        'CarrierStats', 'Location', 'Docked', 'CarrierJumpRequest',
        'CarrierJump', 'CarrierJumpCancelled', 'CarrierDepositFuel'
    }
    if event_type not in CARRIER_EVENTS:
        return

    # Update commander name if changed
    if cmdrname and carrier_state.get('commander') != cmdrname:
        carrier_state['commander'] = cmdrname
        save_state(carrier_state)

    try:
        if event_type == 'CarrierStats':
            carrier_id = entry.get('CarrierID')
            carrier_name = entry.get('Name', 'Unknown')
            callsign = entry.get('Callsign', 'Unknown')
            fuel_level = entry.get('FuelLevel', 0)
            jump_curr = entry.get('JumpRangeCurr', 0.0)
            jump_max = entry.get('JumpRangeMax', 0.0)

            carrier_state.update({
                'name': carrier_name,
                'callsign': callsign,
                'carrierId': carrier_id,
                'fuel_level': fuel_level,
                'jump_range_curr': jump_curr,
                'jump_range_max': jump_max,
            })
            save_state(carrier_state)
            update_ui_labels()

            # If current_system is not yet known, query EDSM asynchronously
            if not carrier_state.get('current_system') and carrier_id:
                request_edsm_system_lookup(carrier_id)

        elif event_type == 'Location':
            carrier_callsign = carrier_state.get('callsign')
            if entry.get('Docked', False) and carrier_callsign and entry.get('StationName') == carrier_callsign:
                star_system = entry.get('StarSystem')
                planet = entry.get('Body')
                carrier_state['current_system'] = star_system
                carrier_state['current_planet'] = planet if planet and entry.get('BodyType') == "Planet" else None
                carrier_state['dock_status'] = True
                save_state(carrier_state)
                update_ui_labels()
            else:
                if carrier_state.get('dock_status'):
                    carrier_state['dock_status'] = False
                    save_state(carrier_state)

        elif event_type == 'Docked':
            carrier_callsign = carrier_state.get('callsign')
            if carrier_callsign and entry.get('StationName') == carrier_callsign:
                carrier_state['current_system'] = entry.get('StarSystem')
                planet = entry.get('Body')
                carrier_state['current_planet'] = planet if planet and entry.get('BodyType') == "Planet" else None
                carrier_state['dock_status'] = True
                save_state(carrier_state)
                update_ui_labels()

        elif event_type == 'CarrierDepositFuel':
            total_fuel = entry.get('Total')
            if total_fuel is not None:
                carrier_state['fuel_level'] = total_fuel
                save_state(carrier_state)
                update_ui_labels()

        elif event_type == 'CarrierJumpRequest':
            target_system = entry.get('SystemName', 'Unknown')
            target_body = entry.get('Body')
            jump_time = entry.get('DepartureTime')

            carrier_state['target_system'] = target_system
            carrier_state['target_planet'] = target_body
            save_state(carrier_state)

            if this.departureMessage and this.departureMessage.get():
                carrier_name = carrier_state.get('name', 'Unknown Carrier')
                carrier_callsign = carrier_state.get('callsign', 'Unknown')
                departing_system = carrier_state.get('current_system') or system or "Unknown System"
                departing_planet = carrier_state.get('current_planet')

                fields: List[Dict[str, Any]] = []

                if departing_planet and departing_planet != departing_system:
                    fields.append({
                        "name": "Departing From:",
                        "value": f"**{departing_system}** ({departing_planet})",
                        "inline": True
                    })
                else:
                    fields.append({
                        "name": "Departing From:",
                        "value": f"**{departing_system}**",
                        "inline": True
                    })

                if target_body and target_body != target_system:
                    fields.append({"name": "System Destination:", "value": f"**{target_system}**", "inline": True})
                    fields.append({"name": "Orbit Destination:", "value": f"**{target_body}**", "inline": True})
                else:
                    fields.append({"name": "Destination:", "value": f"**{target_system}**", "inline": True})

                if jump_time:
                    try:
                        # Parse ISO 8601 UTC timestamp correctly
                        departure_dt = datetime.strptime(jump_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                        lockdown_dt = departure_dt - timedelta(minutes=3, seconds=20)

                        departure_ts = int(departure_dt.timestamp())
                        lockdown_ts = int(lockdown_dt.timestamp())

                        fields.append({
                            "name": "Estimated Departure",
                            "value": f"<t:{departure_ts}:T> (<t:{departure_ts}:R>)",
                            "inline": True
                        })
                        fields.append({
                            "name": "Lockdown Starts",
                            "value": f"<t:{lockdown_ts}:T> (<t:{lockdown_ts}:R>)",
                            "inline": True
                        })
                    except Exception as e:
                        this.logger.warning(f"Could not parse jump time '{jump_time}': {e}")
                        fields.append({"name": "Departure Time", "value": str(jump_time), "inline": True})

                send_embed_to_discord(
                    title=f"{carrier_name} ({carrier_callsign}) | Frame Shift Drive Charging",
                    description="Carrier is preparing for jump.",
                    fields=fields,
                    color=0x3498db
                )

        elif event_type == 'CarrierJump':
            current_system = entry.get('StarSystem')
            current_body = entry.get('Body')

            carrier_state['current_system'] = current_system
            carrier_state['current_planet'] = current_body if current_body and current_body != current_system else None
            carrier_state.pop('target_system', None)
            carrier_state.pop('target_planet', None)
            save_state(carrier_state)
            update_ui_labels()

            if this.arrivalMessage and this.arrivalMessage.get():
                carrier_name = carrier_state.get('name', 'Unknown Carrier')
                carrier_callsign = carrier_state.get('callsign', 'Unknown')
                fields = []

                if current_body and current_body != current_system:
                    fields.append({
                        "name": "Location:",
                        "value": f"System: **{current_system}**\nOrbiting: **{current_body}**",
                        "inline": True
                    })
                else:
                    fields.append({
                        "name": "Location:",
                        "value": f"System: **{current_system}**",
                        "inline": True
                    })

                send_embed_to_discord(
                    title=f"{carrier_name} ({carrier_callsign}) | Capital Class Signature Detected",
                    description="Carrier has arrived at destination.",
                    fields=fields,
                    color=0x2ecc71
                )

        elif event_type == 'CarrierJumpCancelled':
            target_system = carrier_state.pop('target_system', None)
            carrier_state.pop('target_planet', None)
            save_state(carrier_state)

            if this.cancelledMessage and this.cancelledMessage.get():
                carrier_name = carrier_state.get('name', 'Unknown Carrier')
                carrier_callsign = carrier_state.get('callsign', 'Unknown')
                current_system = carrier_state.get('current_system')
                current_planet = carrier_state.get('current_planet')

                fields = []
                if current_system:
                    if current_planet and current_planet != current_system:
                        fields.append({
                            "name": "Holding Position:",
                            "value": f"System: **{current_system}**\nOrbiting: **{current_planet}**",
                            "inline": True
                        })
                    else:
                        fields.append({
                            "name": "Holding Position:",
                            "value": f"System: **{current_system}**",
                            "inline": True
                        })

                cancel_desc = f"Jump to **{target_system}** was cancelled." if target_system else "Carrier jump was cancelled."
                send_embed_to_discord(
                    title=f"{carrier_name} ({carrier_callsign}) | Jump Cancelled",
                    description=cancel_desc,
                    fields=fields,
                    color=0xe67e22
                )

    except Exception as e:
        this.logger.error(f"Error processing journal event {event_type}: {e}", exc_info=True)


def plugin_stop() -> None:
    """Clean up and stop worker thread upon EDMC shutdown."""
    this.logger.info("Stopping CarrierComm plugin...")
    stop_worker_event.set()
    worker_queue.put(None)  # Wake up queue get()
    if worker_thread is not None and worker_thread.is_alive():
        worker_thread.join(timeout=1.5)
    this.logger.info("CarrierComm plugin stopped.")
