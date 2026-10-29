# tfsee

See your `terraform plan` as a graph, drawn right in your terminal, then watch it play the apply order.

Green creates, yellow updates, purple replaces, red destroys. Each column is one apply wave, so you can see what changes first and what depends on what. That's hard to spot in a 400-line text plan.

## Install

```
pip install git+https://github.com/<you>/tfsee
```

You need Python 3.10+, Terraform, and a terminal that can show images: [Ghostty](https://ghostty.org) 1.4+ (for animation), Kitty, or WezTerm. In other terminals (or inside tmux), tfsee saves the graph as a PNG instead.

## Use

```
tfsee                      # plan the current directory and draw it
tfsee infra/ -var env=prod # pass -var / -var-file through to terraform plan
tfsee --plan out.tfplan    # use a saved plan
terraform show -json out.tfplan | tfsee --json -
tfsee --no-animate --png plan.png
```

## Try the demo

The demo uses only Terraform's built-in `terraform_data` resource: no cloud account, no credentials, no providers to download.

```
cd examples/demo
terraform init && terraform apply -auto-approve
tfsee . -var stage=v2
```

You'll get 4 to add, 2 to change, 3 to destroy, across 6 apply waves.

## How it works

1. Runs `terraform plan` and reads `terraform show -json`.
2. Takes each resource's action from `resource_changes`, and its dependencies from the expressions and `depends_on` in the configuration (or from state, for resources being destroyed).
3. Orders resources into apply waves by dependency depth and draws them with Pillow.
4. Sends the image to the terminal with the [Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/). On Ghostty 1.4+ and Kitty, the frames play as a native animation. Older Ghostty versions get a frame-by-frame redraw.

Apply waves approximate Terraform's real walk, which runs in parallel and orders destroys separately. Use the graph to understand a plan, not to predict exact timing.

Personal project, not affiliated with HashiCorp.

## License

MIT
