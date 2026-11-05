"""Pure, deterministic teaching command contract shared by web and SiLA transports."""


class PlanError(ValueError):
    def __init__(self, layer, message):
        super().__init__(message)
        self.layer = layer


def execute_mock(twins, steps):
    """Same bounded command contract described by the exported SiLA mock."""
    location = None
    vessel = None
    volume = 0.0
    temperature = 20.0
    mixed = False
    elapsed = 0.0
    stock = {
        t["id"]: {c["name"]: c["stock"] for c in t["spec"]["consumables"]}
        for t in twins.values()
        if t["confirmed"]
    }
    trace = []

    def station(device_id, label):
        device = twins.get(device_id)
        if not device or not device["confirmed"] or device["mode"] != "mock":
            raise PlanError("state", f"{label}: select a confirmed mock device")
        return device

    def accepts(device, label):
        container = device["spec"]["container"]
        if "load" not in device["spec"]["operations"]:
            raise PlanError("container", f"{label}: {device['spec']['name']} cannot hold a sample")
        if container["vessel"] != vessel:
            raise PlanError(
                "container",
                f"{label}: {device['spec']['name']} accepts a {container['vessel']}, not a {vessel}",
            )
        if volume > container["max_volume_ul"]:
            raise PlanError(
                "volume",
                f"{label}: {volume:g} µL exceeds {device['spec']['name']}'s {container['max_volume_ul']:g} µL limit",
            )

    for index, step in enumerate(steps):
        label = f"Step {index + 1}"
        actor = station(step["device_id"], label)
        spec = actor["spec"]
        operation = step["operation"]
        if operation not in spec["operations"]:
            raise PlanError("state", f"{label}: {spec['name']} does not support {operation}")
        if operation == "load":
            if location is not None:
                raise PlanError(
                    "state", f"{label}: this workflow tracks one sample; load it only once"
                )
            location, vessel, volume = actor["id"], spec["container"]["vessel"], step["value"]
            accepts(actor, label)
        elif operation == "transfer":
            source = station(step["source_id"], label)
            target = station(step["target_id"], label)
            if location != source["id"]:
                raise PlanError("state", f"{label}: the sample is not at {source['spec']['name']}")
            accepts(target, label)
            location = target["id"]
        elif operation != "wait" and location != actor["id"]:
            raise PlanError("state", f"{label}: transfer the sample to {spec['name']} first")
        limits = spec["limits"]
        if (
            operation == "heat"
            and not limits["min_temp_c"] <= step["value"] <= limits["max_temp_c"]
        ):
            raise PlanError(
                "constraint",
                f"{label}: {spec['name']} heats only {limits['min_temp_c']:g}–{limits['max_temp_c']:g} °C",
            )
        if operation in {"mix", "wait"} and step["value"] > limits["max_duration_s"]:
            raise PlanError(
                "constraint",
                f"{label}: {spec['name']} allows at most {limits['max_duration_s']:g} s",
            )
        for item in spec["consumables"]:
            if item["used_by"] == operation:
                left = stock[actor["id"]][item["name"]] - item["per_use"]
                if left < 0:
                    raise PlanError(
                        "consumable", f"{label}: {spec['name']} has run out of {item['name']}"
                    )
                stock[actor["id"]][item["name"]] = left
        if operation == "mix":
            mixed = True
        if operation == "heat":
            temperature = step["value"]
        elapsed += step["value"] if operation in {"wait", "mix"} else 1
        trace.append(
            {
                "step": index + 1,
                "device_id": actor["id"],
                "operation": operation,
                "location": location,
                "vessel": vessel,
                "volume_ul": volume,
                "temperature_c": temperature,
                "mixed": mixed,
                "elapsed_s": elapsed,
                "consumables": {d: dict(items) for d, items in stock.items() if items},
                "measurement": {
                    "kind": "synthetic_state_readout",
                    "temperature_c": temperature,
                    "volume_ul": volume,
                    "mixed": mixed,
                }
                if operation == "read"
                else None,
            }
        )
    return trace
