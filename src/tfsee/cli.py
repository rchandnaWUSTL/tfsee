"""tfsee: run terraform plan and see it as a graph in your terminal, playing the apply order."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

from . import kitty
from .plan import build, load, summary
from .render import draw, png

IMAGE_ID = 7317  # arbitrary; keeps our image separate from anything else on screen

# `eval "$(tfsee hook zsh)"` makes a plain `terraform plan` draw the graph after its normal output.
# Only plan is touched, only in an interactive terminal; every other command passes straight through.
HOOK = r'''
terraform() {
  local sub="" chdir="." arg
  for arg in "$@"; do
    case "$arg" in
      -chdir=*) chdir="${arg#-chdir=}" ;;
      -*) ;;
      *) sub="$arg"; break ;;
    esac
  done
  if [ "$sub" = "plan" ] && [ -t 1 ] && command -v tfsee >/dev/null 2>&1; then
    case " $* " in *" -out="*|*" -out "*) command terraform "$@"; return ;; esac
    local out rc
    mkdir -p "$chdir/.terraform" && out=".terraform/tfsee.tfplan"
    [ "$chdir" != "." ] && out="$chdir/$out"
    command terraform "$@" -out="$out"; rc=$?
    [ $rc -eq 0 ] && tfsee "$chdir" --plan "$out" --quiet
    return $rc  # plan file kept so the "terraform apply <file>" hint above still works
  fi
  command terraform "$@"
}
'''


def _args(argv):
    p = argparse.ArgumentParser(prog="tfsee", description="See your terraform plan as a graph, in the terminal.")
    p.add_argument("dir", nargs="?", default=".", help="Terraform working directory (default: .)")
    p.add_argument("-var", action="append", default=[], metavar="NAME=VALUE", help="passed to terraform plan")
    p.add_argument("-var-file", action="append", default=[], metavar="FILE", help="passed to terraform plan")
    p.add_argument("--plan", metavar="FILE", help="use a saved plan file instead of running terraform plan")
    p.add_argument("--json", metavar="FILE", help="use `terraform show -json` output (- for stdin)")
    p.add_argument("--png", metavar="FILE", help="also save the graph as a PNG")
    p.add_argument("--no-animate", action="store_true", help="draw the finished plan only")
    p.add_argument("--speed", type=int, default=900, metavar="MS", help="ms per apply wave (default 900)")
    p.add_argument("--quiet", action="store_true", help="skip the summary line (terraform already printed it)")
    return p.parse_args(argv)


def _summary_line(nodes) -> str:
    add, change, destroy = summary(nodes)
    green, yellow, red, reset = ("\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[0m") if sys.stdout.isatty() else ("",) * 4
    return f"Plan: {green}{add} to add{reset}, {yellow}{change} to change{reset}, {red}{destroy} to destroy{reset}."


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hook"]:
        print(HOOK.strip())  # the same function works in zsh and bash
        return 0
    args = _args(argv)
    tf_args = [f"-var={v}" for v in args.var] + [f"-var-file={f}" for f in args.var_file]
    plan = load(args.dir, tf_args, plan_file=args.plan, json_file=args.json)
    nodes = build(plan)
    if not nodes:
        print("No resources in this plan.")
        return 0
    if not args.quiet:
        print(_summary_line(nodes))

    text_scale = float(os.environ.get("TFSEE_TEXT_SCALE", "1") or 1)
    final = draw(nodes, text_scale=text_scale)
    if args.png:
        final.save(args.png)
    if not (sys.stdout.isatty() and kitty.supported()):
        out = args.png or "tfsee.png"
        if not args.png:
            final.save(out)
        print(f"This terminal can't draw images (try Ghostty or Kitty, outside tmux). Saved the graph to {out}")
        return 0

    columns = min(shutil.get_terminal_size().columns - 2, 200)
    waves = max(n.wave for n in nodes.values())
    write = sys.stdout.write
    if args.no_animate or waves == 0:
        write(kitty.show(png(final), IMAGE_ID, columns) + "\n")
        return 0

    frames = [png(draw(nodes, applied_through=w, text_scale=text_scale)) for w in range(waves + 1)] + [png(final)]
    if kitty.native_animation():
        # Native animation: the terminal loops it, and your prompt comes right back.
        write(kitty.show(frames[0], IMAGE_ID, columns))
        for frame in frames[1:-1]:
            write(kitty.add_frame(frame, IMAGE_ID, args.speed))
        write(kitty.add_frame(frames[-1], IMAGE_ID, args.speed * 3))  # hold the finished plan
        write(kitty.set_gap(IMAGE_ID, 1, args.speed))
        write(kitty.play(IMAGE_ID, loops=1) + "\n")
    else:
        # Older terminals: redraw each frame in place, once, ending on the finished plan.
        write("\x1b7")  # save cursor
        for i, frame in enumerate(frames):
            write("\x1b8" + kitty.delete(IMAGE_ID) + kitty.show(frame, IMAGE_ID, columns))
            sys.stdout.flush()
            if i < len(frames) - 1:
                time.sleep(args.speed / 1000)
        write("\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    sys.exit(main())
