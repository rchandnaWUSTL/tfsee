"""Turn Terraform plan JSON into a resource graph: what changes, what depends on what, apply order."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ACTIONS = {
    ("create",): "create",
    ("update",): "update",
    ("delete",): "delete",
    ("delete", "create"): "replace",
    ("create", "delete"): "replace",
    ("read",): "read",
    ("no-op",): "no-op",
}
NOT_RESOURCES = {"var", "local", "count", "each", "path", "terraform", "self", "module"}


@dataclass
class Node:
    address: str
    action: str
    deps: set[str] = field(default_factory=set)
    wave: int = 0  # apply order: 0 runs first, then 1, and so on


def resource_of(address: str) -> str:
    """'module.a[0].x.y["k"]' -> 'module.a[0].x.y': drop only the final instance key."""
    return re.sub(r"\[[^\[\]]*\]$", "", address)


def _resource_ref(ref: str) -> str | None:
    """'aws_s3_bucket.logs.arn' -> 'aws_s3_bucket.logs'; 'var.x', 'count.index' -> None."""
    parts = ref.split(".")
    if parts[0] in NOT_RESOURCES or len(parts) < 2:
        return None
    if parts[0] == "data":
        return ".".join(parts[:3]) if len(parts) >= 3 else None
    return ".".join(parts[:2])


def _references(expr) -> set[str]:
    found = set()
    if isinstance(expr, dict):
        for key, value in expr.items():
            if key == "references" and isinstance(value, list):
                found |= {r for r in value if isinstance(r, str)}
            else:
                found |= _references(value)
    elif isinstance(expr, list):
        for item in expr:
            found |= _references(item)
    return found


def _config_deps(module: dict, prefix: str = "") -> dict[str, set[str]]:
    """Resource-level dependencies from the plan's configuration block, recursing into modules."""
    deps = {}
    for res in module.get("resources", []):
        refs = _references(res.get("expressions", {})) | set(res.get("depends_on", []))
        deps[prefix + res["address"]] = {prefix + r for r in filter(None, map(_resource_ref, refs))}
    for name, call in module.get("module_calls", {}).items():
        deps |= _config_deps(call.get("module", {}), f"{prefix}module.{name}.")
    return deps


def _prior_deps(module: dict) -> dict[str, set[str]]:
    """Dependencies recorded in state, for resources removed from config (planned deletes)."""
    deps = {}
    for res in module.get("resources", []):
        deps[res["address"]] = {resource_of(d) for d in res.get("depends_on", [])}
    for child in module.get("child_modules", []):
        deps |= _prior_deps(child)
    return deps


def build(plan: dict) -> dict[str, Node]:
    nodes = {}
    for rc in plan.get("resource_changes", []):
        if rc.get("mode") != "managed":
            continue
        actions = tuple(rc.get("change", {}).get("actions", ["no-op"]))
        nodes[rc["address"]] = Node(rc["address"], ACTIONS.get(actions, "no-op"))

    config = _config_deps(plan.get("configuration", {}).get("root_module", {}))
    prior = _prior_deps(plan.get("prior_state", {}).get("values", {}).get("root_module", {}))
    by_resource: dict[str, list[str]] = {}
    for addr in nodes:
        by_resource.setdefault(resource_of(addr), []).append(addr)
    for addr, node in nodes.items():
        res = resource_of(addr)
        refs = config.get(res) if res in config else prior.get(addr, set())
        node.deps = {d for ref in refs for d in by_resource.get(ref, []) if d != addr}

    return assign_waves(nodes)


def assign_waves(nodes: dict[str, Node]) -> dict[str, Node]:
    """Apply step = longest dependency chain below a resource. Kahn's topological order makes this
    linear in resources + edges; anything left on a cycle (Terraform rejects those) keeps step 0."""
    for node in nodes.values():
        node.wave = 0
    dependents: dict[str, list[str]] = {a: [] for a in nodes}
    for addr, node in nodes.items():
        for dep in node.deps:
            dependents[dep].append(addr)
    waiting = {a: len(n.deps) for a, n in nodes.items()}
    ready = [a for a, count in waiting.items() if count == 0]
    while ready:
        addr = ready.pop()
        for nxt in dependents[addr]:
            nodes[nxt].wave = max(nodes[nxt].wave, nodes[addr].wave + 1)
            waiting[nxt] -= 1
            if waiting[nxt] == 0:
                ready.append(nxt)
    return nodes


def focus(nodes: dict[str, Node]) -> dict[str, Node]:
    """Only the resources that change. A changed resource depends on another changed one if there's
    a path between them, even through unchanged resources, so the order of changes stays true while
    the hundreds of no-ops in a big plan drop out."""
    changed = {a for a, n in nodes.items() if n.action != "no-op"}
    kept = {}
    for c in changed:
        found, seen, stack = set(), set(), list(nodes[c].deps)
        while stack:
            d = stack.pop()
            if d in seen:
                continue
            seen.add(d)
            if d in changed:
                found.add(d)  # nearest changed ancestor on this path; stop here
            else:
                stack.extend(nodes[d].deps)
        kept[c] = Node(c, nodes[c].action, found)
    # Transitive reduction: drop a line A->C when A already reaches C through another kept resource.
    # Same order, far fewer lines.
    ancestors: dict[str, set[str]] = {}

    def reach(a: str, stack: frozenset = frozenset()) -> set[str]:
        if a not in ancestors:
            ancestors[a] = set()  # placeholder also breaks cycles
            out = set()
            for d in kept[a].deps:
                if d not in stack:
                    out |= {d} | reach(d, stack | {a})
            ancestors[a] = out
        return ancestors[a]

    for node in kept.values():
        node.deps = {d for d in node.deps if not any(d in reach(e) for e in node.deps if e != d)}
    return assign_waves(kept)


def summary(nodes: dict[str, Node]) -> tuple[int, int, int]:
    """(to add, to change, to destroy), counted the way `terraform plan` does."""
    acts = [n.action for n in nodes.values()]
    add = acts.count("create") + acts.count("replace")
    change = acts.count("update")
    destroy = acts.count("delete") + acts.count("replace")
    return add, change, destroy


def load(directory: str = ".", tf_args: list[str] | None = None, plan_file: str | None = None,
         json_file: str | None = None) -> dict:
    """Plan JSON from a file, a saved plan, or a fresh `terraform plan` in `directory`."""
    if json_file:
        text = Path("/dev/stdin").read_text() if json_file == "-" else Path(json_file).read_text()
        return json.loads(text)
    tf = ["terraform", f"-chdir={directory}"]
    if not plan_file:
        if not (Path(directory) / ".terraform").exists():
            subprocess.run([*tf, "init", "-input=false"], check=True, capture_output=True, text=True)
        tmp = tempfile.NamedTemporaryFile(suffix=".tfplan", delete=False)
        plan_file = tmp.name
        tmp.close()
        result = subprocess.run([*tf, "plan", "-input=false", "-lock=false", f"-out={plan_file}", *(tf_args or [])],
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(result.stderr or result.stdout)
    shown = subprocess.run([*tf, "show", "-json", str(Path(plan_file).resolve())],
                           check=True, capture_output=True, text=True)
    return json.loads(shown.stdout)
