"""Workflow drafts from an Amazon Nova model through the Bedrock Converse API.

Used instead of Astra when ACADEMY_BRIEF_MODEL is set. The Lambda role calls the model,
so no API key is involved. Nova's tool input is not held to the schema the way a strict
OpenAI response is, so every draft is validated like any other, and a rejected one is
sent back with the reasons for at most ATTEMPTS tries. One request makes at most one
model call, kept well inside the 15 s Lambda limit; the conversation so far is stored
with the brief so the next poll can continue it.
"""

import json
import re

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

ATTEMPTS = 4
TOOL = "teaching_workflow_draft"
# Words a description uses when it states where instruments go on the bench.
PLACES = re.compile(
    r"\b(near|close|next to|beside|adjacent|apart|away|far|left|right|front|back|"
    r"side|corner|cm|metres?|meters?|m)\b",
    re.IGNORECASE,
)
NAMES = {"pro": "Amazon Nova Pro", "lite": "Amazon Nova Lite", "micro": "Amazon Nova Micro"}


def model_name(model_id):
    """A display name for an inference profile ID such as us.amazon.nova-pro-v1:0."""
    kind = model_id.split("amazon.nova-", 1)[-1]
    for key, name in NAMES.items():
        if kind.startswith(key) or kind.startswith(f"2-{key}"):
            return name.replace("Nova", "Nova 2") if kind.startswith("2-") else name
    return "Amazon Nova"


class NovaBriefs:
    def __init__(self, settings, client=None):
        self.settings = settings
        self._client = client

    @property
    def available(self):
        return bool(self.settings.brief_model)

    @property
    def name(self):
        return model_name(self.settings.brief_model)

    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.settings.brief_region,
                config=Config(
                    read_timeout=11, connect_timeout=3, retries={"total_max_attempts": 1}
                ),
            )
        return self._client

    def begin(self, text):
        """The conversation state for a new draft."""
        from .workflow_brief import PROMPT

        return {"messages": [{"role": "user", "content": [{"text": PROMPT + text}]}], "tries": 0}

    def attempt(self, state):
        """One model call: (status, draft, message, next state)."""
        from .workflow_brief import Draft, schema

        state = {**state, "tries": state["tries"] + 1}
        try:
            response = self.client().converse(
                modelId=self.settings.brief_model,
                messages=state["messages"],
                inferenceConfig={"maxTokens": 4000, "temperature": 0},
                toolConfig={
                    "tools": [
                        {
                            "toolSpec": {
                                "name": TOOL,
                                "description": "The drafted teaching workflow.",
                                "inputSchema": {"json": schema()},
                            }
                        }
                    ],
                    "toolChoice": {"tool": {"name": TOOL}},
                },
            )
            message = response["output"]["message"]
            use = next(c["toolUse"] for c in message["content"] if "toolUse" in c)
        except (BotoCoreError, ClientError, KeyError, StopIteration, TypeError):
            return (
                "failed",
                None,
                f"{self.name} did not return a draft. Edit the description and retry.",
                state,
            )
        try:
            draft = Draft.model_validate(use["input"])
        except ValidationError as exc:
            if state["tries"] >= ATTEMPTS:
                return (
                    "failed",
                    None,
                    f"{self.name}'s draft did not match the workflow schema. Nothing was "
                    "saved; retry or build the steps by hand.",
                    state,
                )
            reasons = "; ".join(
                ".".join(map(str, e["loc"])) + ": " + e["msg"] if e["loc"] else e["msg"]
                for e in exc.errors()
            )[:600]
            state["messages"] = [
                *state["messages"],
                json.loads(json.dumps(message)),
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": use["toolUseId"],
                                "status": "error",
                                "content": [
                                    {
                                        "text": f"The draft was rejected: {reasons}. "
                                        "Return the corrected complete draft."
                                    }
                                ],
                            }
                        }
                    ],
                },
            ]
            return "generating", None, "", state
        draft = draft.model_dump(mode="json")
        # Nova adds placement wishes the text never states; they would only narrow the
        # layout search, so they are dropped unless the description talks about places.
        text = state["messages"][0]["content"][0]["text"].rsplit("Workflow description:", 1)[-1]
        if not PLACES.search(text):
            draft["preferences"] = []
        return "draft", draft, "", state
