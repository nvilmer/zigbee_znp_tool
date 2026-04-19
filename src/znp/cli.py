import argparse
import asyncio
import logging
import sys

import zigpy_znp.commands as c
from zigpy.exceptions import NetworkNotFormed
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
        'device': {
            'path': radio_path,
            'baudrate': baud_rate
        },
    }

    # Use .new() but WITHOUT pre-calling SCHEMA() to avoid double validation bugs
    # auto_form=False, and start_radio=False ensure we keep the existing connection logic
    znp_app = await ControllerApplication.new(
        config=config,
        auto_form=False,
        start_radio=False
    )
    znp_app.backups.enabled = False
    znp_app.watchdog_enabled = False
    try:
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
    # Ping the radio to ensure it's responsive
    await znp_app._znp.request(c.SYS.Ping.Req())

    pairing_duration = 254

    def handle_join(device):
        logger.info(f"!!! DEVICE JOINED: {device.ieee} !!!")

    def handle_init(device):
        logger.info(f"!!! DEVICE READY: {device.model} ({device.ieee}) !!!")

    def handle_interview_progress(device, status):
        logger.info(f"Interview progress for {device.ieee}: {status}")

    def handle_device_updated(device):
        logger.info(f"Device updated/persisted: {device.ieee}")

    def handle_message(device, cluster, data):
        logger.debug(f"Received message from {device.ieee}: cluster=0x{cluster:04x}, data={data.hex()}")
        if cluster == 0x0500: # IAS Zone
             logger.info(f"!!! SENSOR UPDATE from {device.ieee} (IAS Zone) !!!")

    znp_app.add_listener({
        "device_joined": handle_join,
        "device_initialized": handle_init,
        "device_interview_failed": lambda d, ex: logger.error(f"Interview failed for {d.ieee}: {ex}"),
        "device_interview_progress": handle_interview_progress,
        "device_updated": handle_device_updated,
        "device_message": handle_message
    })

    # Give the radio a second to settle after network initialization
    await asyncio.sleep(2)

    try:
        await znp_app.permit(time_s=pairing_duration)
        logger.info(f"Permitting joins for {pairing_duration} seconds...")
    except Exception as e:
        logger.error(f"Failed to permit joining: {e}")
        # On NWK_INVALID_REQUEST, we might need to try a ZNP-specific permit command
        logger.info("Retrying with ZNP-specific permit command...")
        # Direct ZDO request to enable permit joining on the coordinator (0x0000)
        # AddrMode=0x02 (Addr16Bit)
        await znp_app._znp.request(c.ZDO.MgmtPermitJoinReq.Req(
            AddrMode=0x02, 
            Dst=0x0000, 
            Duration=pairing_duration, 
            TCSignificance=1
        ))
        logger.info(f"Permit join sent directly to ZNP for {pairing_duration} seconds.")

    logger.info("Pairing active. Waiting for devices...")
    await asyncio.sleep(pairing_duration)
    logger.info("Pairing expired.")


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
    logger.info("Start monitoring... (Press Ctrl+C to stop)")

    def handle_message(device, cluster, data):
        logger.debug(f"Received message from {device.ieee}: cluster=0x{cluster:04x}, data={data.hex()}")
        if cluster == 0x0500: # IAS Zone
             logger.info(f"!!! SENSOR UPDATE from {device.ieee} (IAS Zone) !!!")

    znp_app.add_listener({
        "device_message": handle_message
    })

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Monitoring stopped.")


if __name__ == "__main__":
    main()
