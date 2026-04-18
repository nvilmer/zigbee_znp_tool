async def pair_device():
    # 1. Configuration for the TI CC2652P Dongle
    config = {
        'device': {
            'path': '/dev/ttyUSB0',  # Change to your port
            'baudrate': 115200,
        },
    }
