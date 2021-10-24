{ config, pkgs, lib, ... }:

with lib;

let

  # Do the fetching and unpacking of the VirtualBox guest image
  # locally so that it works on non-Linux hosts.
  pkgsNative = import <nixpkgs> { system = builtins.currentSystem; };

  cfg = config.deployment.proxmox;

in

{

  ###### interface

  options = {

    deployment.proxmox.vcpu = mkOption {
      type = types.int;
      default = 1;
      description = ''
        Number of Virtual CPUs.
      '';
    };

  };


  ###### implementation

  config = mkIf (config.deployment.targetEnv == "proxmox") {
    # TODO(jared): determine what this means
    # deployment.hasFastConnection = true;
  };

}
