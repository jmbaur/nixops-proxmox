{
  config_exporters = { optionalAttrs, pkgs, ... }: with pkgs.lib; [
    (config: { proxmox = optionalAttrs (config.deployment.targetEnv == "proxmox") config.deployment.proxmox; })
  ];
  options = [
    ./proxmox.nix
  ];
  resources = { ... }: { };
}
