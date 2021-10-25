from configparser import ConfigParser
import json
import os
import time
from typing import List, Literal
from urllib.parse import urljoin

from nixops import backends, deployment, resources, state, util
import requests
import urllib3


urllib3.disable_warnings()


GLOBAL_storage = "local"
GLOBAL_iso_url = "https://nixops-proxmox.s3.us-west-2.amazonaws.com/nixos-21.05.3896.b0274abf850-x86_64-linux.iso"
GLOBAL_iso_filename = "nixos-21.05.3896.b0274abf850-x86_64-linux.iso"


class ProxmoxVMOptions(resources.ResourceOptions):
    cores: int
    ide2: str
    memory: int
    net0: str
    nodename: str
    scsi0: str
    scsihw: str
    sockets: int


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
        self.cores = self.config.proxmox.cores
        self.ide2 = self.config.proxmox.ide2
        self.memory = self.config.proxmox.memory
        self.net0 = self.config.proxmox.net0
        self.nodename = self.config.proxmox.nodename
        self.scsi0 = self.config.proxmox.scsi0
        self.scsihw = self.config.proxmox.scsihw
        self.sockets = self.config.proxmox.sockets


class ProxmoxState(backends.MachineState[ProxmoxDefinition]):
    """State of a Proxmox machine."""

    url: str
    api_token: str
    nodename = util.attr_property("proxmox.nodename", None)
    client_public_key = util.attr_property("proxmox.clientPublicKey", None)
    private_ipv4 = util.attr_property("privateIpv4", None)
    client_private_key = util.attr_property("proxmox.clientPrivateKey", None)

    @classmethod
    def get_type(cls):
        return "proxmox"

    def __init__(self, depl: deployment.Deployment, name: str, id: state.RecordId):
        self._pve_config()
        super().__init__(depl, name, id)

    def _pve_has_iso(self) -> bool:
        pve = self._pve_session()
        response = pve.get(
            self._pve_url(
                f"/api2/json/nodes/{self.nodename}/storage/{GLOBAL_storage}/content"
            )
        )
        pve.close()

        if response.status_code != 200:
            return False

        data = json.loads(response.text)
        uploads = data["data"]
        if uploads is None:
            return False

        for upload in uploads:
            if upload["volid"] == f"{GLOBAL_storage}:iso/{GLOBAL_iso_filename}":
                return True

        return False

    def _pve_upload_iso(self):
        pve = self._pve_session()
        pve.post(
            self._pve_url(
                f"/api2/json/nodes/{self.nodename}/storage/{GLOBAL_storage}/download-url"
            ),
            params={
                "url": GLOBAL_iso_url,
                "filename": GLOBAL_iso_filename,
                "content": "iso",
            },
        )
        pve.close()

    def _pve_config(self):
        config = ConfigParser()
        config.read(os.path.join(os.path.expanduser("~"), ".proxmox", "credentials"))
        # TODO(jared): Use the `default` section as a fallback.
        self.url = config.get("default", "URL")
        self.api_token = config.get("default", "API_TOKEN")

    def _pve_session(self) -> requests.Session:
        session = requests.Session()
        session.verify = False
        session.adapters
        session.headers.update({"Authorization": f"PVEAPIToken={self.api_token}"})
        return session

    def _pve_url(self, path: str) -> str:
        return urljoin(self.url, path)

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
            self._pve_url(
                f"/api2/json/nodes/{self.nodename}/qemu/{self.vm_id}/status/current"
            )
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
            self._pve_url(
                f"/api2/json/nodes/{self.nodename}/qemu/{self.vm_id}/status/start"
            )
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
            self._pve_url(
                f"/api2/json/nodes/{self.nodename}/qemu/{self.vm_id}/status/{stop_type}"
            )
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
        response = pve.get(self._pve_url(f"/api2/json/nodes/{self.nodename}/qemu"))
        data = json.loads(response.text)
        pve.close()
        ids: List[int] = []
        if data["data"] is not None:
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

    def _pve_create(self, defn: ProxmoxDefinition) -> bool:
        pve = self._pve_session()

        vm_id = self._pve_next_vm_id()
        self.vm_id = str(vm_id)

        response = pve.post(
            self._pve_url(f"/api2/json/nodes/{defn.nodename}/qemu"),
            params={
                "agent": 1,
                "cores": defn.cores,
                "ide2": defn.ide2,
                "memory": defn.memory,
                "name": defn.name,
                "net0": defn.net0,
                "ostype": "l26",
                "scsi0": defn.scsi0,
                "scsihw": defn.scsihw,
                "sockets": defn.sockets,
                "start": 0,
                "vmid": vm_id,
            },
        )
        pve.close()
        if response.status_code != 200:
            return False

        return True

    def create(self, defn: ProxmoxDefinition, check, allow_reboot, allow_recreate):
        assert isinstance(defn, ProxmoxDefinition)
        self.set_common_state(defn)
        self.nodename = defn.nodename

        if not self.client_public_key:
            (self.client_private_key, self.client_public_key,) = util.create_key_pair()

        if not self.vm_id:
            has_iso = False
            downloading = False
            while not has_iso:
                has_iso = self._pve_has_iso()
                if has_iso:
                    break
                if not downloading:
                    self.log("ISO not found, uploading to Proxmox node...")
                    self._pve_upload_iso()
                    downloading = True
                time.sleep(5)

            self.log("Creating VM...")
            success = self._pve_create(defn)
            if not success:
                self.logger.error("Failed to create VM")
                return

            self._pve_start()

    def _pve_destroy(self) -> bool:
        pve = self._pve_session()
        response = pve.delete(
            self._pve_url(f"/api2/json/nodes/{self.nodename}/qemu/{self.vm_id}"),
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
                self._pve_url(
                    f"/api2/json/nodes/{self.nodename}/qemu/{self.vm_id}/status/shutdown"
                )
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
