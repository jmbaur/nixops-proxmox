import json
import time
from typing import Literal, Mapping, Optional, Sequence, Union
from urllib.parse import urljoin

from nixops import backends, deployment, known_hosts, nix_expr, resources, state, util
import requests
import urllib3


SATA_PORTS = 8


urllib3.disable_warnings()


def get_pve_url(path: str) -> str:
    return urljoin("https://192.168.1.2:8006", path)


def get_pve_session() -> requests.Session:
    session = requests.Session()
    session.verify = False
    session.adapters
    session.headers.update(
        {
            # TODO(jared): behind a firewall, just for development
            "Authorization": "PVEAPIToken=root@pam!nixops=9cdc3c5a-2d6e-4f4d-88f7-629534d97339"
        }
    )
    return session


class DiskOptions(resources.ResourceOptions):
    port: int
    size: int
    baseImage: Optional[str]


class ProxmoxVMOptions(resources.ResourceOptions):
    disks: Mapping[str, DiskOptions]
    memorySize: int
    vcpu: Optional[int]
    vmFlags: Sequence[str]


class ProxmoxOptions(backends.MachineOptions):
    proxmox: ProxmoxVMOptions


class ProxmoxDefinition(backends.MachineDefinition):
    """Definition of a Proxmox machine."""

    config: ProxmoxOptions

    @classmethod
    def get_type(cls):
        return "proxmox"

    def __init__(self, name, config):
        super().__init__(name, config)


class ProxmoxState(backends.MachineState[ProxmoxDefinition]):
    """State of a Proxmox machine."""

    private_ipv4 = util.attr_property("privateIpv4", None)
    client_public_key = util.attr_property("libvirtd.clientPublicKey", None)
    client_private_key = util.attr_property("libvirtd.clientPrivateKey", None)
    primary_net = util.attr_property("libvirtd.primaryNet", None)
    primary_mac = util.attr_property("libvirtd.primaryMAC", None)
    domain_xml = util.attr_property("libvirtd.domainXML", None)
    disk_path = util.attr_property("libvirtd.diskPath", None)
    storage_volume_name = util.attr_property("libvirtd.storageVolume", None)
    storage_pool_name = util.attr_property("libvirtd.storagePool", None)
    vcpu = util.attr_property("libvirtd.vcpu", None)

    @classmethod
    def get_type(cls):
        return "proxmox"

    def __init__(self, depl: deployment.Deployment, name: str, id: state.RecordId):
        super().__init__(depl, name, id)
        self._disk_attached = False

    def get_ssh_private_key_file(self):
        return self._ssh_private_key_file or self.write_ssh_private_key(
            self.client_private_key
        )

    def get_ssh_flags(self, *args, **kwargs):
        super_flags = super(ProxmoxState, self).get_ssh_flags(*args, **kwargs)
        return super_flags + [
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-i",
            self.get_ssh_private_key_file(),
        ]

    def get_physical_spec(self):
        return {
            ("users", "extraUsers", "root", "openssh", "authorizedKeys", "keys"): [
                self.client_public_key
            ]
        }

    def address_to(self, m):
        if isinstance(m, ProxmoxState):
            return m.private_ipv4
        return backends.MachineState.address_to(self, m)

    def _vm_id(self):
        return "nixops-{0}-{1}".format(self.depl.uuid, self.name)

    def _get_vm_status(self) -> Literal["running", "stopped", "nonexistant", None]:
        """Return the status ("running", etc.) of a VM."""
        pve = get_pve_session()
        response = pve.get(get_pve_url("/api2/json/nodes/pve/qemu/602/status/current"))
        if response.status_code != 200:
            return "nonexistant"

        data = json.loads(response.text)
        status = data["data"]["status"]
        expects = ["running", "stopped"]
        if status not in expects:
            self.logger.error(
                f"Invalid proxmox response: expected {expects}, got {status}"
            )
            return None

        return status

    def _start(self) -> bool:
        pve = get_pve_session()
        response = pve.post(get_pve_url("/api2/json/nodes/pve/qemu/602/status/start"))
        pve.close()
        if response.status_code != 200:
            return False
        self.state = self.STARTING
        return True

    def _stop(self, *, stop_type: Literal["stop", "shutdown"]) -> bool:
        if self.state == self.STOPPED:
            return True

        pve = get_pve_session()
        response = pve.post(
            get_pve_url(f"/api2/json/nodes/pve/qemu/602/status/{stop_type}")
        )
        if response.status_code != 200:
            return False

        self.state = self.STOPPING
        while True:
            if self._get_vm_status() == "stopped":
                break
            time.sleep(1)

        self.state = self.STOPPED
        return True

    def _update_ip(self):
        pass

    #     res = self._logged_exec(
    #         [
    #             "VBoxManage",
    #             "guestproperty",
    #             "get",
    #             self.vm_id,
    #             "/Proxmox/GuestInfo/Net/1/V4/IP",
    #         ],
    #         capture_stdout=True,
    #     ).rstrip()
    #     if res[0:7] != "Value: ":
    #         return
    #     new_address = res[7:]
    #     known_hosts.update(self.private_ipv4, new_address, self.public_host_key)
    #     self.private_ipv4 = new_address

    def _update_disk(self, name, state):
        pass

    #     disks = self.disks
    #     if state is None:
    #         disks.pop(name, None)
    #     else:
    #         disks[name] = state
    #     self.disks = disks

    def _wait_for_ip(self):
        pass

    #     self.log_start("waiting for IP address...")
    #     while True:
    #         self._update_ip()
    #         if self.private_ipv4 is not None:
    #             break
    #         time.sleep(1)
    #         self.log_continue(".")
    #     self.log_end(" " + self.private_ipv4)

    def _create(self) -> bool:
        pve = get_pve_session()
        response = pve.post(
            get_pve_url("/api2/json/nodes/pve/qemu"),
            params={
                "vmid": 602,
                "agent": "enabled=1",
                "description": "TODO",  # shows up in "Notes" section
                "name": "TODO",
                "ostype": "l26",
                "start": 0,  # TODO(jared): set to 1
            },
        )
        pve.close()
        if response.status_code != 200:
            return False

        return True

    def create(self, defn: ProxmoxDefinition, check, allow_reboot, allow_recreate):
        assert isinstance(defn, ProxmoxDefinition)
        self.set_common_state(defn)

        if not self.client_public_key:
            (self.client_private_key, self.client_public_key,) = util.create_key_pair()

        if not self.vm_id:
            self.log("Creating VM...")
            success = self._create()
            if not success:
                self.logger.error("Failed to create VM")
                return

            self.vm_id = self._vm_id()
            self._start()

    def destroy(self, wipe: bool = False) -> bool:
        if not self.vm_id:
            return True

        if not self.depl.logger.confirm(
            f"are you sure you want to destroy Proxmox VM ‘{self.name}’?"
        ):
            return False

        self.log("destroying VM...")

        pve = get_pve_session()
        status = self._get_vm_status()
        if status == "nonexistant":
            self.log("VM does not exist")
            self.state = self.MISSING
            return True

        if self.state != self.STOPPED:
            success = self._stop(stop_type="stop")
            if not success:
                self.logger.error("Could not stop VM")
                return False

        response = pve.delete(
            get_pve_url("/api2/json/nodes/pve/qemu/602"),
            params={"purge": 1, "destroy-unreferenced-disks": 1},
        )
        if response.status_code != 200:
            self.logger.error("Failed to destroy VM")
            return False

        pve.close()

        self.state = self.MISSING
        return True

    def stop(self):
        assert self.vm_id
        success = self._stop(stop_type="shutdown")
        if not success:
            self.logger.error("Could not stop VM")
            return
        state = self._get_vm_status()
        if state == "running":
            self.log_start("shutting down... ")
            pve = get_pve_session()
            response = pve.post(
                get_pve_url("/api2/json/nodes/pve/qemu/602/status/shutdown")
            )
            pve.close()
            if response.status_code != 200:
                self.logger.error("Failed to stop VM")
                return

            self.state = self.STOPPING
            while True:
                state = self._get_vm_status()
                self.log_continue(f"[{state}] ")
                if state == "stopped":
                    break
                time.sleep(1)
                self.log_end("")
        self.state = self.STOPPED
        self.ssh_master = None

    def start(self):
        if self._get_vm_status() == "running":
            return
        self.log("Starting...")
        prev_ipv4 = self.private_ipv4
        self._start()
        self._wait_for_ip()
        self.ssh_pinged = False
        self._ssh_pinged_this_time = False
        if prev_ipv4 != self.private_ipv4:
            self.warn("IP address has changed, you may need to run ‘nixops deploy’")
        self.wait_for_ssh(check=True)

    def _check(self, res):
        if not self.vm_id:
            res.exists = False
            return
        state = self._get_vm_status(can_fail=True)
        if state is None:
            with self.depl._db:
                self.vm_id = None
                self.private_ipv4 = None
                self.sata_controller_created = False
                self.public_host_key = None
                self.private_host_key = None
                self.disks = {}
                self.state = self.MISSING
                return

        res.exists = True
        self.log(f"VM state is ‘{state}’")
        if state == "poweroff" or state == "aborted":
            res.is_up = False
            self.state = self.STOPPED
        elif state == "running":
            res.is_up = True
            self._update_ip()
            backends.MachineState._check(self, res)
        else:
            self.state = self.UNKNOWN
