import { connectorCommit } from "./connectorContent";
import { developmentSources } from "./connectorDevelopmentSources";
export type DevelopmentSourceId = (typeof developmentSources)[number]["id"];
export const sourceUrl = (path: string) =>
  `https://github.com/AccelerationConsortium/opentrons-flex/blob/${connectorCommit}/${path}`;
export type Mapping = {
  id: string;
  title: string;
  category: string;
  native: string;
  wrapper: string;
  feature: string;
  lesson: string;
  fields: {
    label: string;
    native: string;
    adapter: string;
    contract: string;
    why: string;
  }[];
  sources: { id: DevelopmentSourceId; label: string }[];
  question: string;
  options: string[];
  correct: number;
  explanation: string;
};
export const mappings: Mapping[] = [
  {
    id: "aspirate",
    title: "Aspirate liquid",
    category: "Parameters & units",
    native: "OT3API.aspirate()",
    wrapper: "FlexMotionController.aspirate()",
    feature: "MotionController.Aspirate",
    lesson:
      "The client-facing contract names the action and its inputs. The adapter preserves their meaning while translating types and coordinating access.",
    fields: [
      {
        label: "Mount",
        native: "OT3Mount.LEFT",
        adapter:
          "_ot3_mount(mount) converts the feature enum to the vendor enum.",
        contract: "Mount.LEFT",
        why: "A common-looking string is not automatically the right backend type. Translate at a defined boundary.",
      },
      {
        label: "Volume",
        native: "volume=100 (µL)",
        adapter:
          "Pass the volume through; check liquid-action readiness and available capacity.",
        contract: "volume: _LiquidVolume > 0, with µL metadata",
        why: "The unit is preserved here. Declaring a positive volume does not establish that every attached pipette can handle it.",
      },
      {
        label: "Rate",
        native: "rate=1.0",
        adapter:
          "Pass the multiplier through without treating it as an absolute flow rate.",
        contract: "rate: _FlowRateMultiplier > 0; dimensionless",
        why: "In this connector, 1.0 is a multiplier of the configured rate. It is not 1 µL/s.",
      },
      {
        label: "Outcome",
        native: "Await aspiration; an exception can interrupt it.",
        adapter:
          "Check operation generation and machine state after the API returns.",
        contract:
          "Observable execution + STARTING / COMPLETED / CANCELLED reports",
        why: "Completion describes this command. Physical liquid-volume accuracy needs separate evidence.",
      },
    ],
    sources: [
      { id: "mount", label: "Enum translation" },
      { id: "units", label: "Units and constraints" },
    ],
    question: "The client supplies rate = 2. What does this contract mean?",
    options: [
      "An absolute rate of 2 µL/s",
      "A multiplier of 2 on the configured rate",
      "A two-second operation",
    ],
    correct: 1,
    explanation:
      "The declared rate is dimensionless. An adapter must preserve that meaning and document any conversion.",
  },
  {
    id: "move",
    title: "Move to a position",
    category: "Shape & defaults",
    native: "OT3API.move_to() + gantry_position()",
    wrapper: "FlexMotionController.move_to()",
    feature: "MotionController.MoveTo",
    lesson:
      "A feature can reshape parameters and combine an action with a readback. This mapping includes a documented default, not just a renamed function.",
    fields: [
      {
        label: "Coordinates",
        native: "abs_position=Point(x, y, z)",
        adapter: "Build Point(x=x, y=y, z=z) from three typed inputs.",
        contract: "x, y, z in millimetres",
        why: "A deck coordinate is not a well name. A higher-level workflow must resolve labware geometry before asking for motion.",
      },
      {
        label: "Default speed",
        native: "speed=None selects the hardware default.",
        adapter: "speed if speed > 0 else None",
        contract: "speed in mm/s; 0 means use the default",
        why: "A zero in the feature contract has an explicit meaning; passing it through blindly would change the request.",
      },
      {
        label: "Position result",
        native: "gantry_position(mount, refresh=True) returns a Point.",
        adapter:
          "Read position after movement and convert the Point to Position.",
        contract: "Position with x, y, z fields in mm",
        why: "The result is a reported position. It does not by itself prove that the intended sample was moved or processed.",
      },
    ],
    sources: [
      { id: "move", label: "Feature conversion" },
      { id: "move_io", label: "Vendor call and readback" },
    ],
    question:
      "A user selects speed = 0 in this Feature. What must the adapter do?",
    options: [
      "Send a zero speed unmodified",
      "Translate it to the vendor default representation",
      "Reject every zero as invalid",
    ],
    correct: 1,
    explanation:
      "The source maps 0 to None. Defaults belong in the contract and need a test just like units.",
  },
  {
    id: "temperature",
    title: "Set a temperature",
    category: "Completion semantics",
    native: "start_set_temperature() or driver.set_temperature()",
    wrapper: "TemperatureModuleController",
    feature: "TemperatureController.SetTemperature / SetTemperatureAndWait",
    lesson:
      "Two commands can use the same native target-setting call but promise different outcomes. Define what completion means before writing the wrapper.",
    fields: [
      {
        label: "Accept a target",
        native: "Send the target to the selected module or driver backend.",
        adapter: "set_temperature() returns after accepting the target.",
        contract: "SetTemperature reports target acceptance.",
        why: "The command may finish while the module is still heating or cooling.",
      },
      {
        label: "Wait for target",
        native: "Set a target, then inspect backend temperature/state.",
        adapter:
          "set_temperature_and_wait() also waits for its target condition.",
        contract: "SetTemperatureAndWait waits for the controller condition.",
        why: "The in-process backend checks target ownership and holding state; the standalone driver path uses a temperature tolerance. Neither proves sample equilibration.",
      },
      {
        label: "Cancel the wait",
        native: "Device heating can continue independently of a Python wait.",
        adapter: "The Feature catches cancellation and calls deactivate().",
        contract:
          "Cancellation has an explicit cleanup path in this implementation.",
        why: "Cancelling a software task is not automatically a physical stop. Define and verify the cleanup for each command.",
      },
    ],
    sources: [
      { id: "target_io", label: "Backend selection and wait" },
      { id: "target_feature", label: "Acceptance command" },
      { id: "wait_feature", label: "Wait and cancellation" },
    ],
    question:
      "SetTemperature completes while the module is heating. Is that necessarily a failure?",
    options: [
      "Yes, every completed command means the target is reached",
      "No, this command promises target acceptance; use the wait command for the controller target condition",
    ],
    correct: 1,
    explanation:
      "Read the command contract. A completed request can mean accepted, reached, or measured depending on the operation; those meanings must be explicit.",
  },
  {
    id: "status",
    title: "Read changing state",
    category: "Observable Property",
    native: "TemperatureModuleState",
    wrapper: "_status() + stream_changes()",
    feature: "TemperatureController.Status",
    lesson:
      "Properties describe state; commands request actions. This connector reshapes backend state before exposing an observable property to subscribers.",
    fields: [
      {
        label: "Missing target",
        native: "target_temperature = None",
        adapter:
          "Represent absence as target_active=false and a numeric placeholder of 0.0.",
        contract: "target_temperature plus target_active",
        why: "Read both fields. A placeholder of zero does not mean the module was commanded to 0 °C.",
      },
      {
        label: "Changing state",
        native: "Controller state changes over time.",
        adapter: "stream_changes reads the mapped state and emits changes.",
        contract: "ObservableProperty implemented by subscribe_status()",
        why: "An observable property is a subscription to reported state, not a command that starts temperature control.",
      },
    ],
    sources: [
      { id: "status_shape", label: "State transformation" },
      { id: "status_property", label: "Property subscription" },
    ],
    question:
      "A reading has target_temperature = 0 and target_active = false. How should a client interpret it?",
    options: [
      "The module is cooling to 0 °C",
      "There is no active target; zero is a placeholder",
    ],
    correct: 1,
    explanation:
      "The boolean carries the missing-value meaning. A typed numeric field alone would lose this information.",
  },
  {
    id: "transfer",
    title: "Compose an operation",
    category: "One command, several calls",
    native: "Move, aspirate, retract and dispense operations",
    wrapper: "FlexLiquidHandlingController.transfer()",
    feature: "LiquidHandlingController.Transfer",
    lesson:
      "A useful lab capability can span multiple native calls. Keep its sequencing and coordination in one controller operation.",
    fields: [
      {
        label: "Input structure",
        native: "Point objects and a LiquidTransferProfile",
        adapter:
          "Translate source, retract and destination coordinates plus the profile.",
        contract: "Typed positions, volume and TransferProfile",
        why: "The interface expresses the full operation. A method name alone cannot supply the motion or liquid-handling assumptions.",
      },
      {
        label: "Operation boundary",
        native: "Several motion and pipetting calls",
        adapter:
          "Validate the profile and positions, then execute under the shared operation lock.",
        contract: "One observable Transfer command",
        why: "Atomic here describes coordinated access. It does not mean a partially completed physical transfer can be rolled back.",
      },
    ],
    sources: [
      { id: "transfer_feature", label: "Feature delegates the operation" },
      { id: "transfer_lock", label: "Validation and operation scope" },
    ],
    question:
      "A transfer fails after aspiration. Does one SiLA command imply that the physical changes were rolled back?",
    options: [
      "Yes, a command is automatically a transaction",
      "No; report the partial state and use an explicit recovery procedure",
    ],
    correct: 1,
    explanation:
      "A shared lock prevents overlapping coordinated operations. It cannot undo liquid movement.",
  },
  {
    id: "errors",
    title: "Translate a failure",
    category: "Defined Execution Errors",
    native: "Vendor communication and operation exceptions",
    wrapper: "translate_module_errors()",
    feature: "Declared module errors on the Feature",
    lesson:
      "Keep failures meaningful for the client. A rejected operation and a device that did not respond should not collapse into a generic success flag.",
    fields: [
      {
        label: "Operation rejected",
        native: "FailedCommand",
        adapter: "Raise ModuleOperationError and preserve the device message.",
        contract: "ModuleOperationError is included in COMMON_MODULE_ERRORS.",
        why: "The device responded but rejected the operation. The original message helps explain recovery.",
      },
      {
        label: "No response",
        native: "SerialException or AbsorbanceReaderDisconnectedError",
        adapter: "Raise ModuleNotRespondingError.",
        contract: "ModuleNotRespondingError is declared on module features.",
        why: "A communication failure can leave the outcome uncertain. Retrying an action blindly can duplicate it.",
      },
      {
        label: "Unmapped failure",
        native: "An exception outside the translated classes",
        adapter: "It is not caught by these branches.",
        contract:
          "Do not claim that every backend failure has a defined mapping.",
        why: "The pinned source documents a coverage gap. Discovering it is part of adapter testing, not a reason to report success.",
      },
    ],
    sources: [{ id: "errors", label: "Exception translation" }],
    question:
      "A native request times out after it might have moved the robot. What should a wrapper do?",
    options: [
      "Immediately repeat the action until one reply succeeds",
      "Report uncertainty and reconcile observed state before deciding whether a retry is appropriate",
    ],
    correct: 1,
    explanation:
      "A missing response is not proof that nothing happened. Recovery needs device-specific evidence and ownership.",
  },
];

export const developmentSteps = [
  {
    title: "Inspect the native interface",
    question: "What can the device actually do, and how do you reach it?",
    artifact: "Capability inventory",
    items: [
      "Record the SDK/API version, operating system, connection method and device identity.",
      "List callable operations, arguments, units, return values, error types and stop behavior.",
      "Establish a minimal read-only connection before commissioning movement.",
    ],
    path: "src/unitelabs/opentrons_flex/__init__.py",
    anchor: "420",
    evidence:
      "The Flex application chooses an OT3API backend at startup. This is the low-level hardware API, not the Python Protocol API.",
    check:
      "A documented call and a known backend; no invented endpoint or unsupported capability.",
  },
  {
    title: "Design the Feature contract",
    question: "What should another lab program be able to ask for?",
    artifact: "Feature and capability mapping",
    items: [
      "Group related lab capabilities into Features; check for a suitable existing standard Feature first.",
      "Choose Command or Property, parameter types and units, and observable behavior.",
      "Define what success, cancellation and failure mean before writing the adapter.",
    ],
    path: "src/unitelabs/opentrons_flex/features/motion_control.py",
    anchor: "142",
    evidence:
      "MotionController declares its identity and typed commands. A custom SiLA Feature still needs agreed semantics to be interchangeable with another device.",
    check:
      "A client can understand the request and outcome without knowing the vendor SDK.",
  },
  {
    title: "Build the adapter",
    question: "Where do vendor-specific details belong?",
    artifact: "Controller / I/O implementation",
    items: [
      "Convert types, units and defaults at an explicit boundary.",
      "Coordinate device ownership, concurrency and deadlines; define ambiguous-result recovery.",
      "Translate known failures and preserve useful device details.",
    ],
    path: "src/unitelabs/opentrons_flex/io/flex_motion.py",
    anchor: "399",
    evidence:
      "FlexMotionController checks readiness, holds the shared lock and awaits OT3API. Module controllers may support more than one backend.",
    check: "A failed or cancelled operation cannot silently become success.",
  },
  {
    title: "Expose and wire the Feature",
    question: "How does the client reach the adapter?",
    artifact: "Registered Feature with status and results",
    items: [
      "Declare the command/property schema and the defined errors.",
      "Delegate to the controller; map result structures and report meaningful state changes.",
      "Register the Feature with the connector and share the intended hardware owner.",
    ],
    path: "src/unitelabs/opentrons_flex/features/temperature.py",
    anchor: "87",
    evidence:
      "The temperature Feature delegates to its controller and distinguishes accepting a target from waiting for it.",
    check:
      "Reported completion matches the promise made in the Feature contract.",
  },
  {
    title: "Test the complete contract",
    question: "Does the wrapper preserve behavior across the boundary?",
    artifact: "Offline adapter and SiLA client tests",
    items: [
      "Test normal inputs, limits, enum/unit mapping, defaults and response shapes.",
      "Exercise exceptions, cancellation, timeouts, concurrent calls and partial completion.",
      "Test with a SiLA client as well as direct controller calls; keep mock and simulator evidence distinct.",
    ],
    path: "tests/integration/test_grpc_temperature_module.py",
    anchor: "1",
    evidence:
      "The repository contains I/O, Feature and gRPC integration tests. A linked test is source evidence, not a claim that it passed on your device.",
    check:
      "Failures are visible to the actual client, not only to a Python unit test.",
  },
  {
    title: "Commission and hand over",
    question: "What proves this installation is usable on the real instrument?",
    artifact: "Versioned acceptance record and recovery guide",
    items: [
      "Verify the physical configuration, calibration and permitted operating envelope.",
      "Exercise representative actions, observed postconditions and stop/recovery behavior on the target device.",
      "Record versions, configuration, evidence, limitations and who owns recovery.",
    ],
    path: "tests/integration/hardware/test_hitl_temperature_module.py",
    anchor: "1",
    evidence:
      "Hardware tests are a separate layer. Clicking through this tutorial neither runs them nor commissions a connector.",
    check:
      "A reproducible acceptance record for the actual device and installation.",
  },
] as const;
