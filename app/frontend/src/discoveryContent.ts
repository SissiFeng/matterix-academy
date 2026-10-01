export type MethodId =
  | "blend"
  | "dilute"
  | "sequence"
  | "mix"
  | "incubate"
  | "wash"
  | "deposit"
  | "powder";
export type WorkflowId =
  "clio" | "ada" | "sonication" | "rainbow" | "mobile" | "alab";
export type GantryId = "liquid" | "handoff" | "scan" | "tool";
export type Brief = {
  id: string;
  title: string;
  source_id: WorkflowId | null;
  objective: string;
  variables: string;
  measurement: string;
  decision: string;
  controls: string;
  methods: MethodId[];
  gantry: GantryId;
  status: "design_only";
};
export type Notebook = { version: number; briefs: Brief[] };
export type Workflow = {
  id: WorkflowId;
  title: string;
  domain: string;
  year: number;
  authors: string;
  paper: string;
  journal: string;
  doi: string;
  url: string;
  platform: string;
  question: string;
  prepare: string;
  test: string;
  optimize: string;
  adaptation: string;
  external: string;
  prompt: string;
  methods: MethodId[];
  kind: "Closed loop" | "Screening";
  note?: string;
};
export const workflows: Workflow[] = [
  {
    id: "clio",
    title: "Find a better electrolyte",
    domain: "Energy",
    year: 2022,
    authors: "Dave et al.",
    journal: "Nature Communications",
    paper:
      "Autonomous optimization of non-aqueous Li-ion battery electrolytes via robotic experimentation and machine learning coupling",
    doi: "10.1038/s41467-022-32938-1",
    url: "https://www.nature.com/articles/s41467-022-32938-1",
    platform: "Clio liquid-handling platform + Dragonfly",
    question: "Which mixture should we prepare next?",
    prepare: "Blend a salt and three solvents across a composition space.",
    test: "Measure ionic conductivity; battery-cell evaluation is a separate test.",
    optimize:
      "Use Bayesian optimization to select the next electrolyte composition.",
    adaptation:
      "Use a composition grid to learn how a recipe becomes dispense volumes. Flex liquid handling is a candidate preparation step, subject to liquid and labware qualification.",
    external:
      "Conductivity measurement, environmental control and cell testing.",
    prompt:
      "How would you separate a promising measurement from a repeatable improvement?",
    methods: ["blend", "mix"],
    kind: "Closed loop",
  },
  {
    id: "ada",
    title: "From solution to functional film",
    domain: "Thin films",
    year: 2020,
    authors: "MacLeod et al.",
    journal: "Science Advances",
    paper:
      "Self-driving laboratory for accelerated discovery of thin-film materials",
    doi: "10.1126/sciadv.aaz8867",
    url: "https://pmc.ncbi.nlm.nih.gov/articles/PMC7220369/",
    platform: "Ada robotic laboratory",
    question: "How do formulation and processing change a film?",
    prepare:
      "Combine precursor formulations, spin-coat and thermally process films.",
    test: "Combine optical and electrical characterization to assess film performance.",
    optimize:
      "Phoenics proposes new conditions through the ChemOS experiment loop.",
    adaptation:
      "Separate solution preparation from substrate processing. A Flex adaptation could prepare a formulation library, with traceable sample handoffs.",
    external: "Spin coating, annealing and film characterization.",
    prompt:
      "If identical solutions make different films, which processing variables should you record?",
    methods: ["blend", "mix", "deposit"],
    kind: "Closed loop",
  },
  {
    id: "sonication",
    title: "A gantry with another job",
    domain: "Nanomaterials",
    year: 2023,
    authors: "Politi et al.",
    journal: "Digital Discovery",
    paper:
      "A high-throughput workflow for the synthesis of CdSe nanocrystals using a sonochemical materials acceleration platform",
    doi: "10.1039/D3DD00033H",
    url: "https://pubs.rsc.org/en/content/articlelanding/2023/dd/d3dd00033h",
    platform: "OT-2 + Jubilee tool-changing gantry + spectroscopy",
    question: "What changes when motion can position a process tool?",
    prepare:
      "Use liquid handling and a separate ultrasound platform for nanocrystal synthesis.",
    test: "Characterize optical spectra across the prepared sample library.",
    optimize:
      "Screen formulation conditions and analyze their effects; this study is not presented here as an autonomous closed-loop optimizer.",
    adaptation:
      "Study the division of work between liquid handling and a process station. The Jubilee tool changer inspires an engineering concept; it does not establish Flex tool compatibility.",
    external: "Ultrasound equipment and optical characterization.",
    prompt:
      "Would moving the sample or moving the process tool make the handoff easier to validate?",
    methods: ["blend", "sequence", "mix"],
    kind: "Screening",
  },
  {
    id: "rainbow",
    title: "Design light-emitting nanocrystals",
    domain: "Nanomaterials",
    year: 2025,
    authors: "Xu et al.",
    journal: "Nature Communications",
    paper:
      "Autonomous multi-robot synthesis and optimization of metal halide perovskite nanocrystals",
    doi: "10.1038/s41467-025-63209-4",
    url: "https://www.nature.com/articles/s41467-025-63209-4",
    platform: "Rainbow: OT-2, robot arm and plate reader",
    question: "How do you improve two optical properties at once?",
    prepare:
      "Prepare solution-phase nanocrystal formulations using coordinated robots.",
    test: "Collect optical measurements, including emission linewidth and a quantum-yield proxy.",
    optimize:
      "Use multi-objective Bayesian optimization at a target emission energy.",
    adaptation:
      "Plan a plate-based sample library and preserve sample identity through a reader handoff. Moving an OT-2 method to Flex requires fresh qualification.",
    external:
      "Plate reader, sample transport integration and chemical-process qualification.",
    prompt:
      "What would you do if brightness improves while the emission peak becomes broader?",
    methods: ["blend", "sequence", "incubate"],
    kind: "Closed loop",
  },
  {
    id: "mobile",
    title: "Let the sample travel",
    domain: "Catalysis",
    year: 2020,
    authors: "Burger et al.",
    journal: "Nature",
    paper: "A mobile robotic chemist",
    doi: "10.1038/s41586-020-2442-2",
    url: "https://www.nature.com/articles/s41586-020-2442-2",
    platform: "Mobile robot coordinating laboratory stations",
    question: "What if the experiment spans several instruments?",
    prepare:
      "Combine candidate photocatalyst mixtures and carry samples between stations.",
    test: "Evaluate hydrogen production under illumination using gas analysis.",
    optimize: "Select subsequent mixtures through Bayesian search.",
    adaptation:
      "Treat liquid preparation as one station in a wider workflow. Describe each station handoff explicitly; a fixed Flex gantry cannot substitute for a mobile robot.",
    external:
      "Solids handling, illumination, gas analysis and inter-station transport.",
    prompt:
      "Which event proves a sample arrived at the right station with its identity intact?",
    methods: ["blend", "mix", "powder"],
    kind: "Closed loop",
  },
  {
    id: "alab",
    title: "When pipetting is not the answer",
    domain: "Solid-state materials",
    year: 2023,
    authors: "Szymanski et al.",
    journal: "Nature",
    paper:
      "An autonomous laboratory for the accelerated synthesis of inorganic materials",
    doi: "10.1038/s41586-023-06734-w",
    url: "https://www.nature.com/articles/s41586-023-06734-w",
    platform: "A-Lab: powder, furnace and X-ray diffraction stations",
    question: "How does the discovery loop change for powders?",
    prepare: "Dose and mix precursor powders, then heat the samples.",
    test: "Use X-ray diffraction to interpret the resulting phases.",
    optimize:
      "Use literature-informed recipes and active learning to revise synthesis conditions.",
    adaptation:
      "Reuse the sample–measurement–decision structure as a design lesson. Powder dosing and furnace processing are not native Flex pipetting operations.",
    external: "Powder dosing, thermal processing and X-ray diffraction.",
    prompt:
      "Could your experiment be well automated even when no step uses a pipette?",
    methods: ["powder", "incubate"],
    kind: "Closed loop",
    note: "The article has an Author Correction dated 19 January 2026. Consult the updated paper; original success totals are not reproduced here.",
  },
];
export const methods: {
  id: MethodId;
  name: string;
  tag: string;
  description: string;
  consider: string;
}[] = [
  {
    id: "blend",
    name: "Blend a composition library",
    tag: "Liquid-handling candidate",
    description:
      "Vary the ratio of ingredients while holding total volume constant.",
    consider:
      "Define the feasible composition range, mixing order and traceable sample IDs.",
  },
  {
    id: "dilute",
    name: "Build a dilution series",
    tag: "Teaching exercise available",
    description: "Step through concentrations from a known starting solution.",
    consider:
      "Account for carryover, residual volume, tip policy and mixing before the next transfer.",
  },
  {
    id: "sequence",
    name: "Control addition order",
    tag: "Liquid-handling candidate",
    description:
      "Compare A into B with B into A; the same final amounts can have a different history.",
    consider:
      "Record timing and mixing, not just the final recipe. A volume model cannot predict reaction pathways.",
  },
  {
    id: "mix",
    name: "Mix and redisperse",
    tag: "Method qualification needed",
    description:
      "Choose pipette mixing or an appropriate shaking process for the sample.",
    consider:
      "Viscosity, settling, bubbles and dead volume can make a nominal recipe nonuniform.",
  },
  {
    id: "incubate",
    name: "Add time and temperature",
    tag: "Module or external station",
    description:
      "Treat dwell time and thermal history as preparation variables.",
    consider:
      "Specify the instrument, temperature range, equilibration and evaporation control.",
  },
  {
    id: "wash",
    name: "Separate and wash",
    tag: "Separation equipment needed",
    description: "Exchange a liquid phase around a retained material.",
    consider:
      "Define how material is retained: settling, a compatible magnetic setup, filtration or an external centrifuge.",
  },
  {
    id: "deposit",
    name: "Deposit onto a substrate",
    tag: "Custom or external process",
    description: "Connect formulation to a coating, droplet array or film.",
    consider:
      "Qualify substrate fixtures, dispense height, wetting, drying and any coating instrument.",
  },
  {
    id: "powder",
    name: "Dose and process powders",
    tag: "External equipment",
    description:
      "Include a solid-state route when liquid handling is not suitable.",
    consider:
      "A pipette is not a powder dispenser. Record mass, grinding, heating and transport separately.",
  },
];
export const gantryConcepts: {
  id: GantryId;
  title: string;
  status: string;
  description: string;
  requirements: string;
}[] = [
  {
    id: "liquid",
    title: "Visit a sample library",
    status: "Flex liquid-handling pattern",
    description:
      "The gantry positions the pipette; the pipette meters liquid. Position and dose are different responsibilities.",
    requirements:
      "Qualified labware coordinates, tip geometry, working height and liquid-handling parameters.",
  },
  {
    id: "handoff",
    title: "Move labware between steps",
    status: "Compatible gripper and labware required",
    description:
      "Move a compatible plate between deck positions or modules, preserving its sample map.",
    requirements:
      "Gripper-compatible definition, grip geometry, clearances and a confirmed destination. External-station reach is not assumed.",
  },
  {
    id: "scan",
    title: "Imagine a measurement raster",
    status: "Engineering concept · not implemented",
    description:
      "Explore how repeated positions could support a camera or probe visiting a sample array.",
    requirements:
      "Independent mounting, load and cable checks; sensing integration, calibration and collision validation. No custom sensor is installed by this lesson.",
  },
  {
    id: "tool",
    title: "Imagine a process tool",
    status: "Engineering concept · not implemented",
    description:
      "Use the Jubilee paper to ask whether a tool or a sample should move. Sketch a dispensing or processing station.",
    requirements:
      "Mechanical and electrical integration, process containment, reach, tool offsets and independent qualification. Flex is not presented as a universal tool changer.",
  },
];
export function newBrief(workflow?: Workflow): Brief {
  return {
    id: crypto.randomUUID(),
    title: workflow
      ? `My adaptation: ${workflow.title}`
      : "My discovery experiment",
    source_id: workflow?.id ?? null,
    objective: "",
    variables: "",
    measurement: "",
    decision: "",
    controls: "",
    methods: workflow?.methods.slice() ?? ["blend", "mix"],
    gantry: "liquid",
    status: "design_only",
  };
}
