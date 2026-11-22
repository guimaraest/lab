"""Power usage recording and reports backed exclusively by power.log."""

import fcntl
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol

from cli.constants import CLI_ROOT

POWER_LOG = CLI_ROOT / "power.log"
SCHEMA_VERSION = 1
EVENTS = {"periodic", "shutdown", "poweron"}


@dataclass(frozen=True)
class PowerReading:
    """A meter snapshot; implementors may provide cumulative joules or watts."""

    method: str
    domain: str
    energy_j: float | None = None
    max_energy_j: float | None = None
    power_w: float | None = None
    label: str | None = None


class PowerMeter(Protocol):
    """Interface for adding another power measurement backend."""

    def snapshot(self) -> Iterable[PowerReading]: ...


class LinuxPowercapMeter:
    """Read cumulative energy counters exposed by Linux powercap drivers."""

    method = "linux-powercap"
    roots = (Path("/sys/class/powercap"), Path("/sys/class/power_cap"))

    def snapshot(self):
        readings = []
        for root in self.roots:
            if not root.is_dir():
                continue
            try:
                controllers = list(root.iterdir())
            except OSError:
                continue
            for controller in controllers:
                if not controller.is_dir():
                    continue
                zones = [controller] if (controller / "energy_uj").is_file() else []
                if not zones:
                    try:
                        zones = [zone for zone in controller.iterdir() if zone.is_dir() and (zone / "energy_uj").is_file()]
                    except OSError:
                        continue
                for zone in zones:
                    try:
                        energy_j = int((zone / "energy_uj").read_text().strip()) / 1_000_000
                        max_path = zone / "max_energy_range_uj"
                        max_energy_j = int(max_path.read_text().strip()) / 1_000_000 if max_path.is_file() else None
                        label_path = zone / "name"
                        label = label_path.read_text().strip() if label_path.is_file() else zone.name
                    except (OSError, ValueError):
                        continue
                    domain = zone.relative_to(root).as_posix()
                    readings.append(PowerReading(self.method, domain, energy_j, max_energy_j, label=label))
        return readings


# Add new PowerMeter implementations here; the log schema accepts either energy_j or power_w.
POWER_METERS: tuple[PowerMeter, ...] = (LinuxPowercapMeter(),)


def collect_readings(meters=None):
    readings = []
    for meter in POWER_METERS if meters is None else meters:
        readings.extend(meter.snapshot())
    return readings


def _timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _serialize_reading(reading):
    result = {key: value for key, value in asdict(reading).items() if value is not None}
    if reading.power_w is not None:
        result["power_w_kind"] = "instantaneous"
    return result


def _counter_delta(previous, current):
    old = previous.get("energy_j")
    new = current.get("energy_j")
    if old is None or new is None:
        return None
    if new >= old:
        return new - old
    maximum = current.get("max_energy_j") or previous.get("max_energy_j")
    if maximum and old >= maximum * 0.8 and new <= maximum * 0.2:
        return maximum - old + new
    return None


def _load_events(stream):
    events = []
    for line_number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("each event must be a mapping")
            if event.get("schema_version") != SCHEMA_VERSION or event.get("event") not in EVENTS:
                raise ValueError("unknown power event schema or type")
            if not isinstance(event.get("timestamp"), str):
                raise ValueError("timestamp must be a string")
            _timestamp(event["timestamp"])
            if not isinstance(event.get("measurements"), list):
                raise ValueError("measurements must be a list")
            if any(not isinstance(measurement, dict) for measurement in event["measurements"]):
                raise ValueError("each measurement must be a mapping")
            if any(
                not isinstance(measurement.get("method"), str)
                or not isinstance(measurement.get("domain"), str)
                for measurement in event["measurements"]
            ):
                raise ValueError("each measurement requires method and domain strings")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise SystemExit(f"invalid power.log line {line_number}: {error}")
        events.append(event)
    return events


def read_power_log(path=POWER_LOG):
    if not path.exists():
        return []
    with path.open() as log_file:
        return _load_events(log_file)


def _last_measurement(events, method, domain):
    for event in reversed(events):
        for measurement in reversed(event["measurements"]):
            if measurement.get("method") == method and measurement.get("domain") == domain:
                return event, measurement
    return None, None


def _record_event(event_type, path=POWER_LOG, meters=None):
    readings = collect_readings(meters)
    if event_type == "periodic" and not readings:
        raise SystemExit(
            "no readable power meter is available; periodic snapshots currently require a Linux powercap energy counter"
        )

    timestamp = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as log_file:
        fcntl.flock(log_file.fileno(), fcntl.LOCK_EX)
        log_file.seek(0)
        events = _load_events(log_file)
        measurements = [_serialize_reading(reading) for reading in readings]
        if event_type == "periodic":
            current_time = _timestamp(timestamp)
            for measurement in measurements:
                previous_event, previous = _last_measurement(
                    events, measurement["method"], measurement["domain"]
                )
                if previous is None or previous_event["event"] == "shutdown":
                    continue
                elapsed = (current_time - _timestamp(previous_event["timestamp"])).total_seconds()
                energy_delta = _counter_delta(previous, measurement)
                if elapsed > 0 and energy_delta is not None:
                    measurement["power_w"] = energy_delta / elapsed
                    measurement["power_w_kind"] = "interval-average"

        record = {
            "schema_version": SCHEMA_VERSION,
            "timestamp": timestamp,
            "event": event_type,
            "measurements": measurements,
        }
        log_file.seek(0, os.SEEK_END)
        log_file.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        log_file.flush()
        os.fsync(log_file.fileno())
        fcntl.flock(log_file.fileno(), fcntl.LOCK_UN)

    if event_type == "periodic":
        estimates = [item["power_w"] for item in measurements if item.get("power_w") is not None]
        if estimates:
            print(f"recorded power snapshot; estimated average: {sum(estimates):.1f} W")
        else:
            print("recorded power snapshot; average power will be available after the next sample")
    else:
        print(f"recorded system {event_type} event")


def cmd_record(args):
    _record_event(args.event)


def _month_bounds(year, month):
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _overlap_fraction(start, end, target_start, target_end):
    duration = (end - start).total_seconds()
    if duration <= 0:
        return 0.0
    overlap_start = max(start, target_start)
    overlap_end = min(end, target_end)
    overlap = (overlap_end - overlap_start).total_seconds()
    return max(0.0, overlap / duration)


def monthly_energy(events, year, month):
    """Calculate measured joules from power.log intervals overlapping a UTC month."""
    target_start, target_end = _month_bounds(year, month)
    previous = {}
    totals = {}
    interval_count = 0

    for event in events:
        current_time = _timestamp(event["timestamp"])
        if event["event"] == "poweron":
            previous.clear()
        for measurement in event["measurements"]:
            key = (measurement.get("method"), measurement.get("domain"))
            prior = previous.get(key)
            if prior is not None:
                prior_event, prior_measurement = prior
                prior_time = _timestamp(prior_event["timestamp"])
                delta_j = _counter_delta(prior_measurement, measurement)
                supports_power_integration = (
                    prior_measurement.get("energy_j") is None
                    or measurement.get("energy_j") is None
                    or (
                        prior_measurement.get("power_w_kind") == "instantaneous"
                        and measurement.get("power_w_kind") == "instantaneous"
                    )
                )
                if delta_j is None and supports_power_integration:
                    old_w = prior_measurement.get("power_w")
                    new_w = measurement.get("power_w")
                    if old_w is not None and new_w is not None:
                        delta_j = (old_w + new_w) * 0.5 * (current_time - prior_time).total_seconds()
                fraction = _overlap_fraction(prior_time, current_time, target_start, target_end)
                if delta_j is not None and fraction:
                    method = measurement.get("method", "unknown")
                    totals[method] = totals.get(method, 0.0) + delta_j * fraction
                    interval_count += 1
            previous[key] = (event, measurement)
        if event["event"] == "shutdown":
            previous.clear()

    return totals, interval_count


def report_month(month, path=POWER_LOG):
    try:
        year, month_number = (int(part) for part in month.split("-", 1))
        datetime(year, month_number, 1)
    except (ValueError, TypeError):
        raise SystemExit("month must use YYYY-MM format")

    events = read_power_log(path)
    totals, intervals = monthly_energy(events, year, month_number)
    print(f"Power consumption for {year:04d}-{month_number:02d} (UTC)")
    if not totals:
        print("No measurable power intervals recorded in power.log for this month.")
        return
    for method, energy_j in sorted(totals.items()):
        print(f"{method}: {energy_j / 3_600_000:.3f} kWh")
    print(f"Total measured energy: {sum(totals.values()) / 3_600_000:.3f} kWh across {intervals} intervals")
    print("Measurements cover only the power domains reported by the installed meter.")


def cmd_power_report(args):
    month = args.month or datetime.now(timezone.utc).strftime("%Y-%m")
    report_month(month)
