import argparse
import logging
import sys

from znp.core import find_radio_path, detect_baud_rate

logger = logging.getLogger(__name__)

def main():
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
    logger.info("Baud rate set to: %s", baud_rate)

    getattr(sys.modules[__name__], args.mode)()

def pair():
    logger.info("Starting pairing....")


def reset():
    logger.info("Running reset...")


def monitor():
    logger.info("Start monitoring...")

if __name__ == "__main__":
    main()
