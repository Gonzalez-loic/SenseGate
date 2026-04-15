from sensegate_device.services.runtime import build_runtime


def main() -> None:
    runtime = build_runtime("config.yaml")
    runtime.start()


if __name__ == "__main__":
    main()
