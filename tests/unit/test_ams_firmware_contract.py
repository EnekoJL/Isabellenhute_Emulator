"""Contract with the AMS firmware decoder.

The AMS firmware (repo AMS_GitHub, Core/Src/Algorithms/AMS_ivt_parser.c) tests
decode exactly these bytes (test/test_AMS_ivt_parser.c, test/test_AMS_CAN_Task.c).
If this file and those tests both pass, emulator and firmware agree on the wire:
ID 0x521, DLC 6, DB0 mux, DB1 = state << 4 | counter, DB2..5 int32 big endian, mA.
"""

from __future__ import annotations

from isascale.domain import ivt_protocol as proto
from isascale.domain.models import ResultState


def _frame(current_ma: int, counter: int, state: ResultState = ResultState.NONE) -> tuple[int, bytes]:
    frame = proto.current_frame(current_ma, counter, state)
    return frame.arbitration_id, bytes(frame.data)


def test_current_result_id_and_dlc_match_the_firmware_filter():
    can_id, data = _frame(0, 0)
    assert can_id == 0x521
    assert len(data) == 6


def test_positive_current_golden_frame():
    # firmware: 00 04 00 01 E2 40 -> counter 4, 123456 mA
    assert _frame(123456, 4) == (0x521, bytes.fromhex("00040001E240"))


def test_negative_current_with_overcurrent_golden_frame():
    # firmware: 00 17 FF FF FF 9C -> state OCS, counter 7, -100 mA
    assert _frame(-100, 7, ResultState.OCS) == (0x521, bytes.fromhex("0017FFFFFF9C"))


def test_every_state_bit_lands_in_the_high_nibble():
    # firmware CAN_IVT_STATE_* = 0x1 OCS, 0x2 result invalid, 0x4 any meas. error, 0x8 system error
    all_bits = ResultState.OCS | ResultState.OUT_OF_RANGE | ResultState.ANY_MEASUREMENT_ERROR | ResultState.SYSTEM_ERROR
    assert _frame(0, 0, all_bits)[1][1] == 0xF0
