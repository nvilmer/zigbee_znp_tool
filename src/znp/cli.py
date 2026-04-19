import argparse
import asyncio
import logging
import sys

import zigpy_znp.commands as c
from zigpy.exceptions import NetworkNotFormed
from zigpy.state import State
from zigpy_znp.types import ResetType
from zigpy_znp.zigbee.application import ControllerApplication

from znp import data_base_path
from znp.core import find_radio_path, detect_baud_rate

logger = logging.getLogger(__name__)


def main():
    asyncio.run(run())


# noinspection PyProtectedMember
async def run():
    # 1. Create the parser
    parser = argparse.ArgumentParser(
        description="A Zigbee ZNP pair/monitor/reset tool"
    )

    parser.add_argument("mode",
                        choices=["pair", "monitor", "reset"],
                        help="The mode used when running tool (air/monitor/reset).")

    args = parser.parse_args()

    if args.mode:
        logger.info("Mode is %s", args.mode)
    else:
        logger.info("usage: znp -m mode; mode: pair/monitor/reset")
        sys.exit(1)

    radio_path = find_radio_path(4292, 60000, "0001")
    logger.info("Radio path: %s", radio_path)

    baud_rate = detect_baud_rate(radio_path)

    config = {
        'database_path': str(data_base_path),
        'backups': {"enabled": False},
        'device': {
            'path': radio_path,
            'baudrate': baud_rate
        },
    }

    # noinspection PyTypeChecker
    znp_app = ControllerApplication(config)
    znp_app.backups.enabled = False
    znp_app.watchdog_enabled = False
    znp_app.state = State()
    try:
        await asyncio.sleep(2)
        await znp_app.connect()
        try:
            await asyncio.wait_for(znp_app.initialize(auto_form=False), timeout=36)
        except NetworkNotFormed:
            logger.info("Radio is blank. Forming a new network...")
            await znp_app.form_network()

        if hasattr(znp_app.backups, "_backup_task") and znp_app.backups._backup_task:
            znp_app.backups._backup_task.cancel()
        if hasattr(znp_app, "_watchdog_task") and znp_app._watchdog_task:
            znp_app._watchdog_task.cancel()

        logger.info("Connected to dongle")

        devices = znp_app.devices
        device_count = len(devices)
        logger.info("Found %d devices", device_count)
        logger.info("Devices: %s", devices)

        current_channel = znp_app.state.network_info.channel
        logger.info(f"Current channel is {current_channel}")

        # run for specified mode
        await getattr(sys.modules[__name__], args.mode)(znp_app)
    finally:
        logger.info("Shutting down...")
        await znp_app.shutdown()  # Explicitly close the connection


# noinspection PyProtectedMember
async def pair(znp_app):
    logger.info("Starting pairing....")
    await znp_app._znp.request(c.SYS.Ping.Req())

    pairing_duration = 254

    def handle_join(device):
        logger.info(f"!!! DEVICE JOINED: {device.ieee} !!!")

    def handle_init(device):
        logger.info(f"!!! DEVICE READY: {device.model} ({device.ieee}) !!!")
        znp_app.topology.save()
        logger.info("Pairing saved to database.")

    # ONE-LINE FIX: Use a dictionary for add_listener
    znp_app.add_listener({"device_joined": handle_join, "device_initialized": handle_init})

    await znp_app.permit(time_s=pairing_duration)

    logger.info("Pairing active. Waiting for devices...")
    await asyncio.sleep(pairing_duration)
    logger.info("Pairing expired.")
    znp_app.topology.save()
    logger.info("Pairing saved to database.")


# noinspection PyProtectedMember
async def reset(znp_app):
    logger.info("Starting reset...")
    await znp_app._znp.request(c.SYS.ResetReq.Req(Type=ResetType.Soft))
    logger.info("Hardware rebooted. Waiting on network stack...")
    for i in range(15):
        try:
            # We use a short timeout here so we don't hang the loop
            res = await znp_app._znp.request(c.UTIL.GetDeviceInfo.Req(), timeout=2)
            if res.DeviceState == 9:
                logger.info("Network is ONLINE.")
                return

            if res.DeviceState == 0:
                # One-line fix to move from State 0 to State 9
                await znp_app._znp.request(c.ZDO.StartupFromApp.Req(StartDelay=0))

            logger.info(f"Still waiting... Current state: {res.DeviceState}")
        except (asyncio.TimeoutError, Exception):
            # Ignore the 'TimeoutError' while the radio is still waking up
            pass

        await asyncio.sleep(2)

    logger.warning("Radio rebooted but network state is still offline.")

async def monitor(znp_app):
    logger.info("Start monitoring...")


if __name__ == "__main__":
    main()
