# Deliberately wrong: an ephemeral value sent somewhere that would persist it. Both tools must refuse this.

ephemeral "random_password" "db" {
  length = 32
}

output "password" {
  value     = ephemeral.random_password.db.result
  sensitive = true
}
