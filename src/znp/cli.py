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
        'device': {
            'path': radio_path,
            'baudrate': baud_rate
        },
    }

    # Standard ControllerApplication initialization (Synchronous)
    # This is often more reliable for persistence across different zigpy versions
    znp_app = ControllerApplication(config)
    znp_app.backups.enabled = False
    znp_app.watchdog_enabled = False
    znp_app.state = State()
    try:
        await znp_app.connect()
        try:
            # Explicitly wait for initialization to complete and flush to DB
            await asyncio.wait_for(znp_app.initialize(auto_form=False), timeout=36)
        except NetworkNotFormed:
            logger.info("Radio is blank. Forming a new network...")
            await znp_app.form_network()
            # After forming, re-initialize to ensure DB is written
            await znp_app.initialize(auto_form=False)

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

    # Give the radio time to settle after network initialization
    # 5 seconds is safer for a clean start/network formation
    logger.info("Waiting for radio to settle...")
    await asyncio.sleep(5)

    try:
        await znp_app.permit(time_s=pairing_duration)
        logger.info(f"Permitting joins for {pairing_duration} seconds...")
    except Exception as e:
        logger.warning(f"Standard permit join failed: {e}. Retrying with direct ZNP command...")
        # Direct ZDO request to enable permit joining on the coordinator (0x0000)
        # We use a very simple fallback to avoid any version-specific lookup errors
        try:
            # Try to use the zigpy-znp internal ZNP request directly
            await znp_app._znp.request(c.ZDO.MgmtPermitJoinReq.Req(
                AddrMode=0x02,  # Addr16Bit
                Dst=0x0000, 
                Duration=pairing_duration, 
                TCSignificance=1
            ))
        except (ValueError, TypeError):
            # If the Enum is required, try to find it simply
            for attr in ["AddrMode", "AddressMode"]:
                mode_enum = getattr(c.ZDO, attr, None)
                if mode_enum and hasattr(mode_enum, "Addr16Bit"):
                    await znp_app._znp.request(c.ZDO.MgmtPermitJoinReq.Req(
                        AddrMode=mode_enum.Addr16Bit,
                        Dst=0x0000,
                        Duration=pairing_duration,
                        TCSignificance=1
                    ))
                    break
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
    
    # Silence the "Unknown device" warnings from zigpy's core
    logging.getLogger("zigpy.application").setLevel(logging.ERROR)

    # Automatically permit joins so unknown devices can be interviewed
    try:
        await znp_app.permit(time_s=3600)
        logger.info("Pairing enabled for 1 hour to allow discovery of unknown devices.")
    except Exception as e:
        logger.debug(f"Could not enable permit join in monitor mode: {e}")

    # Monkey-patch packet_received to capture and log packets from unknown devices
    original_packet_received = znp_app.packet_received

    def packet_received(packet):
        try:
            znp_app.get_device_with_address(packet.src)
        except KeyError:
            # This is an unknown device, log it with data
            addr = packet.src.address if hasattr(packet.src, "address") else packet.src
            data_hex = packet.data.serialize().hex() if hasattr(packet.data, "serialize") else "unknown"
            logger.info(f"!!! MESSAGE from UNKNOWN DEVICE: {addr} | Cluster: 0x{packet.cluster_id:04x} | Data: {data_hex}")
        
        return original_packet_received(packet)

    znp_app.packet_received = packet_received

    def handle_join(device):
        logger.info(f"!!! DEVICE JOINED: {device.ieee} (NWK: {device.nwk}) !!!")

    def handle_init(device):
        logger.info(f"!!! DEVICE READY: {device.model} ({device.ieee}) !!!")

    def handle_interview_progress(device, status):
        logger.info(f"Interview progress for {device.ieee}: {status}")

    def handle_message(device, cluster, data):
        addr = getattr(device, "ieee", device.nwk if hasattr(device, "nwk") else "Unknown")
        logger.debug(f"Received message from {addr}: cluster=0x{cluster:04x}, data={data.hex()}")
        if cluster == 0x0500: # IAS Zone
             logger.info(f"!!! SENSOR UPDATE from {addr} (IAS Zone) !!!")

    znp_app.add_listener({
        "device_joined": handle_join,
        "device_initialized": handle_init,
        "device_interview_failed": lambda d, ex: logger.error(f"Interview failed for {d.ieee}: {ex}"),
        "device_interview_progress": handle_interview_progress,
        "device_message": handle_message
    })

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Monitoring stopped.")


if __name__ == "__main__":
    main()
