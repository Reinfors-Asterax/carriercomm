from typing import Tuple, Optional, Dict, Any, Union
import json
import logging
import os
import re
import requests  # type: ignore
import sys
import threading
import queue
from datetime import datetime, timedelta, timezone

import tkinter as tk
from tkinter import ttk, messagebox

from companion import CAPIData, SERVER_LIVE, SERVER_LEGACY, SERVER_BETA
from config import config, appname
from theme import theme
import myNotebook as nb

# Initialize module variables
this = sys.modules[__name__]
this.plugin_name = "CarrierComm"
this.version_info = (0, 1, 7)
this.version = ".".join(map(str, this.version_info))
this.logger = logging.getLogger(f'{appname}.{this.plugin_name}')
if not this.logger.hasHandlers():
    level = logging.INFO  # So logger.info(...) is equivalent to print()

    this.logger.setLevel(level)
    logger_channel = logging.StreamHandler()
    logger_formatter = logging.Formatter(f'%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d:%(funcName)s: %(message)s')
    logger_formatter.default_time_format = '%Y-%m-%d %H:%M:%S'
    logger_formatter.default_msec_format = '%s.%03d'
    logger_channel.setFormatter(logger_formatter)
    this.logger.addHandler(logger_channel)

STATE_FILE = os.path.join(os.path.dirname(__file__), this.plugin_name, "carrier_state.json")
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

# Tkinter variables
CarrierTrackerSetting: Optional[tk.IntVar] = None
this.webhookURL = tk.StringVar(value=config.get_str('discord_webhook_url'))
this.carrierImageURL = tk.StringVar(value=config.get_str('carrier_image_url'))
this.arrivalMessage = tk.BooleanVar(value=False)
this.departureMessage = tk.BooleanVar(value=True)
this.cancelledMessage = tk.BooleanVar(value=True)

DEFAULT_IMAGE_URL = "https://static.wikia.nocookie.net/elite-dangerous/images/c/cd/ED-Drake-Class-Carrier.png/revision/latest/scale-to-width-down/1000?cb=20200326223341"
discord_webhook_pattern = r"^https://discord\.com/api/webhooks/\d+/\S+$"

style = ttk.Style()
style.configure("My.TCheckbutton", background='white', borderwidth=0)

# Queue and Thread for background processing
update_queue = queue.Queue()
worker_thread = None
stop_event = threading.Event()

# Worker Class
class WebhookWorker(threading.Thread):
    def __init__(self, app_frame: tk.Frame):
        super().__init__()
        self.app_frame = app_frame
        self.stop_event = threading.Event()
        this.logger.info("WebhookWorker initialized")  # Debugging line

    def run(self):
        this.logger.info("WebhookWorker started")  # Debugging line
        while not self.stop_event.is_set():
            try:
                self.app_frame.event_generate(UPDATE_WEBHOOK_STATUS_EVENT)
                this.logger.info("Generated update event")  # Debugging line
                update_queue.get(timeout=1)  # wait for a new task with shorter timeout
            except queue.Empty:
                continue
        this.logger.info("WebhookWorker stopped")  # Debugging line

def check_webhook_url():
    webhook_url = this.webhookURL.get()
    if not webhook_url or webhook_url.strip() == "":
        update_queue.put("Webhook URL is not set or is empty")
        this.logger.warning("Webhook URL is empty")  # Use logger
    else:
        try:
            response = requests.head(webhook_url, timeout=5)
            if response.status_code == 200:
                update_queue.put("Webhook URL is configured and active.")
                this.logger.info("Webhook URL is active")
            else:
                update_queue.put("Webhook URL is invalid.")
                this.logger.warning("Webhook URL returned invalid status code")
        except requests.RequestException as e:
            update_queue.put(f"Error reaching Webhook URL: {str(e)}")
            this.logger.error(f"Exception raised while checking webhook: {str(e)}")

def load_state() -> Dict[str, Any]:
    """Load the carrier state from the JSON file."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as file:
            return json.load(file)
    return {}

def save_state(state: Dict[str, Any]) -> None:
    """Save the carrier state to the JSON file."""
    try:
        with open(STATE_FILE, "w") as file:
            json.dump(state, file)
        this.logger.info("State saved successfully.")
    except Exception as e:
        this.logger.error(f"Failed to save state: {str(e)}")


def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> Optional[tk.Frame]:
    """Create the preferences frame for the plugin."""

    PADX = 10
    PADY = 2
    BOXY = 2
    SEPY = 10
    cur_row = 0

    global CarrierTrackerSetting

    frame = nb.Frame(parent)
    frame.columnconfigure(1, weight=1)

    this.conf_frame = nb.Frame(frame)
    this.conf_frame.grid(columnspan=3, sticky=tk.EW)
    this.conf_frame.columnconfigure(1, weight=1)

    nb.Label(
        this.conf_frame, text=this.plugin_name, underline=True
    ).grid(row=cur_row, padx=PADX, sticky=tk.W)
    nb.Label(this.conf_frame, text="Version: %s" % this.version).grid(row=cur_row, column=1, columnspan= 2,padx=PADX, sticky=tk.E)
    cur_row += 1

    ttk.Checkbutton(this.conf_frame, text="Carrier Jump Message", variable=this.departureMessage, style="My.TCheckbutton").grid(row=cur_row, column=0, padx=PADX, sticky=tk.W)
    cur_row += 1
    ttk.Checkbutton(this.conf_frame, text="Carrier Jump Cancelled Message", variable=this.cancelledMessage, style="My.TCheckbutton").grid(row=cur_row, column=0, padx=PADX, sticky=tk.W)
    cur_row += 1
    nb.Label(this.conf_frame, text="If you disconnected before the carrier arrived at the destination, this won't trigger.").grid(row=cur_row, column=0, columnspan=2, padx=PADX, sticky=tk.W)
    cur_row += 1
    ttk.Checkbutton(this.conf_frame, text="Carrier Jump Arrival Message", variable=this.arrivalMessage, style="My.TCheckbutton").grid(row=cur_row, column=0, padx=PADX, sticky=tk.W)
    cur_row += 1

    ttk.Separator(this.conf_frame, orient=tk.HORIZONTAL).grid(
        columnspan=5, padx=PADX, pady=SEPY, sticky=tk.EW, row=cur_row
    )
    cur_row += 1

    nb.Label(this.conf_frame, text=(
        "Enter your Discord Webhook URL to receive notifications, and the Carrier Image URL to display an image in notifications."
    )).grid(sticky=tk.EW, row=cur_row, column=0, padx=PADX, pady=PADY, columnspan=3)
    cur_row += 1

    nb.Label(this.conf_frame, text="Discord Webhook URL").grid(row=cur_row, padx=PADX, pady=PADY, sticky=tk.W)
    webhook_entry = nb.Entry(this.conf_frame, textvariable=this.webhookURL, width=50, show="*")  # Mask the text
    webhook_entry.grid(row=cur_row, column=1, padx=PADX, pady=0, sticky=tk.EW)  # Full width for the entry

    # Add a button to toggle visibility
    def toggle_webhook_visibility():
        if webhook_entry.cget('show') == '*':
            webhook_entry.config(show='')
            toggle_button.config(text='Hide URL')
        else:
            webhook_entry.config(show='*')
            toggle_button.config(text='Show URL')

    toggle_button = ttk.Button(this.conf_frame, text='Show URL', command=toggle_webhook_visibility)
    toggle_button.grid(row=cur_row, column=2, padx=PADX, pady=0, sticky=tk.W)  # Stick to the left

    cur_row += 1

    nb.Label(this.conf_frame, text="Carrier Image URL").grid(row=cur_row, padx=PADX, pady=PADY, sticky=tk.W)
    image_entry = nb.Entry(this.conf_frame, textvariable=this.carrierImageURL, width=50, show="*")  # Mask the text
    image_entry.grid(row=cur_row, column=1, padx=PADX, pady=PADY, sticky=tk.EW)  # Full width for the entry

    # Add a button to toggle visibility for the image URL
    def toggle_image_visibility():
        if image_entry.cget('show') == '*':
            image_entry.config(show='')
            image_toggle_button.config(text='Hide URL')
        else:
            image_entry.config(show='*')
            image_toggle_button.config(text='Show URL')

    image_toggle_button = ttk.Button(this.conf_frame, text='Show URL', command=toggle_image_visibility)
    image_toggle_button.grid(row=cur_row, column=2, padx=PADX, pady=PADY, sticky=tk.W)  # Stick to the left

    return frame

def prefs_changed(cmdr: str, is_beta: bool):
    webhook_url = this.webhookURL.get()
    image_url = this.carrierImageURL.get()

    departure_message_enabled = this.departureMessage.get()
    cancelled_message_enabled = this.cancelledMessage.get()
    arrival_message_enabled = this.arrivalMessage.get()

    # Save the configuration
    config.set('discord_webhook_url', webhook_url)
    config.set('carrier_image_url', image_url)

    config.set('departure_message', departure_message_enabled)
    config.set('cancelled_message', cancelled_message_enabled)
    config.set('arrival_message', arrival_message_enabled)
    config.save()

# Define a custom event
UPDATE_WEBHOOK_STATUS_EVENT = "<<UpdateWebhookStatus>>"

def plugin_app(parent: tk.Frame) -> Union[tk.Widget, Tuple[tk.Widget, tk.Widget]]:
    # Create the main application frame
    app_frame = tk.Frame(parent)
    app_frame.pack(fill=tk.BOTH, expand=True)

    # Status label for displaying the plugin's activity status
    status_label = tk.Label(app_frame, text="", fg="red", pady=0, bd=0)
    status_label.pack(pady=2)

    # Dynamic label for webhook status
    dynamic_status_label = tk.Label(app_frame, text="Checking webhook status...", font=("Helvetica", 15), pady=0, bd=0, height=1)
    dynamic_status_label.pack(pady=4)

    # Labels for displaying carrier information
    carrier_label = tk.Label(app_frame, text="", font=("Helvetica", 12))
    carrier_label.pack(pady=4)

    location_label = tk.Label(app_frame, text="Current Location: N/A", font=("Helvetica", 12))
    location_label.pack(pady=4)

    # Function to update the displayed carrier information
    def update_carrier_info():
        # Retrieve carrier details from the carrier_state dictionary
        carrier_name = carrier_state.get('name', 'Unknown Carrier')
        carrier_callsign = carrier_state.get('callsign', 'N/A')
        current_system = carrier_state.get('current_system', 'Unknown System')
        current_planet = carrier_state.get('current_planet', 'Unknown Planet')

        # Update the labels with the latest carrier information
        carrier_label.config(text=f"{carrier_name} ({carrier_callsign})")
        location_label.config(text=f"Current Location: {current_system} ({current_planet})")

    # Function to update the status label for the webhook
    def update_webhook_status(status_message: str, color: str):
        status_label.config(text=status_message, fg=color)

    # Function to check the webhook URL's validity and status
    def check_webhook():
        webhook_url = this.webhookURL.get()

        # Validate the webhook URL
        if not webhook_url or webhook_url.strip() == "":
            return f"{this.plugin_name} is inactive", "Webhook URL is invalid or empty", "red"

        # Validate that the webhook URL is a Discord webhook
        discord_webhook_pattern = r"^https://discord\.com/api/webhooks/\d+/\S+$"
        if not re.match(discord_webhook_pattern, webhook_url):
            return f"{this.plugin_name} is inactive", "Webhook URL is invalid or not a Discord webhook.", "red"

        # Check the webhook URL's status
        try:
            response = requests.head(webhook_url, timeout=5)
            if response.status_code == 200:
                return f"{this.plugin_name} is active", "Webhook URL is valid and active", "green"
            else:
                return f"{this.plugin_name} is inactive", "Webhook URL is invalid or empty", "red"
        except requests.RequestException:
            return f"{this.plugin_name} is inactive", "Webhook URL is invalid or empty", "red"

    # Function for periodic checks of the webhook status and carrier information
    def periodic_check():
        status, dynamic_status, color = check_webhook()
        update_webhook_status(dynamic_status, color)
        dynamic_status_label.config(text=status, fg=color)

        # Update the carrier information periodically
        update_carrier_info()

        # Schedule the next check in 10 seconds
        app_frame.after(10000, periodic_check)

    # Perform an initial check of the webhook status
    status, dynamic_status, color = check_webhook()
    update_webhook_status(dynamic_status, color)
    dynamic_status_label.config(text=status, fg=color)

    # Start periodic checking for updates
    app_frame.after(10000, periodic_check)

    # Initial update for carrier info
    update_carrier_info()

    return app_frame

def plugin_start3(plugin_dir):
    """Initialize the plugin and load settings."""
    this.plugin_dir = plugin_dir
    global carrier_state
    carrier_state = load_state()

    # Load saved configuration
    this.webhookURL.set(config.get_str('discord_webhook_url'))
    this.carrierImageURL.set(config.get_str('carrier_image_url'))

    # Load boolean preferences with default values
    this.departureMessage.set(config.get_bool('departure_message'))
    this.cancelledMessage.set(config.get_bool('cancelled_message'))
    this.arrivalMessage.set(config.get_bool('arrival_message'))

    # Handle defaults if necessary
    if this.departureMessage.get() is None:
        this.departureMessage.set(True)  # Default value

    if this.cancelledMessage.get() is None:
        this.cancelledMessage.set(True)  # Default value

    if this.arrivalMessage.get() is None:
        this.arrivalMessage.set(False)  # Default value

    return this.plugin_name

def send_embed_to_discord(title: str, description: str, image: Optional[str] = None, color: int = 0x3498db, fields: Optional[list] = None):
    """Send an embed message to Discord."""
    commander_name = carrier_state.get('commander', 'Unknown')
    webhook_url = this.webhookURL.get()
    image_url = this.carrierImageURL.get()
    formatted_time = datetime.now(timezone.utc).strftime("%H:%M:%S")

    embed = {
        "title": title,
        "description": description,
        "color": color,
        "footer": {"text": f"Galactic Time: {formatted_time} | CMDR {commander_name}"},
        "image": {"url": image_url},
    }
    if fields:
        embed["fields"] = fields

    payload = {"embeds": [embed]}
    headers = {"Content-Type": "application/json"}

    response = requests.post(webhook_url, json=payload, headers=headers)
    if response.status_code != 204:
        this.logger.error(f"Failed to send webhook: {response.text}")

def plugin_stop():
    """Clean up when the plugin stops."""
    stop_event.set()  # Signal the worker thread to stop
    try:
        if worker_thread is not None:
            worker_thread.stop()  # Call the stop method to exit the thread
            worker_thread.join(timeout=1)  # Wait for the worker thread to finish
            this.logger.info("Worker thread has been stopped and joined.")
    except Exception as e:
        this.logger.error(f"Error stopping the worker thread: {e}")


def capi_fleetcarrier(data):
    if data.get('name') is None or data['name'].get('callsign') is None:
        raise ValueError("this isn't possible")
    carrier_state['name'] = data['name']
    carrier_state['callsign'] = data['callsign']
    save_state(carrier_state)


def get_system_name(market_id: str) -> Optional[str]:
    """Retrieve the system name from the EDSM API."""
    current_system_exist = carrier_state.get('current_system')

    # Check if the current system already exists
    if current_system_exist:
        this.logger.info(f"Current system '{current_system_exist}' already exists. Skipping API request.")
        return current_system_exist  # Return the existing system name

    # If current_system does not exist, proceed with the API request
    url = f"https://www.edsm.net/api-system-v1/stations/market?marketId={market_id}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return data.get('name', None)
        else:
            this.logger.warning(f"Error fetching system name: {response.status_code}")
            return None
    except requests.RequestException as e:
        this.logger.error(f"Request failed: {e}")
        return None


# Additional functions for sending messages can be added below...
def journal_entry(cmdrname: str, is_beta: bool, system: str, station: str, entry: dict, state: dict) -> None:
    """Process a journal entry and send updates to Discord."""
    fields = []
    global carrier_state, lockdown_start, departure, departure_str, lockdown_str, arrival_str, description

    try:
        event_type = entry.get('event', 'Unknown')
        carrier_state['commander'] = cmdrname
        save_state(carrier_state)

        if event_type == 'CarrierStats':
            """Update carrier state with stats from the entry."""
            carrierID = entry.get('CarrierID')

            system_name = get_system_name(carrierID) if carrierID else 'Unknown'
            carrier_state['current_system'] = system_name

            carrier_state.update({
                'name': entry.get('Name', 'Unknown'),
                'callsign': entry.get('Callsign', 'Unknown'),
                'carrierId': entry.get('CarrierID'),
                'fuel_level': entry.get('FuelLevel', 0),
                'jump_range_curr': entry.get('JumpRangeCurr', 0.0),
                'jump_range_max': entry.get('JumpRangeMax', 0.0),
            })
            save_state(carrier_state)

        elif event_type == 'Location':
            """Update carrier location based on entry."""
            carrier_callsign = carrier_state.get('callsign', None)
            if entry.get('Docked', False) and entry.get('StationName') == carrier_callsign:
                star_system = entry.get('StarSystem', None)
                planet = entry.get('Body')
                carrier_state['current_system'] = star_system
                carrier_state['current_planet'] = planet if planet and entry.get('BodyType') == "Planet" else None
                carrier_state['dock_status'] = True
            else:
                carrier_state['dock_status'] = False
            save_state(carrier_state)

        elif event_type == "Docked":
            """Update docked state based on entry."""
            carrier_callsign = carrier_state.get('callsign', 'Unknown')
            if entry.get('StationName') == carrier_callsign:
                carrier_state['current_system'] = entry.get('StarSystem', 'Unknown')
                save_state(carrier_state)

        elif event_type == 'CarrierJumpRequest':
            if this.departureMessage.get():
                # System name and optionally a celestial body
                target_system = entry.get('SystemName', 'Unknown')
                target_body = entry.get('Body', None)  # Check if a specific celestial body is targeted
                jump_time = entry.get('DepartureTime', 'Unknown')
                carrier_state['target_system'] = target_system
                carrier_state['target_planet'] = target_body
                save_state(carrier_state)
                current_system = carrier_state.get('current_system', None)

                # Get the carrier's name and callsign
                carrier_name = carrier_state.get('name', 'Unknown')
                carrier_callsign = carrier_state.get('callsign', 'Unknown')

                # Calculate the lockdown end time
                if jump_time != 'Unknown':
                    departure_dt = datetime.strptime(jump_time, "%Y-%m-%dT%H:%M:%SZ")
                    lockdown_duration = timedelta(minutes=3, seconds=20)
                    arrival_duration = timedelta(minutes=1, seconds=15)
                    lockdown_start = departure_dt - lockdown_duration
                    arrival_end = departure_dt + arrival_duration
                    timeofdeparture = departure_dt

                    lockdown_str = lockdown_start.strftime("%B %d %Y, %H:%M:%S")
                    departure_str = timeofdeparture.strftime("%B %d %Y, %H:%M:%S")
                    arrival_str = arrival_end.strftime("%B %d %Y, %H:%M:%S")

                    # Convert DepartureTime and lockdown times to Unix timestamps
                    departure = int(departure_dt.timestamp())
                    lockdown_start = int(lockdown_start.timestamp())

                # Check if the player is docked
                if carrier_state.get('dock_status', False) and current_system:
                    current_system = carrier_state.get('current_system', None)  # Where the carrier is currently located
                # Add the current system as a field
                fields.append({"name": "Departing From:", "value": f"**{current_system}**", "inline": True})

                # Add the target system and body information
                if target_body and target_body != target_system:
                    fields.append(
                        {"name": "System Destination:", "value": f"**{target_system}**", "inline": True})
                    fields.append(
                        {"name": "Orbit Destination:", "value": f"**{target_body}**", "inline": True})
                else:
                    fields.append({"name": "Destination:", "value": f"**{target_system}**", "inline": True})
                # Add departure and lockdown times as a field
                fields.append({"name": "Estimated Departure",
                               "value": f"{departure_str}", "inline": True})
                fields.append({"name": "Estimated Lockdown",
                               "value": f"{lockdown_str}", "inline": True})

                # Send the embed to Discord
                send_embed_to_discord(
                    f"{carrier_name} {carrier_callsign} | Frame Shift Drive Charging",
                    f"Carrier is preparing to jump",  # Empty description if not needed
                    fields=fields
                )

        elif event_type == 'CarrierJump':
            if this.arrivalMessage.get():
                current_system = entry.get('StarSystem', None)
                current_body = entry.get('Body', None)  # Check if a specific celestial body is mentioned

                carrier_state['current_system'] = current_system
                carrier_state['current_planet'] = current_body
                carrier_state.pop('jump_time', None)  # Clear jump time after arrival
                save_state(carrier_state)

                carrier_name = carrier_state.get('name', 'Unknown')
                carrier_callsign = carrier_state.get('callsign', 'Unknown')

                if current_body and current_body != current_system:
                    description = f"Carrier has arrived at their destination"
                    fields.append(
                        {"name": "Staying at:", "value": f"System: **{current_system}**\nOrbiting: **{current_body}**",
                         "inline": True})
                else:
                    description = f"Carrier has arrived at their destination"
                    fields.append(
                        {"name": "Staying at:", "value": f"System: **{current_system}**",
                         "inline": True})

                send_embed_to_discord(
                    f"{carrier_name} {carrier_callsign} | Capital Class Signature Detected",
                    description,
                    color=0x3498db,
                    fields=fields
                )
        elif event_type == 'CarrierJumpCancelled':
            if this.cancelledMessage.get():
                target_system = carrier_state.get('target_system')
                current_system = carrier_state.get('current_system')
                current_planet = carrier_state.get('current_planet')

                carrier_state.pop('jump_time', None)

                carrier_name = carrier_state.get('name', 'Unknown')
                carrier_callsign = carrier_state.get('callsign', 'Unknown')

                if current_system and target_system:
                    description = f"Carrier jump to **{target_system}** has been cancelled"

                    if current_planet:
                        fields.append({"name": "Staying at:",
                                       "value": f"System: **{current_system}**\nOrbiting: **{current_planet}**",
                                       "inline": True})
                    else:
                        fields.append({"name": "Staying at:", "value": f"System: **{current_system}**", "inline": True})

                elif target_system:
                    description = f"Carrier jump to **{target_system}** has been cancelled"

                save_state(carrier_state)
                send_embed_to_discord(
                    f"{carrier_name} {carrier_callsign} | Carrier Jump Cancelled",
                    description,
                    color=0xffa500,
                    fields=fields
                )
                carrier_state.pop('target_system', None)
                carrier_state.pop('target_planet', None)

    except Exception as e:
        this.logger.error(f"Error {str(e)}")
