import logging
import select
import signal
import socket
import threading
import time

from .config import load_config
from .dlms_parser import FrameParseError, find_frame_start, parse_frame
from .mqtt_publisher import MqttPublisher

log = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 10.0
_INTER_BYTE_TIMEOUT = 0.5   # seconds of silence that marks end of a frame
_NO_DATA_TIMEOUT = 90.0     # warn if no data arrives within 1.5× the 60s push interval
_RECV_CHUNK = 1024
_BACKOFF_INITIAL = 5.0
_BACKOFF_MAX = 300.0
_BACKOFF_FACTOR = 2.0


def _receive_frame(sock: socket.socket) -> bytes | None:
    """
    Accumulate bytes from sock until an inter-byte silence of _INTER_BYTE_TIMEOUT.
    Returns the buffered bytes, or None if the connection was closed or errored.
    """
    buf = bytearray()
    while True:
        # Use a long timeout when waiting for the first byte of a new frame,
        # a short one to detect the end of a frame that has started.
        timeout = _INTER_BYTE_TIMEOUT if buf else _NO_DATA_TIMEOUT
        try:
            readable, _, exceptional = select.select([sock], [], [sock], timeout)
        except (ValueError, OSError):
            return None

        if exceptional:
            return None

        if not readable:
            if buf:
                # Silence after partial data → frame complete
                return bytes(buf)
            # No data for _NO_DATA_TIMEOUT seconds
            log.warning(
                "No data received for %.0f seconds — meter may be offline or silent",
                _NO_DATA_TIMEOUT,
            )
            continue

        try:
            chunk = sock.recv(_RECV_CHUNK)
        except OSError:
            return None

        if not chunk:
            # Graceful TCP close
            return None

        buf.extend(chunk)
        log.debug("Received %d bytes (buffer: %d bytes total)", len(chunk), len(buf))


def _connect_tcp(host: str, port: int, stop_event: threading.Event) -> socket.socket | None:
    delay = _BACKOFF_INITIAL
    while not stop_event.is_set():
        log.info("Connecting to Waveshare at %s:%d...", host, port)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(_CONNECT_TIMEOUT)
            sock.connect((host, port))
            sock.settimeout(None)
            log.info("TCP connection established to %s:%d", host, port)
            return sock
        except OSError as exc:
            log.error("TCP connection failed: %s. Retrying in %.0fs", exc, delay)
            if stop_event.wait(timeout=delay):
                return None  # shutdown requested during backoff
            delay = min(delay * _BACKOFF_FACTOR, _BACKOFF_MAX)
    return None


def _run(config, publisher: MqttPublisher, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        sock = _connect_tcp(config.waveshare_host, config.waveshare_port, stop_event)
        if sock is None:
            break  # shutdown

        try:
            while not stop_event.is_set():
                raw = _receive_frame(sock)
                if raw is None:
                    log.warning("TCP connection lost, reconnecting...")
                    break

                frame_start = find_frame_start(raw)
                if frame_start == -1:
                    log.debug("No 0x0F frame marker in %d-byte buffer, discarding", len(raw))
                    continue
                if frame_start > 0:
                    log.warning("Discarding %d pre-frame garbage bytes", frame_start)
                    raw = raw[frame_start:]

                try:
                    result = parse_frame(raw)
                except FrameParseError as exc:
                    log.error("Frame parse error: %s", exc)
                    log.debug("Failed frame (hex): %s", raw.hex(" "))
                    continue

                serial = ""
                if "serial_number" in result.values:
                    serial = str(result.values["serial_number"].raw_value or "")

                publisher.publish_discovery(serial)
                publisher.publish_state(result.values)
                log.info(
                    "Frame published: invoke_id=0x%08X values=%d",
                    result.invoke_id,
                    len(result.values),
                )

        except Exception:
            log.exception("Unexpected error in receive loop")
        finally:
            try:
                sock.close()
            except OSError:
                pass


def main() -> None:
    try:
        config = load_config()
    except ValueError as exc:
        logging.basicConfig(level=logging.ERROR, format="%(levelname)s: %(message)s")
        log.error("%s", exc)
        raise SystemExit(1) from exc

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    log.info(
        "Starting electricity-meter bridge — Waveshare=%s:%d MQTT=%s:%d device_id=%s",
        config.waveshare_host,
        config.waveshare_port,
        config.mqtt_host,
        config.mqtt_port,
        config.meter_device_id,
    )

    publisher = MqttPublisher(config)
    publisher.connect()

    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        log.info("Signal %d received, shutting down...", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    run_thread = threading.Thread(target=_run, args=(config, publisher, stop_event), daemon=True)
    run_thread.start()

    stop_event.wait()

    log.info("Shutting down — publishing offline status")
    publisher.set_offline()
    publisher.disconnect()
    run_thread.join(timeout=5)
    log.info("Shutdown complete")


if __name__ == "__main__":
    main()
