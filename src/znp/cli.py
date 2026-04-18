import argparse
import logging
import sys

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

    getattr(sys.modules[__name__], args.mode)()

def pair():
    logger.info("Pairing mode")


def reset():
    logger.info("Reset mode")


def monitor():
    logger.info("Reset mode")

if __name__ == "__main__":
    main()
