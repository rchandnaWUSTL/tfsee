#!/bin/zsh
# Plays the demo for a screen recording: resets the demo infra to v1, then "types" and runs
# a plain `terraform plan` with the tfsee hook on, so the graph draws after terraform's output.
cd "${0:A:h}/../examples/demo" || exit 1
terraform apply -auto-approve -input=false >/dev/null 2>&1
eval "$(tfsee hook zsh)"
clear
prompt() { printf '\e[38;5;244m~/infra\e[0m \e[38;5;79m❯\e[0m '; }
prompt
sleep 1.2
cmd="terraform plan -var stage=v2"
for ((i = 1; i <= ${#cmd}; i++)); do printf '%s' "${cmd[i]}"; sleep 0.045; done
sleep 0.5
echo
terraform plan -var stage=v2 -compact-warnings
prompt
sleep ${DEMO_HOLD:-30}
