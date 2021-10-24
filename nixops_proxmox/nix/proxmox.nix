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

    deployment.proxmox.cores = mkOption {
      type = types.int;
      default = 1;
      description = ''
        The number of cores per socket.
      '';
    };

    deployment.proxmox.ide2 = mkOption {
      type = types.str;
      default = "none,media=cdrom";
      description = ''
        Use volume as IDE hard disk or CD-ROM (n is 0 to 3). Use the special syntax STORAGE_ID:SIZE_IN_GB to allocate a new volume.
      '';
    };

    deployment.proxmox.memory = mkOption {
      type = types.int;
      default = 512;
      description = ''
        Amount of RAM for the VM in MB. This is the maximum available memory
        when you use the balloon device.
      '';
    };

    # TODO(jared): Make this a list and expand options.
    deployment.proxmox.net0 = mkOption {
      type = types.str;
      default = "virtio,bridge=vmbr0,firewall=1";
      description = ''
        Specify network devices.
      '';
    };

    deployment.proxmox.nodename = mkOption {
      type = types.str;
      default = "pve";
      description = ''
        Name of node.
      '';
    };

    deployment.proxmox.scsi0 = mkOption {
      type = types.str;
      default = "local-lvm:32";
      description = ''
        Use volume as SCSI hard disk or CD-ROM (n is 0 to 30). Use the special
        syntax STORAGE_ID:SIZE_IN_GB to allocate a new volume.
      '';
    };

    deployment.proxmox.scsihw = mkOption {
      type = types.enum [ "lsi" "lsi53c810" "virtio-scsi-pci" "virtio-scsi-single" "megasus" "pvscsi" ];
      default = "virtio-scsi-pci";
      description = ''
        SCSI controller model
      '';
    };

    deployment.proxmox.sockets = mkOption {
      type = types.int;
      default = 1;
      description = ''
        The number of CPU sockets.
      '';
    };

  };

  ###### implementation

  config = mkIf (config.deployment.targetEnv == "proxmox") {
    # TODO(jared): determine what this means
    # deployment.hasFastConnection = true;

    deployment.proxmox.cores = 4;
  };

}
