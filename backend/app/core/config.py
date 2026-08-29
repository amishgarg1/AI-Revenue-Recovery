"""
Policy as configuration.

The eleven gates enforce rules; they should not also *own* them. Quiet hours
are 9 PM to 9 AM here because that is the Indian norm, the frequency cap is one
message a day because that is what felt defensible, and a voice call costs
₹1.50 because that is roughly what a call costs. Every one of those is a
merchant's decision, not an engineering constant, and a merchant in another
country will disagree with the first one before they finish reading it.

So the numbers live in `config/policy.yaml` and the gates read them from here.
The engine is the same for everybody; the policy is not.

Three properties this has to have, in order of how badly they bite:

**The demo must run with no config file at all.** Every value has a default,
which is the value the committed evaluation was produced with. A missing file
is normal, not an error.

**A malformed file must fail loudly at load, not quietly at midnight.** A
typo'd `quiet_hours` that silently falls back to the default would mean a
merchant believes they have set a rule they have not. Unknown keys are
rejected for the same reason - a misspelled key is a rule that does nothing.

**Per merchant, not per deployment.** One engine serves many merchants with
different rules, so a merchant id resolves to a policy: their overrides on top
of the defaults, and the defaults alone when they have none.
"""

import os
from dataclasses import dataclass, field, fields
from typing import Dict, Optional

CONFIG_ENV = "RECOVEROS_POLICY"

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
DEFAULT_PATH = os.path.join(REPO_ROOT, "config", "policy.yaml")


class PolicyConfigError(ValueError):
    """A policy file that cannot be trusted. Never swallowed."""


@dataclass(frozen=True)
class PolicyConfig:
    """
    One merchant's rules.

    Defaults are the values the committed evaluation was produced with, so a
    deployment with no config file reproduces the published numbers exactly.
    Frozen because a gate that could mutate the policy while evaluating it
    would be unauditable.
    """

    # Contact windows, in IST hours.
    quiet_start_ist: int = 21
    quiet_end_ist: int = 9
    voice_start_ist: int = 10
    voice_end_ist: int = 19

    # How often a person may be contacted, across all their cases.
    max_touches_per_case: int = 3
    max_touches_24h: int = 1
    max_touches_7d: int = 3
    cooldown_hours: int = 6

    # What a recovery attempt may cost.
    max_cost_ratio: float = 0.15
    min_viable_amount_paise: int = 5_000
    compliance_risk_paise: int = 50_000

    # What each rung costs to send, in paise.
    tier_cost_paise: Dict[int, int] = field(
        default_factory=lambda: {0: 0, 1: 30, 2: 20, 3: 150, 4: 5_000})
    voice_min_amount_paise: int = 200_000

    label: str = "default"

    def __post_init__(self):
        self._validate()

    # ------------------------------------------------------------ validation

    def _validate(self):
        """
        Reject a policy that cannot mean what it says.

        Checked here rather than at the gate, because a gate that has to
        defend against nonsense every evaluation is a gate whose logic is
        buried in defence.
        """
        for name in ("quiet_start_ist", "quiet_end_ist",
                     "voice_start_ist", "voice_end_ist"):
            hour = getattr(self, name)
            if not isinstance(hour, int) or not 0 <= hour <= 23:
                raise PolicyConfigError(
                    f"{name} must be an hour from 0 to 23, got {hour!r}")

        if self.quiet_start_ist == self.quiet_end_ist:
            raise PolicyConfigError(
                f"quiet_start_ist and quiet_end_ist are both "
                f"{self.quiet_start_ist}; that means either always quiet or "
                "never quiet, and there is no way to tell which was meant")

        if self.voice_start_ist >= self.voice_end_ist:
            raise PolicyConfigError(
                f"voice_start_ist ({self.voice_start_ist}) must be before "
                f"voice_end_ist ({self.voice_end_ist}); a window that wraps "
                "midnight is not something a merchant means to configure")

        for name in ("max_touches_per_case", "max_touches_24h",
                     "max_touches_7d", "cooldown_hours"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise PolicyConfigError(
                    f"{name} must be a non-negative integer, got {value!r}")

        if self.max_touches_24h > self.max_touches_7d:
            raise PolicyConfigError(
                f"max_touches_24h ({self.max_touches_24h}) exceeds "
                f"max_touches_7d ({self.max_touches_7d}), so the weekly cap "
                "could never bind")

        if not 0 < self.max_cost_ratio <= 1:
            raise PolicyConfigError(
                f"max_cost_ratio must be between 0 and 1, got "
                f"{self.max_cost_ratio!r}")

        for name in ("min_viable_amount_paise", "compliance_risk_paise",
                     "voice_min_amount_paise"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise PolicyConfigError(
                    f"{name} must be a non-negative whole number of paise, "
                    f"got {value!r}")

        if set(self.tier_cost_paise) != {0, 1, 2, 3, 4}:
            raise PolicyConfigError(
                "tier_cost_paise must price every rung 0 to 4, got "
                f"{sorted(self.tier_cost_paise)}")

        for tier, cost in self.tier_cost_paise.items():
            if not isinstance(cost, int) or cost < 0:
                raise PolicyConfigError(
                    f"tier {tier} cost must be a non-negative whole number of "
                    f"paise, got {cost!r}")

    # -------------------------------------------------------------- building

    @classmethod
    def from_dict(cls, data: dict, label: str = "default") -> "PolicyConfig":
        known = {f.name for f in fields(cls)} - {"label"}
        unknown = set(data) - known
        if unknown:
            # A misspelled key is a rule the merchant believes they set and
            # did not. Louder than a silent default.
            raise PolicyConfigError(
                f"unknown policy keys: {sorted(unknown)}. "
                f"Valid keys are {sorted(known)}")

        values = dict(data)
        if "tier_cost_paise" in values:
            # YAML gives string keys when they are quoted; rungs are integers.
            values["tier_cost_paise"] = {
                int(k): v for k, v in values["tier_cost_paise"].items()
            }
        return cls(label=label, **values)


@dataclass(frozen=True)
class PolicyBook:
    """Every merchant's policy, plus the fallback for merchants with none."""

    default: PolicyConfig
    merchants: Dict[str, PolicyConfig] = field(default_factory=dict)
    source: Optional[str] = None

    def for_merchant(self, merchant_id: Optional[str]) -> PolicyConfig:
        if merchant_id and merchant_id in self.merchants:
            return self.merchants[merchant_id]
        return self.default


def _read(path: str) -> dict:
    import yaml

    with open(path, encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise PolicyConfigError(
            f"{path} must contain a mapping at the top level, got "
            f"{type(loaded).__name__}")
    return loaded


def load(path: Optional[str] = None) -> PolicyBook:
    """
    Read the policy book, or return the built-in defaults.

    `RECOVEROS_POLICY` overrides the path, which is how the tests point at a
    fixture without touching the committed file.
    """
    path = path or os.environ.get(CONFIG_ENV) or DEFAULT_PATH
    if not os.path.exists(path):
        return PolicyBook(default=PolicyConfig(), source=None)

    raw = _read(path)
    unknown = set(raw) - {"defaults", "merchants"}
    if unknown:
        raise PolicyConfigError(
            f"{path}: unknown top-level keys {sorted(unknown)}; "
            "expected 'defaults' and 'merchants'")

    default = PolicyConfig.from_dict(raw.get("defaults") or {})

    merchants = {}
    for merchant_id, overrides in (raw.get("merchants") or {}).items():
        # A merchant states only what differs. Repeating the whole policy per
        # merchant is how two of them silently drift apart.
        merged = {
            f.name: getattr(default, f.name)
            for f in fields(PolicyConfig) if f.name != "label"
        }
        merged.update(overrides or {})
        merchants[merchant_id] = PolicyConfig.from_dict(merged, label=merchant_id)

    return PolicyBook(default=default, merchants=merchants, source=path)


# Loaded once. `reload()` exists for the tests and for an operator who has just
# edited the file; nothing reloads on a timer, because a policy that changes
# halfway through a batch would make the audit trail unreadable.
_book: Optional[PolicyBook] = None


def book() -> PolicyBook:
    global _book
    if _book is None:
        _book = load()
    return _book


def reload(path: Optional[str] = None) -> PolicyBook:
    global _book
    _book = load(path)
    return _book


def active(merchant_id: Optional[str] = None) -> PolicyConfig:
    """The policy in force for this merchant."""
    return book().for_merchant(merchant_id)
