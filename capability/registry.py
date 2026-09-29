"""CapabilityRegistry: which providers exist, what they can do, and which one a job should use.

Selection is deterministic: the same providers, requirement and policy always give the same ranking, and every
provider that was left out carries its reason. Availability is asked of each provider at selection time (a tool
may be missing, a key unset, an MCP server down), so an unavailable provider is skipped, never crashed into.
"""
from __future__ import annotations

import dataclasses

from contracts.base import hash_without
from contracts.capability import Policy, Rejection, Requirement, Selection


class NoProvider(RuntimeError):
    def __init__(self, selection: Selection) -> None:
        reasons = "; ".join(f"{r.provider_id}: {r.reason}" for r in selection.rejected) or "none registered"
        super().__init__(f"no provider for {selection.requirement.capability} ({reasons})")
        self.selection = selection


class CapabilityRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, object] = {}

    def register(self, provider) -> None:
        pid = provider.manifest().provider_id
        if pid in self._providers:
            raise ValueError(f"provider {pid!r} is already registered")
        self._providers[pid] = provider

    def get(self, provider_id: str):
        return self._providers[provider_id]

    def catalog(self) -> dict[str, list[str]]:
        """capability -> provider ids, for listing what this installation can do."""
        out: dict[str, list[str]] = {}
        for pid, p in sorted(self._providers.items()):
            for cap in p.manifest().capabilities:
                out.setdefault(cap, []).append(pid)
        return dict(sorted(out.items()))

    def select(self, req: Requirement, policy: Policy = Policy()) -> Selection:
        ok, rejected = [], []
        for pid, provider in sorted(self._providers.items()):
            m = provider.manifest()
            if req.capability not in m.capabilities:
                continue
            reason = _unfit(m, req, policy)
            if not reason:
                up, why = provider.available()
                reason = "" if up else f"unavailable: {why}"
            if reason:
                rejected.append(Rejection(pid, reason))
            else:
                ok.append(m)
        rank = {"cheap": lambda m: (m.cost_per_second, -m.quality, m.latency_seconds),
                "quality": lambda m: (-m.quality, m.cost_per_second, m.latency_seconds),
                "fast": lambda m: (m.latency_seconds, m.cost_per_second, -m.quality)}[policy.prefer]
        explicit = {pid: i for i, pid in enumerate(policy.order)}
        ok.sort(key=lambda m: (explicit.get(m.provider_id, len(explicit)), rank(m), m.provider_id))
        sel = Selection(req, policy, [m.provider_id for m in ok], rejected)
        return dataclasses.replace(sel, selection_hash=hash_without(sel, "selection_hash"))

    def choose(self, req: Requirement, policy: Policy = Policy()) -> tuple[list, Selection]:
        """The usable providers, best first, and the selection record. Raises NoProvider when there are none."""
        sel = self.select(req, policy)
        if not sel.chosen:
            raise NoProvider(sel)
        return [self._providers[pid] for pid in sel.chosen], sel


def _unfit(m, req: Requirement, policy: Policy) -> str:
    missing = sorted(set(req.features) - set(m.features))
    if missing:
        return "lacks " + ", ".join(missing)
    if m.max_seconds and req.seconds > m.max_seconds:
        return f"{req.seconds:g}s is longer than its {m.max_seconds:g}s limit"
    if (m.max_width and req.width > m.max_width) or (m.max_height and req.height > m.max_height):
        return f"{req.width}x{req.height} is larger than its {m.max_width}x{m.max_height} limit"
    if m.provider_id in policy.deny:
        return "denied by policy"
    if not m.local and not policy.allow_remote:
        return "remote providers not allowed by policy"
    cost = m.cost_per_second * max(req.seconds, 1.0)
    if cost > policy.max_cost:
        return f"costs {cost:.2f} {m.currency}, over the {policy.max_cost:.2f} budget"
    return ""
