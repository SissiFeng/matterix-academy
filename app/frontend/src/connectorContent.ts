export const connectorCommit = "2a9c3004400325d7816c80065a2282a4ad6b5b70";
export const connectorExcerpts = [
  {
    id: "request",
    path: "src/unitelabs/opentrons_flex/features/motion_control.py",
    start: 355,
    end: 364,
    code: "    @sila.ObservableCommand(errors=_LIQUID_ERRORS)\n    async def aspirate(\n        self,\n        mount: Mount,\n        volume: _LiquidVolume,\n        rate: _FlowRateMultiplier,\n        *,\n        status: sila.Status,\n        intermediate: sila.Intermediate[OperationProgress],\n    ) -> None:",
    url: "https://github.com/AccelerationConsortium/opentrons-flex/blob/2a9c3004400325d7816c80065a2282a4ad6b5b70/src/unitelabs/opentrons_flex/features/motion_control.py#L355-L364",
  },
  {
    id: "progress",
    path: "src/unitelabs/opentrons_flex/features/motion_control.py",
    start: 376,
    end: 382,
    code: '        report_progress(status, intermediate, 0.0, OperationPhase.STARTING, f"Starting {mount.value} aspiration.")\n        try:\n            await self._controller.aspirate(_ot3_mount(mount), volume=volume, rate=rate)\n        except asyncio.CancelledError:\n            report_progress(status, intermediate, 1.0, OperationPhase.CANCELLED, f"{mount.value} aspiration cancelled.")\n            raise\n        report_progress(status, intermediate, 1.0, OperationPhase.COMPLETED, f"{mount.value} aspiration completed.")',
    url: "https://github.com/AccelerationConsortium/opentrons-flex/blob/2a9c3004400325d7816c80065a2282a4ad6b5b70/src/unitelabs/opentrons_flex/features/motion_control.py#L376-L382",
  },
  {
    id: "controller",
    path: "src/unitelabs/opentrons_flex/io/flex_motion.py",
    start: 399,
    end: 408,
    code: '    @translate_liquid_errors\n    async def aspirate(self, mount: OT3Mount, volume: float, rate: float = 1.0) -> None:\n        """Aspirate an explicit ``volume`` in µL on ``mount``."""\n        async with self._lock:\n            self._assert_operation_ready()\n            self._assert_liquid_action_ready(mount, volume=volume, aspirating=True)\n            async with self._active_operation() as generation:\n                await self._api.aspirate(mount=mount, volume=volume, rate=rate)\n                self._assert_operation_generation(generation)\n                self._assert_machine_ok()',
    url: "https://github.com/AccelerationConsortium/opentrons-flex/blob/2a9c3004400325d7816c80065a2282a4ad6b5b70/src/unitelabs/opentrons_flex/io/flex_motion.py#L399-L408",
  },
  {
    id: "authority",
    path: "src/unitelabs/opentrons_flex/io/run_authority.py",
    start: 69,
    end: 78,
    code: '    def assert_direct_control_allowed(self) -> None:\n        """Reject uncoordinated SiLA hardware control while PE owns the Flex."""\n        state = self.current()\n        if state.owns_hardware:\n            message = (\n                f"Protocol Engine run {state.run_id} owns the Flex in state {state.status!r}. "\n                "Stop that run, or use a controlled UNITELABS mutation checkpoint; "\n                "independent SiLA actuation is disabled."\n            )\n            raise RunOwnershipError(message)',
    url: "https://github.com/AccelerationConsortium/opentrons-flex/blob/2a9c3004400325d7816c80065a2282a4ad6b5b70/src/unitelabs/opentrons_flex/io/run_authority.py#L69-L78",
  },
  {
    id: "backend",
    path: "src/unitelabs/opentrons_flex/__init__.py",
    start: 420,
    end: 428,
    code: '    if config.use_simulator:\n        log.info("Building OT3API simulator backend")\n        api = await OT3API.build_hardware_simulator(\n            attached_instruments=_simulator_attached_instruments(config),\n            attached_modules=_simulator_attached_modules(config),\n        )\n    else:\n        log.info("Building OT3API for real Flex hardware (CAN)")\n        api = await OT3API.build_hardware_controller()',
    url: "https://github.com/AccelerationConsortium/opentrons-flex/blob/2a9c3004400325d7816c80065a2282a4ad6b5b70/src/unitelabs/opentrons_flex/__init__.py#L420-L428",
  },
] as const;

export type ExcerptId = (typeof connectorExcerpts)[number]["id"];
export type LessonStep = { actor: string; message: string; packet: string };
export type ConnectorModule = {
  id: ExcerptId;
  title: string;
  subtitle: string;
  scenario: string;
  takeaway: string;
  steps: LessonStep[];
  translation: string[];
  terms: { term: string; definition: string }[];
  question: string;
  answers: string[];
  correct: number;
  explanation: string;
};

export const connectorModules: ConnectorModule[] = [
  {
    id: "request",
    title: "Ask for an action",
    subtitle: "From a laboratory intention to a software request",
    scenario:
      "You want the left pipette to aspirate 100 µL. How does another program ask the connector to do it?",
    takeaway:
      "An action needs explicit parameters and an observable outcome. A moving progress bar alone cannot tell a client what happened.",
    steps: [
      {
        actor: "Student",
        message: "Draw 100 µL into the left pipette, at the normal rate.",
        packet: "Intention: aspirate",
      },
      {
        actor: "Client",
        message:
          "I send the mount, volume and rate through the connector’s API.",
        packet: "mount · volume · rate",
      },
      {
        actor: "SiLA feature",
        message:
          "My observable command declares the inputs, status updates and possible liquid-handling errors.",
        packet: "ObservableCommand",
      },
      {
        actor: "Observer",
        message:
          "I follow the command’s reported state. Accepting a request does not mean its work is complete.",
        packet: "status · intermediate updates",
      },
    ],
    translation: [
      "The decorator marks aspiration as a command whose execution can be observed. It also declares the liquid-handling errors it may report.",
      "The request identifies a pipette mount, a liquid volume and a flow-rate multiplier. These are explicit inputs, rather than a screen coordinate.",
      "The status and intermediate arguments provide the reporting channels. This excerpt is the interface; the execution appears in later modules.",
    ],
    terms: [
      {
        term: "API",
        definition:
          "A defined way for one program to ask another to do something or return information.",
      },
      {
        term: "SiLA",
        definition:
          "A laboratory automation standard that describes device capabilities, commands and their results.",
      },
      {
        term: "Observable command",
        definition:
          "A command whose execution state and intermediate reports can be followed by a client.",
      },
      {
        term: "Decorator",
        definition:
          "A Python annotation above a function that attaches behavior or metadata to it.",
      },
    ],
    question:
      "A client shows a two-second animation after sending Aspirate. What should decide whether the action finished?",
    answers: [
      "The animation reaching its last frame",
      "The command’s reported execution outcome",
      "The client waiting longer than usual",
    ],
    correct: 1,
    explanation:
      "Follow the observable command. Request acceptance and elapsed time do not establish completion, and an operation can fail or be cancelled.",
  },
  {
    id: "controller",
    title: "Follow the controller",
    subtitle: "One action, several responsibilities",
    scenario:
      "The request has arrived. Before the robot acts, which part coordinates access and checks whether aspiration is ready?",
    takeaway:
      "The feature speaks the client’s language. The controller coordinates the action and delegates to the shared Opentrons API.",
    steps: [
      {
        actor: "Feature",
        message: "I pass the aspiration request to FlexMotionController.",
        packet: "aspirate(mount, volume, rate)",
      },
      {
        actor: "Controller",
        message:
          "I enter the shared lock so another coordinated operation cannot overlap this one.",
        packet: "async with self._lock",
      },
      {
        actor: "Readiness checks",
        message:
          "I check operation and liquid-action readiness before the API call, then check the operation generation and machine state afterward.",
        packet: "ready → act → verify state",
      },
      {
        actor: "OT3API",
        message:
          "The controller awaits my aspiration call. The configured backend determines how that call is performed.",
        packet: "await self._api.aspirate(...)",
      },
    ],
    translation: [
      "The asynchronous function can wait while work is in progress. The liquid-error translator maps failures into the connector’s error vocabulary.",
      "The shared lock surrounds the operation. Inside it, readiness checks run before aspiration and an active-operation context tracks its generation.",
      "OT3API receives the mount, volume and rate. After it returns, the controller checks that the operation generation and machine state remain acceptable.",
    ],
    terms: [
      {
        term: "Controller",
        definition:
          "Code that coordinates an action, including its checks and the call to the device API.",
      },
      {
        term: "Async / await",
        definition:
          "A way for code to wait for an operation without pretending that the operation has already finished.",
      },
      {
        term: "Lock",
        definition:
          "A shared turn-taking mechanism. Coordinated callers must acquire it before entering the protected operation.",
      },
      {
        term: "OT3API",
        definition:
          "The Opentrons hardware-control interface used by this connector for the Flex.",
      },
    ],
    question:
      "Another client wants to move the gantry while aspiration is in progress. What should its implementation do?",
    answers: [
      "Create another controller to bypass the busy one",
      "Send the movement directly to the motors",
      "Use the coordinated path, shared lock and applicable ownership checks",
    ],
    correct: 2,
    explanation:
      "Keep both operations on the coordinated path. A lock prevents overlapping access; a separate ownership policy also matters when Protocol Engine owns a run.",
  },
  {
    id: "authority",
    title: "Who owns the robot?",
    subtitle: "Taking turns is different from having permission",
    scenario:
      "A Protocol Engine run is paused. A second client now asks for an independent SiLA movement. Is an idle moment enough to allow it?",
    takeaway:
      "In connector-pe, a nonterminal Protocol Engine run retains hardware ownership, including when paused. An available lock is not permission to intervene.",
    steps: [
      {
        actor: "Protocol Engine",
        message:
          "My run is paused, but it has not reached a terminal state. I still own the Flex.",
        packet: "nonterminal run owns hardware",
      },
      {
        actor: "Second client",
        message: "I request an independent SiLA action.",
        packet: "direct-control request",
      },
      {
        actor: "Run authority",
        message:
          "I read the current owner. This request cannot independently actuate the robot while that run owns it.",
        packet: "state.owns_hardware",
      },
      {
        actor: "Client response",
        message:
          "A RunOwnershipError explains why control was rejected. This teaching trace sends no real command.",
        packet: "request rejected",
      },
    ],
    translation: [
      "The authority check obtains the current Protocol Engine ownership state.",
      "If a run owns the Flex, the error explains the run identifier, its state and the restriction on independent SiLA actuation.",
      "The function raises RunOwnershipError instead of silently allowing the request. This policy belongs to the connector-pe integration; it is not implied by connector-unit’s lock alone.",
    ],
    terms: [
      {
        term: "Protocol Engine",
        definition:
          "The Opentrons runtime that manages a protocol run and its execution state.",
      },
      {
        term: "Ownership",
        definition:
          "The right to direct the robot for a run, even during moments when no motor is moving.",
      },
      {
        term: "Nonterminal",
        definition:
          "A state in which a run has not ended. Pausing does not by itself end the run.",
      },
      {
        term: "connector-pe",
        definition:
          "The connector mode that integrates an embedded Opentrons server and Protocol Engine with SiLA access.",
      },
      {
        term: "connector-unit",
        definition:
          "The standalone connector mode without that embedded robot server. Its lock alone does not establish Protocol Engine ownership checks.",
      },
    ],
    question:
      "A paused Protocol Engine run still owns the Flex. What happens to an independent SiLA actuation request in connector-pe?",
    answers: [
      "It stays blocked by the ownership policy",
      "It is allowed because the robot is motionless",
      "It becomes safe if a new lock is created",
    ],
    correct: 0,
    explanation:
      "Paused is still nonterminal. The run retains ownership, so independent actuation is rejected; a free lock or a motionless robot does not change that authority.",
  },
  {
    id: "progress",
    title: "Read the result",
    subtitle: "Software outcomes and experimental evidence",
    scenario:
      "The command reports that aspiration completed. What does this tell you, and what still needs a measurement?",
    takeaway:
      "Completion reports a software action boundary. Establishing transferred volume, composition or scientific success requires the appropriate measurements and validation.",
    steps: [
      {
        actor: "Feature",
        message:
          "I report STARTING before awaiting the controller’s aspiration call.",
        packet: "STARTING · 0.0",
      },
      {
        actor: "Controller",
        message:
          "I execute the coordinated action. Cancellation raises an exception; other failures do not reach the final completion report.",
        packet: "await action outcome",
      },
      {
        actor: "Feature",
        message:
          "If cancellation occurs, I report CANCELLED and re-raise. If the call returns normally, I report COMPLETED.",
        packet: "COMPLETED or CANCELLED",
      },
      {
        actor: "Scientist",
        message:
          "I still need an appropriate measurement to establish actual transferred volume or sample quality.",
        packet: "execution evidence ≠ assay result",
      },
    ],
    translation: [
      "STARTING is reported immediately before the controller call. The 0.0 value marks the beginning of this software operation.",
      "The cancellation branch reports CANCELLED and raises again. The final COMPLETED report is reached only if the awaited call returns normally.",
      "These reports do not show a continuous liquid-volume measurement. The 1.0 value is an operation boundary, including in the cancellation branch.",
    ],
    terms: [
      {
        term: "Cancellation",
        definition:
          "A request to interrupt an operation. It must be reported distinctly from successful completion.",
      },
      {
        term: "Backend",
        definition:
          "The implementation behind an interface. Here, configuration chooses an Opentrons simulator or a real Flex hardware controller.",
      },
      {
        term: "CAN",
        definition:
          "The communication bus used by the real Flex hardware-control backend.",
      },
      {
        term: "Exception",
        definition:
          "A software signal that an operation cannot continue normally, such as an error or cancellation.",
      },
    ],
    question:
      "Aspiration returns COMPLETED using the Opentrons simulator backend. Which conclusion is supported?",
    answers: [
      "The physical sample has exactly the requested volume",
      "The simulated API action completed; physical volume accuracy remains unverified",
      "The same workflow has passed Matterix Isaac validation",
    ],
    correct: 1,
    explanation:
      "The simulator can exercise software behavior. It does not measure physical liquid volume, prove scientific validity, or establish a Matterix Isaac acceptance result.",
  },
];

export const sourceNodes: {
  id: ExcerptId;
  title: string;
  role: string;
  relationship: string;
}[] = [
  {
    id: "request",
    title: "Command interface",
    role: "MotionControlFeature.aspirate",
    relationship:
      "Declares the observable aspiration command, its parameters and reporting channels.",
  },
  {
    id: "controller",
    title: "Coordinated action",
    role: "FlexMotionController.aspirate",
    relationship:
      "Called by the feature. Holds the shared lock, checks readiness and awaits OT3API.aspirate.",
  },
  {
    id: "backend",
    title: "Backend selection",
    role: "Connector initialization",
    relationship:
      "Wires either an OT3API simulator or real hardware controller. This is initialization, not a call made on each aspiration.",
  },
  {
    id: "authority",
    title: "Run ownership",
    role: "ProtocolRunAuthority",
    relationship:
      "A separate connector-pe guard rejects independent control while Protocol Engine owns the Flex. It is not an extra hop in every connector-unit aspiration.",
  },
  {
    id: "progress",
    title: "Execution reports",
    role: "report_progress calls",
    relationship:
      "The feature reports action boundaries around the controller call. These reports do not measure liquid volume.",
  },
];
