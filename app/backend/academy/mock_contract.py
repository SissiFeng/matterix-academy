"""Pure, deterministic teaching command contract shared by web and SiLA transports.

A workflow tracks one or more named samples (plates, tubes, vials). Each one is loaded
once onto a slot of an instrument that can hold it; transfers move it between slots.
Steps without a `sample` act on the single default sample, as before.
"""

DEFAULT_SAMPLE = "sample"


class PlanError(ValueError):
    def __init__(self, layer, message):
        super().__init__(message)
        self.layer = layer


def site_keys(spec):
    """Slot names of an instrument: its drawn sites, else numbered slots."""
    keys = [s["key"] for s in spec.get("sites", [])]
    return keys or [str(i + 1) for i in range(spec["resource"]["slots"])]


def execute_mock(twins, steps):
    """Same bounded command contract described by the exported SiLA mock."""
    samples = {}  # key -> location, site, vessel, volume, temperature, mixed
    occupied = {}  # device id -> {site: sample key}
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

    def accepts(device, sample, label):
        container = device["spec"]["container"]
        if "load" not in device["spec"]["operations"]:
            raise PlanError("container", f"{label}: {device['spec']['name']} cannot hold a sample")
        if container["vessel"] != sample["vessel"]:
            raise PlanError(
                "container",
                f"{label}: {device['spec']['name']} accepts a {container['vessel']}, "
                f"not a {sample['vessel']}",
            )
        if sample["volume"] > container["max_volume_ul"]:
            raise PlanError(
                "volume",
                f"{label}: {sample['volume']:g} µL exceeds {device['spec']['name']}'s "
                f"{container['max_volume_ul']:g} µL limit",
            )

    def seat(device, wanted, key, label):
        """The slot a sample takes on a device: the one asked for, else the first free one."""
        keys = site_keys(device["spec"])
        taken = occupied.setdefault(device["id"], {})
        name = device["spec"]["name"]
        if wanted:
            if wanted not in keys:
                raise PlanError("resource", f"{label}: {name} has no slot {wanted}")
            if wanted in taken:
                raise PlanError(
                    "resource", f"{label}: slot {wanted} on {name} already holds {taken[wanted]}"
                )
            site = wanted
        else:
            site = next((k for k in keys if k not in taken), None)
            if site is None:
                raise PlanError(
                    "resource",
                    f"{label}: {name} has no free slot for {key}; its {len(keys)} "
                    f"slot{'s' if len(keys) != 1 else ''} are in use",
                )
        taken[site] = key
        return site

    for index, step in enumerate(steps):
        label = f"Step {index + 1}"
        actor = station(step["device_id"], label)
        spec = actor["spec"]
        operation = step["operation"]
        key = step.get("sample") or DEFAULT_SAMPLE
        if operation not in spec["operations"]:
            raise PlanError("state", f"{label}: {spec['name']} does not support {operation}")
        sample = samples.get(key)
        source_site = None
        if operation == "load":
            if sample is not None:
                raise PlanError(
                    "state",
                    f"{label}: this workflow tracks one sample; load it only once"
                    if key == DEFAULT_SAMPLE
                    else f"{label}: {key} is already loaded; load each sample once",
                )
            sample = {
                "location": actor["id"],
                "site": None,
                "vessel": spec["container"]["vessel"],
                "volume": step["value"],
                "temperature": 20.0,
                "mixed": False,
            }
            accepts(actor, sample, label)
            sample["site"] = seat(actor, step.get("site"), key, label)
            samples[key] = sample
        elif operation == "transfer":
            source = station(step["source_id"], label)
            target = station(step["target_id"], label)
            if sample is None or sample["location"] != source["id"]:
                what = "the sample" if key == DEFAULT_SAMPLE else key
                raise PlanError("state", f"{label}: {what} is not at {source['spec']['name']}")
            if step.get("source_site") and step["source_site"] != sample["site"]:
                raise PlanError(
                    "resource",
                    f"{label}: {key} is in slot {sample['site']} of {source['spec']['name']}, "
                    f"not slot {step['source_site']}",
                )
            accepts(target, sample, label)
            source_site = sample["site"]
            occupied[source["id"]].pop(source_site)
            sample["site"] = seat(target, step.get("target_site"), key, label)
            sample["location"] = target["id"]
        elif operation != "wait" and (sample is None or sample["location"] != actor["id"]):
            what = "the sample" if key == DEFAULT_SAMPLE else key
            raise PlanError("state", f"{label}: transfer {what} to {spec['name']} first")
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
            sample["mixed"] = True
        if operation == "heat":
            sample["temperature"] = step["value"]
        elapsed += step["value"] if operation in {"wait", "mix"} else 1
        state = sample or {
            "location": None,
            "site": None,
            "vessel": None,
            "volume": 0.0,
            "temperature": 20.0,
            "mixed": False,
        }
        trace.append(
            {
                "step": index + 1,
                "device_id": actor["id"],
                "operation": operation,
                "sample": key,
                "location": state["location"],
                "site": state["site"],
                "source_site": source_site,
                "vessel": state["vessel"],
                "volume_ul": state["volume"],
                "temperature_c": state["temperature"],
                "mixed": state["mixed"],
                "elapsed_s": elapsed,
                "consumables": {d: dict(items) for d, items in stock.items() if items},
                "samples": {
                    k: {
                        "location": s["location"],
                        "site": s["site"],
                        "volume_ul": s["volume"],
                        "temperature_c": s["temperature"],
                        "mixed": s["mixed"],
                    }
                    for k, s in samples.items()
                },
                "measurement": {
                    "kind": "synthetic_state_readout",
                    "temperature_c": state["temperature"],
                    "volume_ul": state["volume"],
                    "mixed": state["mixed"],
                }
                if operation == "read"
                else None,
            }
        )
    return trace


def transfer_sites(twins, steps):
    """Source and target slot of every transfer, keyed by step number."""
    out = {}
    for entry in execute_mock(twins, steps):
        if entry["operation"] == "transfer":
            out[entry["step"]] = (entry["source_site"], entry["site"])
    return out
