# A tiny "web app" made only of terraform_data resources: no cloud, no credentials,
# no provider downloads. Apply it with stage=v1, then plan stage=v2 to get every
# kind of change: create, update, destroy, replace, and no-op.
#
#   terraform init && terraform apply -auto-approve
#   tfsee . -var stage=v2

variable "stage" {
  type    = string
  default = "v1"
}

locals {
  v2 = var.stage == "v2"
}

resource "terraform_data" "network" {
  input = "10.0.0.0/16"
}

resource "terraform_data" "subnet" {
  count = 2
  input = "${terraform_data.network.output}/subnet-${count.index}"
}

# v2 bumps the engine version: an in-place update.
resource "terraform_data" "database" {
  input      = local.v2 ? "postgres-17" : "postgres-16"
  depends_on = [terraform_data.subnet]
}

# v2 drops the cache: a destroy.
resource "terraform_data" "cache" {
  count      = local.v2 ? 0 : 1
  input      = "redis-7"
  depends_on = [terraform_data.subnet]
}

# v2 adds a queue: a create.
resource "terraform_data" "queue" {
  count      = local.v2 ? 1 : 0
  input      = "jobs"
  depends_on = [terraform_data.subnet]
}

# v2 ships a new build: the app servers get replaced.
resource "terraform_data" "app" {
  count            = 2
  input            = "app-${count.index}"
  triggers_replace = local.v2 ? "build-42" : "build-41"
  depends_on       = [terraform_data.database, terraform_data.cache, terraform_data.queue]
}

resource "terraform_data" "load_balancer" {
  input = [for a in terraform_data.app : a.id]
}

resource "terraform_data" "dns" {
  input = "app.example.com"
  depends_on = [terraform_data.load_balancer]
}

# v2 adds monitoring on the load balancer: another create.
resource "terraform_data" "alerts" {
  count = local.v2 ? 1 : 0
  input = terraform_data.load_balancer.id
}
