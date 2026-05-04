import logging

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE

from pycalaos.item import io

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

triggers = {
    io.InputSwitch: {
        True: "click",
        False: "release",
    },
    io.InputSwitchLongPress: {
        io.InputSwitchLongPressState.SHORT: "short_click",
        io.InputSwitchLongPressState.LONG: "long_click",
    },
    io.InputSwitchTriple: {
        io.InputSwitchTripleState.SINGLE: "single_click",
        io.InputSwitchTripleState.DOUBLE: "double_click",
        io.InputSwitchTripleState.TRIPLE: "triple_click",
    },
    io.InputTime: {
        True: "triggered",
    },
}


def all_triggers() -> set[str]:
    triggers_list = set()
    for this_triggers in triggers.values():
        for trigger_string in this_triggers.values():
            triggers_list.add(trigger_string)

    _LOGGER.debug("No-entity triggers: %s", triggers_list)
    return triggers_list


def get_triggers(item_type, device_id: str) -> list[dict[str, str]]:
    if item_type not in triggers:
        return []

    item_triggers = []
    for trigger_string in triggers[item_type].values():
        item_triggers.append(
            {
                CONF_PLATFORM: "device",
                CONF_DOMAIN: DOMAIN,
                CONF_DEVICE_ID: device_id,
                CONF_TYPE: trigger_string,
            }
        )

    _LOGGER.debug("Triggers for %s: %s", item_type, item_triggers)
    return item_triggers


def _normalize_state_candidates(state) -> list:
    candidates = [state]

    state_name = getattr(state, "name", None)
    if state_name is not None:
        candidates.append(state_name)
        candidates.append(state_name.upper())
        candidates.append(state_name.lower())

    state_value = getattr(state, "value", None)
    if state_value is not None:
        candidates.append(state_value)
        if isinstance(state_value, str):
            candidates.append(state_value.upper())
            candidates.append(state_value.lower())

    return candidates


def translate_trigger(event) -> str | None:
    for item_type, item_triggers in triggers.items():
        if not isinstance(event.item, item_type):
            continue

        for candidate in _normalize_state_candidates(event.state):
            if candidate in item_triggers:
                trigger = item_triggers[candidate]
                _LOGGER.debug(
                    "Translated Calaos event for %s: state=%r candidate=%r trigger=%s",
                    type(event.item).__name__,
                    event.state,
                    candidate,
                    trigger,
                )
                return trigger

        if isinstance(event.item, io.InputSwitchTriple):
            normalized_map = {}
            for known_state, trigger in item_triggers.items():
                known_name = getattr(known_state, "name", None)
                known_value = getattr(known_state, "value", None)

                if known_name is not None:
                    normalized_map[known_name.upper()] = trigger
                    normalized_map[known_name.lower()] = trigger
                if known_value is not None and isinstance(known_value, str):
                    normalized_map[known_value.upper()] = trigger
                    normalized_map[known_value.lower()] = trigger

            for candidate in _normalize_state_candidates(event.state):
                if isinstance(candidate, str) and candidate in normalized_map:
                    trigger = normalized_map[candidate]
                    _LOGGER.debug(
                        "Translated Calaos triple-click event using normalized lookup: "
                        "state=%r candidate=%r trigger=%s",
                        event.state,
                        candidate,
                        trigger,
                    )
                    return trigger

        _LOGGER.warning(
            "Unsupported Calaos trigger state for %s: %r",
            type(event.item).__name__,
            event.state,
        )
        return None

    return None
