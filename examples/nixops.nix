{
  network.description = "Proxmox network";

  # needed for nixops v2
  network.storage.legacy.databasefile = "~/.nixops/deployments.nixops";

  machine = { ... }:
    { deployment.targetEnv = "proxmox"; };
}
