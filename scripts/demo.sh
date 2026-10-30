#!/bin/zsh
# Plays the demo for a screen recording: resets the demo infra to v1, points the next plan at v2
# (via TF_VAR_stage, so the typed command is just `terraform plan`), then "types" and runs it with
# the tfsee hook on, so the graph draws after terraform's normal output.
cd "${0:A:h}/../examples/demo" || exit 1
terraform apply -auto-approve -input=false -var stage=v1 >/dev/null 2>&1
export TF_VAR_stage=v2
export TFSEE_TEXT_SCALE=1.4  # bigger text, for a video watched on phones
eval "$(tfsee hook zsh)"
clear
printf '\e]0;tfsee in Ghostty 1.4\a'  # window title, so the recording shows what's drawing it
prompt() { printf '\e[38;5;244mtfsee/examples/demo\e[0m \e[38;5;80m$\e[0m '; }
prompt
# For automated recording: hold here until the recorder removes this file.
while [ -f /tmp/tfsee_demo_wait ]; do sleep 0.1; done
sleep 0.6
cmd="terraform plan"
for ((i = 1; i <= ${#cmd}; i++)); do printf '%s' "${cmd[i]}"; sleep 0.05; done
sleep 0.3
echo
# Same as the hook (plan to .terraform/tfsee.tfplan, then tfsee), but Terraform's output is printed
# line by line so the recording shows it scrolling instead of appearing all at once.
mkdir -p .terraform
command terraform plan -compact-warnings -out=.terraform/tfsee.tfplan | while IFS= read -r line; do
  print -r -- "$line"; sleep 0.028
done
tfsee . --plan .terraform/tfsee.tfplan --quiet
prompt
sleep ${DEMO_HOLD:-30}
