"""
PROPOSAL — not agreed yet. For discussion in the 18 Nov session.

The contract between the dialogue module and the game loop.

Design rule: **the LLM proposes, the game disposes.** The model returns a
structured suggestion; game code reads `intent` and applies its own rules.
Model output never writes game state directly — otherwise a hallucinated item
ends up in the player's inventory.

Requires: pydantic >= 2
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

# The only actions the game knows how to carry out. Anything else is rejected.
Intent = Literal[
    "smalltalk",   # flavour only, no state change
    "hint",        # nudge towards the objective, never the full solution
    "give_quest",  # game assigns the quest matching `quest_id`
    "give_item",   # game adds `item` to the inventory, if the rules allow it
    "refuse",      # NPC declines; game may set a flag
]

Emotion = Literal["neutral", "happy", "angry", "afraid", "sly"]


class NPCReply(BaseModel):
    """One NPC turn. This is what the dialogue module hands the game loop."""

    text: str = Field(
        description="What the NPC says out loud. At most two sentences, in character."
    )
    emotion: Emotion = Field(
        default="neutral",
        description="Drives the portrait/sprite shown with the line.",
    )
    intent: Intent = Field(
        default="smalltalk",
        description="What the NPC is trying to do. The game decides whether to allow it.",
    )
    item: Optional[str] = Field(
        default=None,
        description="Item id. Only meaningful when intent is 'give_item'.",
    )
    quest_id: Optional[str] = Field(
        default=None,
        description="Quest id. Only meaningful when intent is 'give_quest'.",
    )


class GameState(BaseModel):
    """
    Compact state serialised into the system prompt.

    Keep it SMALL. The model has no memory, so everything it needs to stay
    consistent has to travel in the prompt — but the full history grows without
    bound and costs tokens. Send the last few turns, not the whole conversation.
    """

    player_name: str
    location: str
    inventory: list[str] = Field(default_factory=list)
    flags: dict[str, bool] = Field(
        default_factory=dict,
        description="World facts already established, e.g. {'met_innkeeper': True}.",
    )
    last_turns: list[str] = Field(
        default_factory=list,
        description="Last N exchanges, most recent last. Never the full history.",
    )


class NPCProfile(BaseModel):
    """Static description of an NPC, written once and reused in every prompt."""

    npc_id: str
    name: str
    role: str = Field(description="e.g. 'innkeeper of the harbour town'")
    personality: str = Field(description="Two or three adjectives.")
    knows: list[str] = Field(
        default_factory=list,
        description="Facts this NPC may reveal.",
    )
    must_not_reveal: list[str] = Field(
        default_factory=list,
        description="Facts this NPC must never state, even if asked directly.",
    )


# --- Open questions for the session -----------------------------------------
#
# 1. Does the game loop want NPCReply as a Python object, or as JSON over a
#    boundary (HTML5 front end)? If JSON, we freeze this as a JSON Schema too.
# 2. Are `item` and `quest_id` ids from a fixed catalogue? They should be —
#    otherwise the model invents them and the game cannot resolve them.
# 3. How many NPCs are in scope? Two or three done well beats ten half-working.
# 4. Baked vs live: agreed plan is to pre-generate a dialogue bank as the
#    default, with live calls as an optional mode. The demo must not depend on
#    a network call succeeding in the classroom.
