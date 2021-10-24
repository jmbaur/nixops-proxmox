import json
import time
from typing import Dict, Literal, List
from urllib.parse import urljoin

from nixops import backends, deployment, known_hosts, nix_expr, resources, state, util
import requests
import urllib3


SATA_PORTS = 8


urllib3.disable_warnings()


class ProxmoxVMOptions(resources.ResourceOptions):
    vcpu: int
    # baseImage: Optional[str]
    # baseImageSize: int
    # cmdline: str
    # domainType: str
    # extraDevicesXML: str
    # extraDomainXML: str
    # headless: bool
    # initrd: str
    # kernel: str
    # memorySize: int
    # networks: Sequence[str]
    # storagePool: str


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

    client_public_key = util.attr_property("proxmox.clientPublicKey", None)
    vcpu = util.attr_property("proxmox.vcpu", None)
    private_ipv4 = util.attr_property("privateIpv4", None)
    client_private_key = util.attr_property("proxmox.clientPrivateKey", None)
    # primary_net = util.attr_property("proxmox.primaryNet", None)
    # primary_mac = util.attr_property("proxmox.primaryMAC", None)
    # domain_xml = util.attr_property("proxmox.domainXML", None)
    # disk_path = util.attr_property("proxmox.diskPath", None)
    # storage_volume_name = util.attr_property("proxmox.storageVolume", None)
    # storage_pool_name = util.attr_property("proxmox.storagePool", None)

    @classmethod
    def get_type(cls):
        return "proxmox"

    def __init__(self, depl: deployment.Deployment, name: str, id: state.RecordId):
        super().__init__(depl, name, id)

    def _pve_session(self) -> requests.Session:
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

    def _pve_url(self, path: str) -> str:
        return urljoin("https://192.168.1.2:8006", path)

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

    def get_ssh_name(self):
        # TODO(jared): figure this out
        # self.private_ipv4 = self._parse_ip()
        return self.private_ipv4

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
        pve = self._pve_session()
        response = pve.get(
            self._pve_url(f"/api2/json/nodes/pve/qemu/{self.vm_id}/status/current")
        )
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

    def _pve_start(self) -> bool:
        pve = self._pve_session()
        response = pve.post(
            self._pve_url(f"/api2/json/nodes/pve/qemu/{self.vm_id}/status/start")
        )
        pve.close()
        if response.status_code != 200:
            return False
        self.state = self.STARTING
        return True

    def _pve_stop(self, *, stop_type: Literal["stop", "shutdown"]) -> bool:
        if self.state == self.STOPPED:
            return True

        pve = self._pve_session()
        response = pve.post(
            self._pve_url(f"/api2/json/nodes/pve/qemu/{self.vm_id}/status/{stop_type}")
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

    def _wait_for_ip(self):
        pass

    def _pve_next_vm_id(self) -> int:
        pve = self._pve_session()
        response = pve.get(self._pve_url("/api2/json/nodes/pve/qemu"))
        data = json.loads(response.text)
        pve.close()
        ids: List[int] = []
        for vm in data["data"]:
            ids.append(vm["vmid"])

        ids.sort()
        lowest: int = 100
        for id in ids:
            if id == lowest:
                lowest += 1
            else:
                break

        return lowest

    def _pve_create(self) -> bool:
        pve = self._pve_session()

        vm_id = self._pve_next_vm_id()
        self.vm_id = str(vm_id)

        response = pve.post(
            self._pve_url("/api2/json/nodes/pve/qemu"),
            params={
                "vmid": vm_id,
                "agent": "enabled=1",
                "description": "TODO",
                "name": "TODO",
                "ostype": "l26",
                "start": 0,
                "cores": self.vcpu,
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
            success = self._pve_create()
            if not success:
                self.logger.error("Failed to create VM")
                return

            self._pve_start()

    def _pve_destroy(self) -> bool:
        pve = self._pve_session()
        response = pve.delete(
            self._pve_url(f"/api2/json/nodes/pve/qemu/{self.vm_id}"),
            params={"purge": 1, "destroy-unreferenced-disks": 1},
        )
        pve.close()
        if response.status_code != 200:
            return False

        return True

    def destroy(self, wipe: bool = False) -> bool:
        if not self.vm_id:
            return True

        if not self.depl.logger.confirm(
            f"are you sure you want to destroy Proxmox VM ‘{self.name}’?"
        ):
            return False

        self.log("destroying VM...")

        if self._get_vm_status() == "nonexistant":
            self.log("VM does not exist")
            self.state = self.MISSING
            return True

        success = self._pve_stop(stop_type="stop")
        if not success:
            self.logger.error("Could not stop VM")
            return False

        success = self._pve_destroy()
        if not success:
            self.logger.error("could not delete VM")
            return False

        return True

    def stop(self):
        assert self.vm_id
        success = self._pve_stop(stop_type="shutdown")
        if not success:
            self.logger.error("Could not stop VM")
            return
        state = self._get_vm_status()
        if state == "running":
            self.log_start("shutting down... ")
            pve = self._pve_session()
            response = pve.post(
                self._pve_url(f"/api2/json/nodes/pve/qemu/{self.vm_id}/status/shutdown")
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
        self._pve_start()
        self._wait_for_ip()
        self.ssh_pinged = False
        self._ssh_pinged_this_time = False
        if prev_ipv4 != self.private_ipv4:
            self.warn("IP address has changed, you may need to run ‘nixops deploy’")
        self.wait_for_ssh(check=True)
