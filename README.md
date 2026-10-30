# tfsee

**See your `terraform plan` as a graph, right in your terminal.**

Type `terraform plan` like you always do. After the usual output, tfsee draws every change as a dependency graph and plays it in the order Terraform will apply it.

![tfsee drawing a terraform plan as an animated graph in Ghostty](https://raw.githubusercontent.com/rchandnaWUSTL/tfsee/main/docs/demo.gif)

A 400-line text plan tells you what changes. It doesn't show you what depends on what, or which change lands first. tfsee does, without leaving the terminal.

## Quickstart

You need Python 3.10+, Terraform, and a terminal that can draw images: [Ghostty](https://ghostty.org) 1.4+, [Kitty](https://sw.kovidgoyal.net/kitty/), or [WezTerm](https://wezfurlong.org/wezterm/).

**1. Install**

```sh
uv tool install tfsee
# or: pipx install tfsee
```

**2. Hook it into `terraform plan`**

Add this line to your `~/.zshrc` (or `~/.bashrc`), then open a new shell:

```sh
eval "$(tfsee hook zsh)"
```

**3. Plan**

```sh
terraform plan
```

You get Terraform's normal output, then the graph. That's it.

> The hook only touches `terraform plan`, and only in an interactive terminal. Every other command, pipes, and CI runs go straight to Terraform.

## Try it without your own infrastructure

The repo includes a small demo built only from Terraform's built-in `terraform_data` resource. No cloud account, no credentials, nothing to download.

```sh
git clone https://github.com/rchandnaWUSTL/tfsee && cd tfsee/examples/demo
terraform init && terraform apply -auto-approve
terraform plan -var stage=v2
```

You'll see 4 resources to add, 2 to change, and 3 to destroy, across 6 apply steps.

## Reading the graph

| You see | It means |
|---|---|
| `+` teal box | Created |
| `~` yellow box | Updated in place |
| `±` purple box | Replaced (destroyed, then created) |
| `-` red box, struck through | Destroyed |
| `·` gray box | Unchanged, shown for context |
| Columns, left to right | Apply steps: everything in a step depends only on earlier steps |
| Lines | Dependencies: a box depends on every box that points into it |

Every box carries Terraform's own symbol (`+ ~ ± -`), so the graph reads fine in grayscale and for colorblind viewers. The colors also pass a colorblind-safety check against the dark background.

The animation plays the steps in order: the step being applied glows, and later steps stay dim until it's their turn.

## Other ways to run it

```sh
tfsee                          # plan the current directory and draw it
tfsee infra/ -var env=prod     # -var and -var-file pass through to terraform plan
tfsee --plan out.tfplan        # draw a saved plan
terraform show -json out.tfplan | tfsee --json -
tfsee --no-animate             # draw the finished graph only
tfsee --png plan.png           # also save it as an image
```

| Option | What it does |
|---|---|
| `--speed MS` | Milliseconds per apply step in the animation (default 900) |
| `--quiet` | Skip tfsee's summary line (the hook uses this, since Terraform already prints one) |
| `TFSEE_TEXT_SCALE=1.4` | Bigger text in the graph, useful for screenshots and talks |

## Terminal support

| Terminal | What you get |
|---|---|
| Ghostty 1.4+ | Full animation, drawn natively |
| Kitty | Full animation, drawn natively |
| Ghostty before 1.4, WezTerm | The graph, animated by redrawing each frame |
| Anything else, or inside tmux | tfsee saves `tfsee.png` and tells you where |

tfsee uses the [Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/) to put images in the terminal. Animation support arrived in Ghostty 1.4.

## How it works

1. Runs `terraform plan`, then reads the plan as JSON with `terraform show -json`.
2. Takes each resource's action from `resource_changes`. Dependencies come from the references and `depends_on` in your configuration, or from state for resources being destroyed.
3. Groups resources into apply steps by dependency depth, orders each step to reduce crossing lines, and draws the graph with [Pillow](https://python-pillow.org).
4. Sends the frames to the terminal, which plays them as an animation.

tfsee only reads your plan. It never runs `apply`, and nothing leaves your machine.

## Limitations

- **Apply steps are an approximation.** Terraform applies in parallel and orders destroys separately, so read the graph as "what depends on what," not as a timeline.
- **Large plans get wide.** It works best on plans of up to a few dozen resources. Very large plans still render, but you may want `--png` and an image viewer.
- **Data sources aren't drawn.** Only managed resources appear.

## Development

```sh
git clone https://github.com/rchandnaWUSTL/tfsee && cd tfsee
uv venv && uv pip install -e '.[dev]'
.venv/bin/pytest
```

`scripts/demo.sh` plays the demo for a screen recording, and `scripts/edit_video.py` turns that recording into the video above.

Issues and pull requests are welcome.

## License

[MIT](LICENSE). A personal project, not affiliated with HashiCorp or Ghostty.
