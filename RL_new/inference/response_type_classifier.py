"""Response-type classification seam for the RL runtime.

The 8 response-type labels the policy was trained on were produced by the
training-time visitor simulator, not by lexical rules, and the channel each one
came from differs (rl-agent-thesis src/simulator/sim8_adapter.py):

  silence      - visitor gave no response          -> Unity's silence timer
  disengaged   - lecture-fatigue latch tripped     -> VR gaze telemetry
  everything else                                  -> utterance content + context

So this module routes each turn to the channel that matches how the label was
generated, rather than running one lexical pass over everything:

  metadata.response_type  (explicit override, unused by Unity today)
  -> is_silence_event     -> "silence"
  -> TelemetryGate        -> "disengaged"
  -> LLM speech classifier (7 labels)
  -> rules_v1 fallback on timeout / error / out-of-vocab

`rules_v1` (inference.response_type_provider) stays registered unmodified: it is
both the fallback and the A/B control for reproducing pre-change behaviour.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from inference.response_type_provider import (
    RESPONSE_TYPE_LABELS,
    predict_response_type,
)

classifier_logger = logging.getLogger("runtime_service.response_type")
if not classifier_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    classifier_logger.addHandler(_handler)
classifier_logger.setLevel(logging.INFO)
classifier_logger.propagate = False


# The one-hot index of each label is baked into the trained network
# (rl-agent-thesis src/environment/env.py:211). Order is load-bearing.
STATE_LABELS: List[str] = list(RESPONSE_TYPE_LABELS)

# repeat_request is a real label in the training reward table but it is NOT in
# the 8-label state contract. The E_flat_S2 boundary
# (inference/bundle_loader.py:BOUNDARY_REMAP) maps it explicitly to "confusion"
# before validation -- HANDOFF.md's open decision, resolved 2026-08-02: both are
# "please go over that again" states, and confusion legally enables ClarifyFact.
# The analysis logs keep the finer distinction; only the state one-hot sees the
# mapped label.
REPEAT_REQUEST = "repeat_request"

# Labels an LLM can decide from the transcript. Excludes silence, which is set from
# the event flag only.
#
# disengaged is included as a DELIBERATE DEVIATION from the training channel split.
# In training it was purely behavioural (the lecture-fatigue latch), so the deployment
# originally detected it from gaze telemetry alone. Real visitors say it out loud --
# observed live: "now I'm getting a bit bored" scored as statement and "Hmm, yeah,
# whatever" as acknowledgment, both while looking straight at the painting, so the
# telemetry gate could never fire. The verbal route is recorded under its own source
# so the two can be separated in analysis.
SPEECH_LABELS: List[str] = [
    "acknowledgment",
    "follow_up_question",
    "question",
    "statement",
    "confusion",
    "clarification_request",
    REPEAT_REQUEST,
    "disengaged",
]

# NOTE (E_flat_S2): the old deadend_fix_v1 runtime remapped
# clarification_request -> confusion here because that run's simulator never
# produced it (HRL_P_CLAR=0). The new contract (deploy_bundle/dialogue_masks.py
# RESPONSE_TYPE_LABELS) lists clarification_request as a valid label, so it now
# enters the state one-hot unchanged; all boundary mapping lives in
# inference/bundle_loader.py:to_contract_label.

# Sources, recorded per turn so every label is attributable after the fact.
SOURCE_METADATA = "metadata"
SOURCE_SILENCE_FLAG = "silence_flag"
SOURCE_FOCUS_CHANGE = "focus_change"
SOURCE_TELEMETRY_RULE = "telemetry_rule"
SOURCE_LLM = "llm"
# disengaged reached from what the visitor SAID rather than from gaze telemetry.
SOURCE_LLM_VERBAL_DISENGAGED = "llm_verbal_disengaged"
SOURCE_RULES_V1 = "rules_v1"
SOURCE_RULES_FALLBACK = "rules_fallback"
SOURCE_ERROR_FALLBACK = "error_fallback"


def _assert_label_contract() -> None:
    """A silently reordered label list would corrupt every state vector in the
    study, and nothing downstream would raise. Fail at import instead."""
    expected = [
        "acknowledgment",
        "follow_up_question",
        "question",
        "statement",
        "confusion",
        "silence",
        "clarification_request",
        "disengaged",
    ]
    if STATE_LABELS != expected:
        raise RuntimeError(
            "response-type label contract broken: the trained checkpoint expects "
            "{expected!r} in this exact order, got {actual!r}".format(
                expected=expected, actual=STATE_LABELS
            )
        )
    for label in SPEECH_LABELS:
        if label not in STATE_LABELS and label != REPEAT_REQUEST:
            raise RuntimeError(
                "speech label {0!r} is neither a state label nor repeat_request".format(label)
            )


_assert_label_contract()


@dataclass
class ClassificationContext:
    """Everything a classifier may look at for one turn."""

    user_utterance: str = ""
    last_agent_reply: str = ""
    last_action: Optional[str] = None      # bare subaction, e.g. "ExplainNewFact"
    history: List[str] = field(default_factory=list)  # "role: text", last 4
    is_silence_event: bool = False
    # VR telemetry, straight from the /turn metadata block.
    off_exhibit_seconds: float = 0.0


@dataclass
class ResponseTypeResult:
    label: str
    source: str
    latency_ms: float = 0.0
    ok: bool = True
    error: str = ""
    # The rules_v1 label for the same turn, always populated for speech turns so
    # the old and new classifiers can be compared offline at zero extra cost.
    rules_v1_label: Optional[str] = None


class TelemetryGate:
    """Behavioural labels come from telemetry, not text.

    In training, `disengaged` was the lecture-fatigue latch
    (sim8_adapter.py:640-700), never a lexical decision. This runtime has no
    equivalent signal anywhere else: RecoverEngagement availability is hardcoded
    to 1.0 (state_builder.py:164) and the fatigue feature keys off the *agent's*
    own explain streak (state_builder.py:195-206), not the visitor. The
    `disengaged` one-hot is therefore the only channel by which visitor
    disengagement can reach the policy at all.

    Precision-first: a false positive misrepresents an engaged visitor in the one
    channel that carries this signal, so require BOTH sustained off-exhibit gaze
    AND absent/minimal speech.

    Stateless by design. The disengagement LATCH lives on SessionState, because
    it is per-visitor and it gates the action space (env.py:1148-1151); a latch
    held here would be shared by every concurrent session through the single
    classifier instance built in RuntimeService.__init__.
    """

    _MINIMAL_SPEECH = {
        "mm", "mmm", "mhm", "mm-hm", "mmhm", "uh huh", "uh-huh", "hm", "hmm",
        "ok", "okay", "yeah", "yep", "yes", "no", "sure", "right",
    }

    def __init__(self, dwell_threshold_sec: float = 6.0):
        self.dwell_threshold_sec = float(dwell_threshold_sec)

    @classmethod
    def _is_minimal_speech(cls, transcript: str) -> bool:
        text = (transcript or "").strip().lower().rstrip(".!,")
        if not text:
            return True
        return text in cls._MINIMAL_SPEECH

    def check(self, ctx: ClassificationContext) -> Optional[ResponseTypeResult]:
        """Return a result to short-circuit on, or None to fall through to speech."""
        if self.dwell_threshold_sec <= 0:
            return None
        if ctx.off_exhibit_seconds < self.dwell_threshold_sec:
            return None
        if not self._is_minimal_speech(ctx.user_utterance):
            return None
        return ResponseTypeResult(label="disengaged", source=SOURCE_TELEMETRY_RULE)


class RulesV1Classifier:
    """The original lexical cascade, unmodified. Fallback and A/B control."""

    name = "rules_v1"

    def classify(self, ctx: ClassificationContext) -> ResponseTypeResult:
        started = time.monotonic()
        label = predict_response_type(
            user_utterance=ctx.user_utterance or "",
            last_agent_reply=ctx.last_agent_reply or "",
            last_action=ctx.last_action,
            history=ctx.history,
            is_silence_event=ctx.is_silence_event,
        )
        return ResponseTypeResult(
            label=label,
            source=SOURCE_RULES_V1,
            latency_ms=(time.monotonic() - started) * 1000.0,
            rules_v1_label=label,
        )


class HybridClassifier:
    """Telemetry gates + LLM speech classification, with a rules_v1 floor.

    `speech_backend` is a callable (prompt: str) -> str returning the raw model
    completion. Injecting it keeps this class network-free for testing.
    """

    name = "hybrid_v1"

    def __init__(
        self,
        speech_backend: Callable[[str], str],
        prompt_builder: Callable[[ClassificationContext], str],
        gate: Optional[TelemetryGate] = None,
        max_attempts: int = 2,
    ):
        self.speech_backend = speech_backend
        self.prompt_builder = prompt_builder
        self.gate = gate or TelemetryGate()
        self.max_attempts = max(1, int(max_attempts))
        self._rules = RulesV1Classifier()

    def classify(self, ctx: ClassificationContext) -> ResponseTypeResult:
        started = time.monotonic()
        rules_label = predict_response_type(
            user_utterance=ctx.user_utterance or "",
            last_agent_reply=ctx.last_agent_reply or "",
            last_action=ctx.last_action,
            history=ctx.history,
            is_silence_event=ctx.is_silence_event,
        )

        gated = self.gate.check(ctx)
        if gated is not None:
            gated.latency_ms = (time.monotonic() - started) * 1000.0
            gated.rules_v1_label = rules_label
            return gated


        prompt = self.prompt_builder(ctx)
        last_error = ""
        for attempt in range(self.max_attempts):
            try:
                raw = self.speech_backend(prompt)
            except Exception as exc:  # network, timeout, auth, malformed response
                last_error = "{0}: {1}".format(type(exc).__name__, exc)
                classifier_logger.warning("speech classifier backend error: %s", last_error)
                break
            label = self._normalize(raw)
            if label in SPEECH_LABELS:
                return ResponseTypeResult(
                    label=label,
                    # Same classifier, but tag the verbal-disengagement route
                    # separately: it is the one place the deployment departs from
                    # training's behavioural-only channel for this label.
                    source=(SOURCE_LLM_VERBAL_DISENGAGED if label == "disengaged" else SOURCE_LLM),
                    latency_ms=(time.monotonic() - started) * 1000.0,
                    rules_v1_label=rules_label,
                )
            last_error = "out-of-vocab label {0!r}".format(raw)
            classifier_logger.warning(
                "speech classifier returned %s (attempt %d/%d)",
                last_error, attempt + 1, self.max_attempts,
            )

        classifier_logger.warning(
            "speech classifier falling back to rules_v1 (%s) for %r",
            rules_label, (ctx.user_utterance or "")[:80],
        )
        return ResponseTypeResult(
            label=rules_label,
            source=SOURCE_RULES_FALLBACK,
            latency_ms=(time.monotonic() - started) * 1000.0,
            ok=False,
            error=last_error,
            rules_v1_label=rules_label,
        )

    @staticmethod
    def _normalize(raw: str) -> str:
        text = (raw or "").strip().lower()
        # Models sometimes wrap the label in quotes, backticks or a trailing period.
        return text.strip("\"'`. \n\t")


def build_classifier(name: str, config: Dict[str, Any]):
    """Registry. An unknown name raises at startup rather than silently
    degrading to rules — a study must not run on an unintended classifier."""
    key = (name or "").strip().lower()
    if key in ("rules_v1", "rules"):
        return RulesV1Classifier()
    if key in ("hybrid_v1", "hybrid"):
        # Imported here so the rules-only path never touches the OpenAI SDK.
        from prompt.response_type_prompt import build_response_type_prompt
        from prompt.openai_generator import generate_classification_label

        model = str(config.get("openai_model", "gpt-5.4"))
        timeout_sec = float(config.get("response_type_llm_timeout_sec", 2.0))
        dwell = float(config.get("response_type_disengage_dwell_sec", 6.0))

        def backend(prompt: str) -> str:
            return generate_classification_label(
                prompt=prompt,
                model=model,
                timeout_sec=timeout_sec,
            )

        return HybridClassifier(
            speech_backend=backend,
            prompt_builder=build_response_type_prompt,
            gate=TelemetryGate(dwell_threshold_sec=dwell),
        )
    raise ValueError(
        "unknown response_type_classifier {0!r} (expected 'rules_v1' or 'hybrid_v1')".format(name)
    )
