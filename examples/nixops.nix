{
  network = {
    description = "Proxmox network";
    storage.legacy = {
      databasefile = "~/.nixops/deployments.nixops";
    };
  };

  machine = { config, pkgs, ... }:
    {
      deployment.targetEnv = "proxmox";
    };
}
