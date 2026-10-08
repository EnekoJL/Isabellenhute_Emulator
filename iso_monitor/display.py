"""Terminal display for isolation sensor data using rich."""

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.columns import Columns
from rich import box

from isolation_sensor import (
    IsolationSensorState,
    VoltageStatus, CurrentStatus, ResThreshold, SafeToStart,
    ResStatus, EarthLiftStatus, PosNegStatus, PackLinkStatus, TempStatus,
    MSG_IVT_HVBATTERY, MSG_IVT_VOLTAGELINK, MSG_IVT_VOLTAGEPACK,
    MSG_IVT_VOLTAGELINKPRCHDIFF, MSG_IVT_ISORESTOTAL,
    MSG_IVT_ISORESPOSNEG, MSG_IVT_ISORESPACKLINK, MSG_IVT_TEMPERATURE,
)

MSG_NAME = {
    MSG_IVT_HVBATTERY:           "HV Battery",
    MSG_IVT_VOLTAGELINK:         "Voltage Link",
    MSG_IVT_VOLTAGEPACK:         "Voltage Pack",
    MSG_IVT_VOLTAGELINKPRCHDIFF: "Voltage Link PreChg",
    MSG_IVT_ISORESTOTAL:         "ISO Res Total",
    MSG_IVT_ISORESPOSNEG:        "ISO Res Pos/Neg",
    MSG_IVT_ISORESPACKLINK:      "ISO Res Pack/Link",
    MSG_IVT_TEMPERATURE:         "Temperature",
}


def _status_style(val: int, ok_val: int = 0) -> str:
    return "green" if val == ok_val else "red"


def build_layout(state: IsolationSensorState) -> Columns:
    v = state.voltage
    i = state.current
    r = state.resistance
    t = state.temperature

    # --- Voltage table ---
    vt = Table(title="Voltages", box=box.SIMPLE_HEAVY, show_lines=False)
    vt.add_column("Signal", style="cyan", no_wrap=True)
    vt.add_column("Value", justify="right")
    vt.add_column("Status", justify="center")

    def v_row(label, volts, status_val):
        style = _status_style(status_val)
        vt.add_row(label, f"{volts:+.3f} V",
                   f"[{style}]{VoltageStatus.label(status_val)}[/{style}]")

    v_row("Battery",       v.battery_V,    v.battery_status)
    v_row("Link+",         v.link_plus_V,  v.link_plus_status)
    v_row("Link-",         v.link_minus_V, v.link_minus_status)
    v_row("Pack+",         v.pack_plus_V,  v.pack_plus_status)
    v_row("Pack-",         v.pack_minus_V, v.pack_minus_status)
    v_row("PreChg Diff",   v.prech_diff_V, v.prech_diff_status)
    v_row("PreChg",        v.prech_V,      v.prech_status)

    # --- Current table ---
    ct = Table(title="Current", box=box.SIMPLE_HEAVY, show_lines=False)
    ct.add_column("Signal", style="cyan")
    ct.add_column("Value", justify="right")
    ct.add_column("Status", justify="center")
    style = _status_style(i.current_status)
    ct.add_row("Current",
               f"{i.current_A:+.3f} A",
               f"[{style}]{CurrentStatus.label(i.current_status)}[/{style}]")

    # --- Resistance table ---
    rt = Table(title="Isolation Resistance", box=box.SIMPLE_HEAVY, show_lines=False)
    rt.add_column("Signal", style="cyan", no_wrap=True)
    rt.add_column("Value", justify="right")
    rt.add_column("Status", justify="center")

    def r_row(label, value_str, status_str, ok: bool):
        col = "green" if ok else "red"
        rt.add_row(label, value_str, f"[{col}]{status_str}[/{col}]")

    r_row("Total",       f"{r.total_kohm} kΩ",
          ResThreshold.label(r.threshold_status), r.threshold_status == 0)
    r_row("Safe-to-Start", "",
          SafeToStart.label(r.safe_to_start), r.safe_to_start == 3)
    r_row("Res Status",  "",
          ResStatus.label(r.res_status), r.res_status == 0)
    r_row("Earth Lift",  "",
          EarthLiftStatus.label(r.earth_lift_status), True)
    rt.add_row("", "", "")
    r_row("Pos/Neg",     "",
          PosNegStatus.label(r.posneg_status), r.posneg_status == 0)
    rt.add_row("  Positive",  f"{r.pos_kohm} kΩ", "")
    rt.add_row("  Negative",  f"{r.neg_kohm} kΩ", "")
    rt.add_row("", "", "")
    r_row("Pack/Link",   "",
          PackLinkStatus.label(r.packlink_status), r.packlink_status == 0)
    rt.add_row("  Pack",      f"{r.pack_kohm} kΩ", "")
    rt.add_row("  Link",      f"{r.link_kohm} kΩ", "")

    # --- Temperature table ---
    tt = Table(title="Temperature", box=box.SIMPLE_HEAVY, show_lines=False)
    tt.add_column("Signal", style="cyan")
    tt.add_column("Value", justify="right")
    tt.add_column("Status", justify="center")
    style = _status_style(t.status)
    tt.add_row("Shunt",
               f"{t.temp_C} °C",
               f"[{style}]{TempStatus.label(t.status)}[/{style}]")

    # --- Stats panel ---
    last_name = MSG_NAME.get(state.last_msg_id, f"0x{state.last_msg_id:04X}")
    stats = (
        f"Frames received : [bold]{state.msg_count}[/bold]\n"
        f"Sequence errors : [{'red' if state.seq_errors else 'green'}]{state.seq_errors}[/]\n"
        f"Last message    : [cyan]{last_name}[/cyan]"
    )
    stats_panel = Panel(stats, title="Stats", border_style="dim")

    left  = Columns([vt, ct], equal=False, expand=False)
    right = Columns([rt, tt], equal=False, expand=False)

    return Panel(
        Columns([
            Panel(left,   title="Electrical", border_style="blue"),
            Panel(right,  title="Isolation & Thermal", border_style="yellow"),
            stats_panel,
        ], expand=True),
        title="[bold white]Isolation Sensor Monitor[/bold white]",
        border_style="bright_white",
    )


class SensorDisplay:
    def __init__(self, refresh_per_second: float = 4.0) -> None:
        self._console = Console()
        self._live    = Live(console=self._console,
                            refresh_per_second=refresh_per_second,
                            screen=True)

    def __enter__(self):
        self._live.__enter__()
        return self

    def __exit__(self, *args):
        self._live.__exit__(*args)

    def update(self, state: IsolationSensorState) -> None:
        self._live.update(build_layout(state))
