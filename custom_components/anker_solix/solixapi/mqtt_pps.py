"""MQTT device control methods for Anker Solix Portable Power Stations.

This module contains control methods specific to portable power stations (PPS).
These methods provide comprehensive device control via MQTT commands.
"""

from __future__ import annotations  # noqa: TID251

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .mqtt_device import SolixMqttDevice
from .mqttcmdmap import SolixMqttCommands

if TYPE_CHECKING:
    from .api import AnkerSolixApi

# Define supported Models for this class
MODELS = {
    "A1722",  # SOLIX C300 AC
    "A1723",  # SOLIX C300X AC
    "A1725",  # SOLIX C200(X)
    "A1726",  # SOLIX C300 DC
    "A1727",  # SOLIX C200 DC
    "A1728",  # SOLIX C300X DC
    "A1729",  # SOLIX C200X DC
    "A1753",  # SOLIX C800
    "A1754",  # SOLIX C800 Plus
    "A1755",  # SOLIX C800X
    "A1761",  # SOLIX C1000(X)
    "A1762",  # Portable Power Station 1000
    "A1763",  # SOLIX C1000 Gen 2
    "A1765",  # SOLIX C1000X Gen 2
    "A1770",  # F1200 (Bluetooth)
    "A1771",  # F1200 (Bluetooth and WLAN)
    "A1772",  # SOLIX F1500
    "A1780",  # 767 PowerHouse (SOLIX F2000)
    "A1780P",  # 767 Power House (SOLIX F2000) with WLAN
    "A1781",  # SOLIX F2600
    "A1782",  # SOLIX F3000 Solarbank PPS
    "A1783",  # SOLIX C2000 Gen 2
    "A1785",  # SOLIX C2000X Gen 2
    "A1790",  # SOLIX F3800 Power Panel PPS
    "A1790P",  # SOLIX F3800 Plus Power Panel PPS
    "AS220",  # SOLIX S2000
}

# Define possible controls per Model
# Those commands are only supported once also described for a message type in the model mapping (except realtime trigger)
# Models can be removed from a feature to block command usage even if message type is described in the mapping
FEATURES = {
    SolixMqttCommands.status_request: MODELS,
    SolixMqttCommands.realtime_trigger: MODELS,
    SolixMqttCommands.temp_unit_switch: MODELS,
    SolixMqttCommands.device_max_load: MODELS,
    SolixMqttCommands.device_timeout_minutes: MODELS,
    SolixMqttCommands.ac_charge_limit: MODELS,
    SolixMqttCommands.ac_output_switch: MODELS,
    SolixMqttCommands.ac_fast_charge_switch: MODELS,
    SolixMqttCommands.ac_output_mode_select: MODELS,
    SolixMqttCommands.ac_output_timeout_seconds: MODELS,
    SolixMqttCommands.ac_output_timeout_minutes: MODELS,
    SolixMqttCommands.ac_output_timer: MODELS,
    SolixMqttCommands.dc_output_switch: MODELS,
    SolixMqttCommands.dc_12v_output_mode_select: MODELS,
    SolixMqttCommands.dc_output_timeout_seconds: MODELS,
    SolixMqttCommands.energy_saving_switch: MODELS,
    SolixMqttCommands.display_switch: MODELS,
    SolixMqttCommands.display_mode_select: MODELS,
    SolixMqttCommands.display_timeout_seconds: MODELS,
    SolixMqttCommands.light_switch: MODELS,
    SolixMqttCommands.light_mode_select: MODELS,
    SolixMqttCommands.port_memory_switch: MODELS,
    SolixMqttCommands.soc_limits: MODELS,
    SolixMqttCommands.pps_usage_mode: MODELS,
    SolixMqttCommands.silent_schedule: MODELS,
    # SolixMqttCommands.pps_custom_schedule: MODELS,  # TODO: Enable once fully supported
    SolixMqttCommands.pps_tou_schedule: MODELS,
    # SolixMqttCommands.pps_output_schedule: MODELS,  # TODO: Enable once fully supported
    SolixMqttCommands.backup_soc: MODELS,
    SolixMqttCommands.backup_charge_storm_guard: MODELS,
    SolixMqttCommands.backup_charge_plan: MODELS,
    SolixMqttCommands.backup_charge_timestamps: MODELS,
}


class SolixMqttDevicePps(SolixMqttDevice):
    """Define the class to handle an Anker Solix MQTT device for PPS controls."""

    def __init__(self, api_instance: AnkerSolixApi, device_sn: str) -> None:
        """Initialize."""
        self.models = MODELS
        self.features = FEATURES
        super().__init__(api_instance=api_instance, device_sn=device_sn)

    def update_device(
        self, device: dict, dynamic_descriptions: dict | None = None
    ) -> None:
        """Define callback for Api device updates."""
        super().update_device(device=device, dynamic_descriptions=dynamic_descriptions)
        # TODO: Call methods to extract actual presets from plans if available

    def update_custom_plan_presets(
        self,
        fromFile: bool = False,
    ) -> dict | None:
        """Update the presets from actual custom plan based on time.

        Args:
            fromFile: If True, consider the mocked cache

        Returns:
            dict: Custom plan presets as updated in mqttdata. None will be returned upon error.

        Example output:
            {"preset_load_mode": 1}

        """

        cache = self.get_status(fromFile=fromFile)
        presets = {}
        schedule = cache.get("custom_mode_schedule") or {}  # noqa: F841
        # TODO: Add code to extract active preset
        return presets

    def update_tou_plan_presets(
        self,
        fromFile: bool = False,
    ) -> dict | None:
        """Update the presets from actual time of use plan based on time.

        The device reports the currently active tariff directly in the 0421
        status (d9[0]: 0=none/UPS, 1=Peak, 2=Mid, 3=Off), so the active TOU
        preset is exposed without recomputing it from the schedule + time.

        Args:
            fromFile: If True, consider the mocked cache

        Returns:
            dict: TOU plan presets as updated in mqttdata. None will be returned upon error.

        Example output:
            {"preset_tariff": 1}

        """
        cache = self.get_status(fromFile=fromFile)
        presets = {}
        # The device reports the currently active tariff directly (0421.d9[0]);
        # expose it as the active TOU preset (0=none, 1=Peak, 2=Mid, 3=Off).
        if (active := cache.get("active_tariff")) is not None:
            presets["preset_tariff"] = int(active)
        return presets

    async def set_backup_charge_plan(
        self,
        backup_start: datetime | float | None = None,
        backup_end: datetime | float | None = None,
        backup_duration: timedelta | None = None,
        backup_switch: bool | None = None,
        toFile: bool = False,  # used for testing with files
    ) -> dict | None:
        """Set PPS manual backup charge parameters. Times will be rounded to minute granularity, and end time must be larger than start time.

        If duration is specified, the start time will be set <= now and the end time will reflect the duration to ensure immediate start for
        given duration if the switch will be enabled. If only the switch is enabled without future backup window, a default immediate duration
        of 1h will be applied.

        Args:
            backup_start: Optional datetime or timestamp to update the manual backup start time.
            backup_end: Optional datetime or timestamp to update the manual backup start time. M
            backup_duration: Set backup window being active from at least now for given duration.
            backup_switch: Enable or disable the manual backup option
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            await mydevice.set_backup_charge_plan(backup_duration=timedelta(hours=2), backup_switch=True)

        """
        # response and commands
        resp = {}
        cmd1 = SolixMqttCommands.backup_charge_timestamps
        parm_map = {}
        # validate parameters
        def_duration = timedelta(hours=1)
        backup_start = (
            backup_start.astimezone()
            if isinstance(backup_start, datetime)
            else datetime.fromtimestamp(round(backup_start / 60) * 60).astimezone()
            if isinstance(backup_start, float | int)
            else None
        )
        backup_end = (
            backup_end.astimezone()
            if isinstance(backup_end, datetime)
            else datetime.fromtimestamp(round(backup_end / 60) * 60).astimezone()
            if isinstance(backup_end, float | int)
            else None
        )
        backup_duration = (
            max(backup_duration, timedelta(minutes=1))
            if isinstance(backup_duration, timedelta)
            else None
        )
        backup_switch = backup_switch if isinstance(backup_switch, bool) else None
        # fast quit if nothing to change
        if (
            backup_start is None
            and backup_end is None
            and backup_duration is None
            and backup_switch is None
        ):
            self._logger.error(
                "No valid AC charge options provided for device %s (%s)",
                self.sn,
                self.pn,
            )
            return False
        # Consider time zone shifts of device, timestamp conversion is absolute and timezone aware
        now = datetime.now().replace(second=0, microsecond=0).astimezone()
        cache = self.get_status(fromFile=toFile)
        if not backup_start:
            backup_start = datetime.fromtimestamp(
                cache.get("backup_start_timestamp") or 0
            ).astimezone()
        if not backup_end:
            backup_end = datetime.fromtimestamp(
                cache.get("backup_end_timestamp") or 0
            ).astimezone()
        if backup_switch is None:
            backup_switch = bool(cache.get("backup_switch"))
        else:
            # switch provided as parameter, first ensure start time is set correctly if backup range will be activated
            if backup_switch:
                backup_start = backup_start or now
                if not cache.get("backup_switch") and (backup_end or now) <= now:
                    # switch will be changed to enabled, ensure start time is at least now if now passed a previous interval
                    backup_start = now
            parm_map["set_backup_option_switch"] = int(backup_switch)
        # make sure backup start and end time are valid and merged with optional parameters before applying them
        if backup_start or backup_end:
            backup_end = max(backup_start or backup_end, backup_end or backup_start)
            backup_start = min(backup_start or backup_end, backup_end or backup_start)
            if backup_start == backup_end or backup_duration:
                backup_end = backup_start + (backup_duration or def_duration)
            parm_map["set_backup_start_timestamp"] = round(backup_start.timestamp() / 60) * 60
            parm_map["set_backup_end_timestamp"] = round(backup_end.timestamp() / 60) * 60
        # Send command if any parameters to update
        if parm_map:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    parm_map=parm_map,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or None

    async def set_tou_schedule(
        self,
        schedule: list[dict] | dict | None = None,
        toFile: bool = False,  # used for testing with files
    ) -> dict | None:
        """Set the PPS time-of-use schedule (list of up to 6 tariff slots).

        Each slot is a dict with keys: tariff (1=Peak, 2=Mid, 3=Off),
        start_time ("HH:MM"), end_time ("HH:MM"). Slots should be contiguous
        and cover the day (00:00-24:00).

        The schedule is applied through two paths so that both the device and
        the Anker app reflect the change:
        1. A full-state MQTT 0090 command (usage mode + backup SOC + schedule),
           sent exactly as the Anker app sends it, updates the device directly.
        2. A commit to the cloud store (the ``pps_use_time`` device attribute)
           updates the authoritative copy the Anker app reads. Without this the
           app would keep showing the previous schedule, since the app does not
           read the device state for the TOU plan.

        The slot count (a6) of the MQTT command is derived automatically from
        the slots.

        Args:
            schedule: List of slot dicts, or a dict with a "ranges" key holding the list.
            toFile: If True, save mock response (for testing compatibility).

        Returns:
            dict: Mocked state if successful, None otherwise.

        Example:
            await mydevice.set_tou_schedule([
                {"tariff": 1, "start_time": "00:00", "end_time": "08:00"},
                {"tariff": 2, "start_time": "08:00", "end_time": "09:00"},
                {"tariff": 3, "start_time": "09:00", "end_time": "24:00"},
            ])

        """
        # normalize input to a list of slot dicts
        if isinstance(schedule, dict):
            ranges = schedule.get("ranges", [])
        elif isinstance(schedule, list):
            ranges = schedule
        else:
            self._logger.error(
                "No valid TOU schedule provided for device %s (%s)", self.sn, self.pn
            )
            return None
        # validate slot count and structure
        if not isinstance(ranges, list) or not (1 <= len(ranges) <= 6):
            self._logger.error(
                "Invalid TOU schedule (need 1-6 slots) for device %s (%s)",
                self.sn,
                self.pn,
            )
            return None
        for slot in ranges:
            if not isinstance(slot, dict) or not all(
                k in slot for k in ("tariff", "start_time", "end_time")
            ):
                self._logger.error(
                    "Invalid TOU slot (need tariff/start_time/end_time) for device %s: %s",
                    self.sn,
                    slot,
                )
                return None
            if slot.get("tariff") not in (1, 2, 3):
                self._logger.error(
                    "Invalid TOU tariff (need 1=Peak, 2=Mid, 3=Off) for device %s: %s",
                    self.sn,
                    slot,
                )
                return None
        # Read the cloud pps_use_time (the authoritative TOU store) once. It is
        # used to commit the new schedule back to the cloud so the Anker app
        # reflects the change (the app reads the TOU plan from the cloud, not the
        # device). Its reserve_power is kept only as a fallback for the 0090
        # backup SOC when the device cache has no value. A read failure must not
        # prevent the device 0090, so on error the commit re-reads the cloud.
        pps: dict | None = None
        try:
            cloud = await self.api.get_device_attributes(
                deviceSn=self.sn, attributes=["pps_use_time"], fromFile=toFile
            )
            raw = ((cloud or {}).get("attributes") or {}).get("pps_use_time")
            if isinstance(raw, str) and raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    pps = parsed
        except Exception:  # noqa: BLE001 - a cloud read failure must not block the 0090
            pps = None
        # Build the full-state 0090 command exactly as the Anker app sends it
        # (usage mode a2, plan id/switch a3/a4, backup SOC a5, slot count a6,
        # schedule a7, unix-seconds timestamp fe). The device merges partial
        # updates, but the cloud only records the TOU schedule when the command
        # carries the full state with an fe timestamp, so read the current usage
        # mode + backup SOC and include them.
        cache = self.get_status(fromFile=toFile)
        parm_map = {
            "set_tou_mode_schedule": {"ranges": ranges},
            "set_tou_slot_count": len(ranges),
        }
        if (usage_mode := cache.get("usage_mode")) is not None:
            parm_map["set_usage_mode"] = int(usage_mode)
        # Backup SOC: preserve the device's current value (from cache) so that
        # setting the TOU schedule does not change the backup SOC. The
        # pps_backup_soc number entity sets the device's backup SOC without
        # committing to the cloud, so the device's value reflects the user's
        # latest choice. Fall back to the cloud's reserve_power only if the
        # device cache has no value.
        backup_soc = cache.get("backup_soc")
        if backup_soc is None and pps is not None:
            rp = pps.get("reserve_power")
            if isinstance(rp, (int, float)) and rp > 0:
                backup_soc = int(rp)
        if backup_soc is not None:
            parm_map["set_backup_soc"] = int(backup_soc)
        if (
            result := await self.run_command(
                cmd=SolixMqttCommands.pps_tou_schedule,
                parm_map=parm_map,
                toFile=toFile,
            )
        ) is None:
            return None
        # Commit the schedule to the cloud store (reusing the already-read pps
        # dict to avoid a second read), so the Anker app reflects the change.
        try:
            committed = await self._commit_tou_to_cloud(
                ranges=ranges, toFile=toFile, base=pps
            )
        except Exception as err:  # noqa: BLE001 - a cloud failure must not block the 0090
            self._logger.warning(
                "Cloud TOU commit failed for device %s (%s): %s (the device was "
                "updated via MQTT, but the Anker app may not reflect the new schedule)",
                self.sn,
                self.pn,
                err,
            )
            return result
        if not isinstance(committed, dict):
            self._logger.warning(
                "Cloud TOU commit failed for device %s (%s): the device was updated "
                "via MQTT, but the Anker app may not reflect the new schedule",
                self.sn,
                self.pn,
            )
        return result

    async def _commit_tou_to_cloud(
        self,
        ranges: list[dict],
        toFile: bool = False,
        base: dict | None = None,
    ) -> dict | None:
        """Commit the TOU schedule to the cloud store (pps_use_time attribute).

        The Anker app reads the PPS TOU schedule from the cloud ``pps_use_time``
        device attribute, not from the device state. A direct MQTT 0090 command
        updates the device but not this cloud store, so the app would keep showing
        the old schedule. This method reads the current ``pps_use_time`` value,
        replaces its ``ranges`` with the provided schedule (preserving ``prices``,
        ``unit`` and ``reserve_power``), and writes it back so both the app and the
        device (via the cloud's 0090 push) reflect the new schedule.

        Args:
            ranges: List of slot dicts with keys tariff (1=Peak, 2=Mid, 3=Off),
                start_time, end_time.
            toFile: If True, use the mocked file cache (testmode).
            base: Optional already-read cloud pps_use_time dict (avoids a second
                read when the caller already fetched it). When None, the cloud
                is read here.

        Returns:
            dict: The updated cloud attributes, or None on failure.

        """
        if base is not None:
            # Use the already-read cloud pps_use_time (a dict)
            pps: dict = dict(base) if isinstance(base, dict) else {}
        else:
            # Read the current cloud pps_use_time (a JSON string)
            attr = await self.api.get_device_attributes(
                deviceSn=self.sn, attributes=["pps_use_time"], fromFile=toFile
            )
            raw = ((attr or {}).get("attributes") or {}).get("pps_use_time")
            pps = {}
            if isinstance(raw, str) and raw:
                try:
                    pps = json.loads(raw)
                except (ValueError, TypeError):
                    pps = {}
            if not isinstance(pps, dict):
                pps = {}
        # Build the cloud ranges (the cloud uses "type" where the schedule uses "tariff")
        pps["ranges"] = [
            {"start_time": s["start_time"], "end_time": s["end_time"], "type": s["tariff"]}
            for s in ranges
        ]
        # Write back, preserving prices / unit / reserve_power
        return await self.api.set_device_attributes(
            deviceSn=self.sn,
            attributes={"pps_use_time": json.dumps(pps, separators=(",", ":"))},
            query_attributes=["pps_use_time"],
            toFile=toFile,
        )

    async def set_ac_output(
        self,
        enabled: bool | None = None,
        mode: int | str | None = None,
        toFile: bool = False,
    ) -> dict | None:
        """Control AC output power via MQTT.

        Args:
            enabled: True to enable AC output, False to disable
            mode: AC output mode - 1=Normal, 0=Smart
                Can also be string: "normal", "smart"
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            await mydevice.set_ac_output(enabled=True)
            await mydevice.set_ac_output(mode=1)  # Normal
            await mydevice.set_ac_output(mode="smart")

        """
        # response and commands
        resp = {}
        cmd1 = SolixMqttCommands.ac_output_switch
        cmd2 = SolixMqttCommands.ac_output_mode_select
        # First validate all parameters
        if (
            enabled is not None
            and self.validate_cmd_value(cmd=cmd1, value=enabled) is None
        ):
            return None
        if mode is not None and self.validate_cmd_value(cmd=cmd2, value=mode) is None:
            return None
        # Validate and run AC switch enable command
        if enabled is not None:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    value=enabled,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        # Validate and run AC output mode command
        if mode is not None:
            if (
                result := await self.run_command(
                    cmd=cmd2,
                    value=mode,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or None

    async def set_dc_output(
        self,
        enabled: bool | None = None,
        mode: int | str | None = None,
        toFile: bool = False,
    ) -> dict | None:
        """Control DC output power via MQTT.

        Args:
            enabled: True to enable DC output, False to disable
            mode: DC output mode - 1=Normal, 0=Smart
                Can also be string: "normal", "smart"
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            await mydevice.set_dc_output(enabled=True)
            await mydevice.set_dc_output(mode=0)  # Smart
            await mydevice.set_dc_output(mode="normal")

        """
        # response and commands
        resp = {}
        cmd1 = SolixMqttCommands.dc_output_switch
        cmd2 = SolixMqttCommands.dc_12v_output_mode_select
        # First validate all parameters
        if (
            enabled is not None
            and self.validate_cmd_value(cmd=cmd1, value=enabled) is None
        ):
            return None
        if mode is not None and self.validate_cmd_value(cmd=cmd2, value=mode) is None:
            return None
        # Validate and run DC switch enable command
        if enabled is not None:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    value=enabled,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        # Validate and run DC output mode command
        if mode is not None:
            if (
                result := await self.run_command(
                    cmd=cmd2,
                    value=mode,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or False

    async def set_display(
        self,
        enabled: bool | None = None,
        mode: int | str | None = None,
        timeout_seconds: int | None = None,
        toFile: bool = False,
    ) -> dict | None:
        """Control display settings via MQTT.

        Args:
            enabled: True to turn display on, False to turn off
            mode: Display mode - 0=Off, 1=Low, 2=Medium, 3=High
                Can also be string: "off", "low", "medium", "high"
            timeout_seconds: Seconds before display goes off again
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            await mydevice.set_display(enabled=True)
            await mydevice.set_display(mode=2)  # Medium
            await mydevice.set_display(mode="high")
            await mydevice.set_display(timeout_seconds=20)

        """
        # response
        resp = {}
        cmd1 = SolixMqttCommands.display_switch
        cmd2 = SolixMqttCommands.display_mode_select
        cmd3 = SolixMqttCommands.display_timeout_seconds
        # First validate all parameters
        if (
            enabled is not None
            and self.validate_cmd_value(cmd=cmd1, value=enabled) is None
        ):
            return None
        if mode is not None and self.validate_cmd_value(cmd=cmd2, value=mode) is None:
            return None
        if (
            timeout_seconds is not None
            and self.validate_cmd_value(cmd=cmd3, value=timeout_seconds) is None
        ):
            return None
        # Validate and run enable command
        if enabled is not None:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    value=enabled,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        # Validate and run mode command
        if mode is not None:
            if (
                result := await self.run_command(
                    cmd=cmd2,
                    value=mode,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        # Validate and run timeout command
        if timeout_seconds is not None:
            if (
                result := await self.run_command(
                    cmd=cmd3,
                    value=timeout_seconds,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or None

    async def set_backup_charge(
        self,
        enabled: bool | None = None,
        toFile: bool = False,
    ) -> dict | None:
        """Control backup charge / fast charge mode via MQTT.

        Args:
            enabled: True to enable backup charge (Fast Charge) mode, False to disable
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            await mydevice.set_backup_charge(enabled=True)

        """
        # response and commands
        resp = {}
        cmd1 = SolixMqttCommands.ac_fast_charge_switch
        # Validate and run command
        if enabled is not None:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    value=enabled,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or None

    async def set_temp_unit(
        self,
        unit: str | None = None,
        toFile: bool = False,
    ) -> dict | None:
        """Set temperature unit via MQTT.

        Args:
            unit: "fahrenheit" | "celsius"
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            await mydevice.set_temp_unit(unit="celsius")  # Celsius

        """
        # response and commands
        resp = {}
        cmd1 = SolixMqttCommands.temp_unit_switch
        # Validate and run command
        if unit is not None:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    value=unit,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or None

    async def set_light(
        self,
        mode: int | str | None = None,
        toFile: bool = False,
    ) -> dict | None:
        """Set light mode via MQTT.

        Args:
            mode: Light mode - 0=Off, 1=Low, 2=Medium, 3=High, 4=Blinking
                Can also be string: "off", "low", "medium", "high", "blinking"
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            await mydevice.set_light_mode(mode=3)  # High
            await mydevice.set_light_mode(mode="blinking")

        """
        # response and commands
        resp = {}
        cmd1 = SolixMqttCommands.light_mode_select
        # Validate and run command
        if mode is not None:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    value=mode,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or None

    async def set_device_timeout(
        self,
        timeout_minutes: int | None = None,
        toFile: bool = False,
    ) -> dict | None:
        """Set device auto-off timeout.

        Args:
            timeout_minutes: Timeout in minutes (30-1440)
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            # Set 8 hour timeout
            result = await device.set_device_timeout(timeout_minutes=480)

        """
        # response and commands
        resp = {}
        cmd1 = SolixMqttCommands.device_timeout_minutes
        # Validate and run command
        if timeout_minutes is not None:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    value=timeout_minutes,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or None

    async def set_max_load(
        self,
        max_watts: int | None = None,
        toFile: bool = False,
    ) -> dict | None:
        """Set maximum AC output load in Watt.

        Args:
            max_watts: Maximum load in watts
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            # Set 800W max load
            result = await device.set_max_load(max_watts=800)

        """
        # response and commands
        resp = {}
        cmd1 = SolixMqttCommands.device_max_load
        # Validate and run command
        if max_watts is not None:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    value=max_watts,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or None

    async def set_charge_limit(
        self,
        max_watts: int | None = None,
        toFile: bool = False,
    ) -> dict | None:
        """Set maximum AC charge limit in Watt.

        Args:
            max_watts: Maximum load in watts
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            # Set 800W charge limit
            result = await device.set_max_load(max_watts=800)

        """
        # response and commands
        resp = {}
        cmd1 = SolixMqttCommands.ac_charge_limit
        # Validate and run command
        if max_watts is not None:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    value=max_watts,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or None

    async def set_fast_charging(
        self,
        enabled: bool | None = None,
        toFile: bool = False,
    ) -> dict | None:
        """Set Fast charging mode (e.g. 1300W max).

        Args:
            enabled: True to enable Fast charging, False to disable
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            # Enable Fast charging
            result = await device.set_fast_charging(enabled=True)

        """
        # response and commands
        resp = {}
        cmd1 = SolixMqttCommands.ac_fast_charge_switch
        # Validate and run command
        if enabled is not None:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    value=enabled,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or None

    async def set_port_memory(
        self,
        enabled: bool,
        toFile: bool = False,
    ) -> dict | None:
        """Set port memory switch.

        Args:
            enabled: True to enable port memory, False to disable
            toFile: If True, save mock response (for testing compatibility)

        Returns:
            dict: Mocked state if successful, None otherwise

        Example:
            # Enable port memory switch
            result = await device.set_port_memory(enabled=True)

        """
        # response and commands
        resp = {}
        cmd1 = SolixMqttCommands.port_memory_switch
        # Validate and run command
        if enabled is not None:
            if (
                result := await self.run_command(
                    cmd=cmd1,
                    value=enabled,
                    toFile=toFile,
                )
            ) is None:
                return None
            resp.update(result)
        return resp or None
