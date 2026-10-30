#!/bin/zsh
# Plays the demo for a screen recording: resets the demo infra to v1, then "types" and runs
# a plain `terraform plan` with the tfsee hook on, so the graph draws after terraform's output.
cd "${0:A:h}/../examples/demo" || exit 1
terraform apply -auto-approve -input=false >/dev/null 2>&1
eval "$(tfsee hook zsh)"
export TFSEE_TEXT_SCALE=1.4  # bigger text, for a video watched on phones
clear
printf '\e]0;tfsee in Ghostty 1.4\a'  # window title, so the recording shows what's drawing it
# For automated recording: hold here until the recorder removes this file.
while [ -f /tmp/tfsee_demo_wait ]; do sleep 0.1; done
prompt() { printf '\e[38;5;244mtfsee/examples/demo\e[0m \e[38;5;80m$\e[0m '; }
prompt
sleep 0.5
cmd="terraform plan -var stage=v2"
for ((i = 1; i <= ${#cmd}; i++)); do printf '%s' "${cmd[i]}"; sleep 0.03; done
sleep 0.25
echo
terraform plan -var stage=v2 -compact-warnings
prompt
sleep ${DEMO_HOLD:-30}
