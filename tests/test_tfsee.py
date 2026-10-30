import base64
import json
import re
from pathlib import Path

from tfsee import kitty
from tfsee.plan import build, focus, resource_of, summary
from tfsee.render import draw

PLAN = json.loads((Path(__file__).parent / "fixtures" / "plan_v2.json").read_text())


def test_actions_match_terraform():
    nodes = build(PLAN)
    assert summary(nodes) == (4, 2, 3)  # what `terraform plan` printed for this fixture
    assert nodes["terraform_data.app[0]"].action == "replace"
    assert nodes["terraform_data.cache[0]"].action == "delete"
    assert nodes["terraform_data.database"].action == "update"
    assert nodes["terraform_data.queue[0]"].action == "create"


def test_dependencies_and_apply_order():
    nodes = build(PLAN)
    assert nodes["terraform_data.load_balancer"].deps == {"terraform_data.app[0]", "terraform_data.app[1]"}
    assert nodes["terraform_data.network"].wave == 0
    assert nodes["terraform_data.alerts[0]"].wave > nodes["terraform_data.load_balancer"].wave > nodes["terraform_data.app[0]"].wave
    for n in nodes.values():
        assert all(nodes[d].wave < n.wave for d in n.deps)


def test_resource_of_strips_only_final_index():
    assert resource_of('module.net[0].aws_subnet.private["a"]') == "module.net[0].aws_subnet.private"
    assert resource_of("aws_instance.web") == "aws_instance.web"


def test_frames_share_one_size():
    nodes = build(PLAN)
    sizes = {draw(nodes, applied_through=w).size for w in range(3)} | {draw(nodes).size}
    assert len(sizes) == 1  # kitty animation frames must match the root image


def test_kitty_chunks_reassemble():
    payload = bytes(range(256)) * 50
    out = kitty.show(payload, 7, columns=80)
    parts = re.findall(r"\x1b_G([^;\x1b]*);([^\x1b]*)\x1b\\", out)
    assert parts[0][0].startswith("a=T,f=100,i=7,q=2,c=80,m=1")
    assert all(keys in ("m=1", "m=0") for keys, _ in parts[1:]) and parts[-1][0].endswith("m=0")
    assert all(len(chunk) <= kitty.CHUNK for _, chunk in parts)
    assert base64.standard_b64decode("".join(chunk for _, chunk in parts)) == payload


def test_focus_keeps_only_changes_with_true_order():
    nodes = build(PLAN)
    kept = focus(nodes)
    assert set(kept) == {a for a, n in nodes.items() if n.action != "no-op"}
    # app depends on database/cache/queue directly; database's own deps (subnets) are unchanged, so it's a root.
    assert kept["terraform_data.app[0]"].deps == {"terraform_data.database", "terraform_data.cache[0]", "terraform_data.queue[0]"}
    assert kept["terraform_data.database"].deps == set()
    assert kept["terraform_data.alerts[0]"].wave > kept["terraform_data.load_balancer"].wave > kept["terraform_data.app[0]"].wave


def test_scales_linearly():
    import time
    layers = [[f"t.r{l}_{i}" for i in range(100)] for l in range(20)]  # 2,000 resources, deep and wide
    plan = {"resource_changes": [{"address": a, "mode": "managed", "change": {"actions": ["no-op"]}}
                                 for layer in layers for a in layer],
            "configuration": {"root_module": {"resources": [
                {"address": a, "expressions": {"x": {"references": layers[l - 1][:4] if l else []}}}
                for l, layer in enumerate(layers) for a in layer]}}}
    start = time.time()
    nodes = build(plan)
    assert time.time() - start < 2
    assert max(n.wave for n in nodes.values()) == 19
