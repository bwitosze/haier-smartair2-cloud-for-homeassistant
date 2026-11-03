"""Cloud transport: persistent MQTT connection to the Haier uSDK gateway.

Reproduces the uSDK gateway handshake reverse-engineered from liball-in-one.so:
login -> master-gw request -> MQTT 3.1 CONNECT with AES-signed credentials ->
boundDevs registration -> EPP frames over ``User/<token>/Ext/{Req,Push}/<devId>``.

One client multiplexes all cloud devices on a single long-lived connection, like
the app. The access token is a short-lived TGT ticket, refreshed periodically and
on ``invalidToken`` by a full reconnect (topics embed the token).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import socket
import ssl
import struct
from collections.abc import Callable

import paho.mqtt.client as mqtt
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    APP_ID,
    APP_KEY,
    APP_VERSION,
    AUTH_SALT,
    LOGIN_HOST,
    LOGIN_PORT,
    MASTER_GW_PORT,
    REST_CLIENT_ID,
    TOKEN_REFRESH_SECONDS,
    generate_client_id,
)

_LOGGER = logging.getLogger(__name__)


def _insecure_ctx() -> ssl.SSLContext:
    # bare context: create_default_context() loads the CA store from disk, which is a
    # blocking call in the event loop - and verification is disabled here anyway
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _make_auth() -> tuple[str, str]:
    """username = '01'+8-digit nonce, password = hex(AES128CBC(MD5(nonce), '<len>haier_sdk')).

    Recipe from uss_encrpyt_user_auth / uss_encrpyt_aes128.
    """
    nonce = ""
    while len(nonce) < 8:
        nonce += str(os.urandom(1)[0])
    nonce = nonce[:8]
    key = hashlib.md5(nonce.encode()).digest()
    pt = bytearray(16)
    struct.pack_into(">H", pt, 0, len(AUTH_SALT))
    pt[2 : 2 + len(AUTH_SALT)] = AUTH_SALT
    enc = Cipher(algorithms.AES(key), modes.CBC(b"\x00" * 16)).encryptor()
    ct = enc.update(bytes(pt)) + enc.finalize()
    return "01" + nonce, ct.hex()


class HaierCloudClient:
    """Single persistent MQTT connection multiplexing all cloud devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        gateway: str,
        app_client_id: str | None = None,
    ) -> None:
        self._hass = hass
        self._username = username
        self._password = password
        self._gateway = gateway
        self._app_client_id = app_client_id or generate_client_id()
        self._token: str | None = None
        self._client: mqtt.Client | None = None
        self._broker_port: int | None = None
        self._devices: set[str] = set()
        self._frames: dict[str, bytes] = {}
        self._online: dict[str, bool] = {}
        self._listeners: list[Callable[[], None]] = []
        self._sn = 100
        self._lock = asyncio.Lock()
        self._reconnecting = False
        self._stopped = False
        self._refresh_unsub: asyncio.TimerHandle | None = None

    # -------------------------------------------------------------- registration

    def register_device(self, devid: str) -> None:
        self._devices.add(devid.upper())

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return remove

    def latest_frame(self, devid: str) -> bytes | None:
        return self._frames.get(devid.upper())

    def is_online(self, devid: str) -> bool:
        return self._online.get(devid.upper(), False)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("listener failed")

    # --------------------------------------------------------------------- REST

    async def async_login(self) -> str:
        session = async_get_clientsession(self._hass)
        body = {
            "loginId": self._username,
            "password": self._password,
            "accType": 0,
            "loginType": 2,
            "sequenceId": "20260101000000000000",
        }
        headers = {
            "appKey": APP_KEY,
            "appId": APP_ID,
            "appVersion": APP_VERSION,
            "clientId": REST_CLIENT_ID,
            "Content-Type": "application/json;charset=utf-8",
            "Accept": "application/json",
        }
        url = f"https://{LOGIN_HOST}:{LOGIN_PORT}/uhome/acbiz/login"
        async with session.post(url, data=json.dumps(body), headers=headers, ssl=False) as resp:
            data = await resp.json(content_type=None)
        if data.get("retCode") != "00000" or not data.get("accessToken"):
            raise CloudAuthError(f"login failed: {data.get('retCode')} {data.get('retInfo')}")
        self._token = data["accessToken"]
        return self._token

    async def async_get_devices(self) -> list[dict]:
        """Return [{id, name, type}] from get_userDevlist."""
        if not self._token:
            await self.async_login()
        session = async_get_clientsession(self._hass)
        headers = {
            "appKey": APP_KEY,
            "appId": APP_ID,
            "appVersion": APP_VERSION,
            "clientId": REST_CLIENT_ID,
            "accessToken": self._token,
            "Content-Type": "application/json;charset=utf-8",
            "Accept": "application/json",
        }
        body = {"get_devlist_info": {"sctx": {"appId": APP_ID, "appVersion": APP_VERSION, "clientId": REST_CLIENT_ID}}}
        url = f"https://{LOGIN_HOST}:{LOGIN_PORT}/uhome/acbiz/device/v25/get_userDevlist"
        async with session.post(url, data=json.dumps(body), headers=headers, ssl=False) as resp:
            data = await resp.json(content_type=None)
        out: list[dict] = []
        for city in data.get("cityListResult") or []:
            for room in city.get("roomDeviceResultList") or []:
                for d in room.get("deviceList") or []:
                    out.append(
                        {
                            "id": d.get("id"),
                            "name": d.get("name") or d.get("id"),
                            "type": (d.get("type") or {}).get("typeIdentifier"),
                            "online": (d.get("status") or {}).get("online"),
                        }
                    )
        return out

    def _master_gw_blocking(self) -> int:
        j = json.dumps(
            {
                "protocolVers": "1.0.0",
                "clientId": self._app_client_id,
                "connType": "MqttUSdk",
                "svcVers": "0.0.0",
                "libVers": "0.0.0",
                "userAGpType": "UCP-MQTT-UACP",
                "userAGpVers": "1.2.0",
            }
        ).encode()
        hdr = bytearray(8)
        hdr[1] = 1
        struct.pack_into(">H", hdr, 2, 1)
        struct.pack_into(">H", hdr, 6, len(j))
        with socket.create_connection((self._gateway, MASTER_GW_PORT), timeout=8) as s:
            with _insecure_ctx().wrap_socket(s, server_hostname=self._gateway) as ss:
                ss.sendall(bytes(hdr) + j)
                data = b""
                while len(data) < 8:
                    data += ss.recv(4096)
                ln = struct.unpack(">H", data[6:8])[0]
                while len(data) < 8 + ln:
                    data += ss.recv(4096)
                return json.loads(data[8 : 8 + ln])["port"]

    # ------------------------------------------------------------------- start

    async def async_start(self) -> None:
        await self._connect()
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self._stopped:
            return
        loop = self._hass.loop
        self._refresh_unsub = loop.call_later(
            TOKEN_REFRESH_SECONDS,
            lambda: self._hass.async_create_background_task(self._reconnect("token refresh"), "haier_cloud_reconnect"),
        )

    async def _connect(self) -> None:
        async with self._lock:
            await self.async_login()
            self._broker_port = await self._hass.async_add_executor_job(self._master_gw_blocking)
            username, password = _make_auth()
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id="HA" + os.urandom(8).hex().upper(),
                protocol=mqtt.MQTTv31,
            )
            client.username_pw_set(username, password)
            client.tls_set_context(_insecure_ctx())
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.on_disconnect = self._on_disconnect
            self._client = client
            await self._hass.async_add_executor_job(
                client.connect, self._gateway, self._broker_port, 30
            )
            client.loop_start()

    async def _reconnect(self, reason: str) -> None:
        if self._stopped or self._reconnecting:
            return
        self._reconnecting = True
        _LOGGER.info("Haier cloud reconnect: %s", reason)
        try:
            if self._client:
                try:
                    self._client.loop_stop()
                    self._client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            await asyncio.sleep(2)
            await self._connect()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("reconnect failed; retrying in 30s")
            self._hass.loop.call_later(
                30, lambda: self._hass.async_create_background_task(self._reconnect("retry"), "haier_cloud_reconnect")
            )
        finally:
            self._reconnecting = False
            self._schedule_refresh()

    # --------------------------------------------------------------- callbacks

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if getattr(reason_code, "value", reason_code) != 0:
            _LOGGER.warning("Haier cloud CONNACK rc=%s", reason_code)
            return
        token = self._token
        client.subscribe(
            [(f"Client/{self._app_client_id}/Business/Down", 0), (f"User/{token}/#", 0)]
        )
        self._sn += 1
        data = base64.b64encode(json.dumps({"sn": str(self._sn)}).encode()).decode()
        client.publish(
            f"Client/{self._app_client_id}/Business/Up",
            json.dumps({"type": "boundDevs", "data": data, "tokens": [token]}),
        )
        # kick a status poll for every managed device
        from .codec import POLL_FRAME

        for devid in self._devices:
            self._publish_epp(devid, POLL_FRAME)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if self._stopped:
            return
        _LOGGER.info("Haier cloud disconnected rc=%s", reason_code)
        self._hass.loop.call_soon_threadsafe(
            lambda: self._hass.async_create_background_task(self._reconnect("disconnect"), "haier_cloud_reconnect")
        )

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload)
        except Exception:  # noqa: BLE001
            return
        if payload.get("event") == "invalidToken":
            self._hass.loop.call_soon_threadsafe(
                lambda: self._hass.async_create_background_task(self._reconnect("invalidToken"), "haier_cloud_reconnect")
            )
            return
        if payload.get("type") == "boundDevs" and payload.get("data"):
            try:
                inner = json.loads(base64.b64decode(payload["data"]))
            except Exception:  # noqa: BLE001
                return
            for d in inner.get("devs") or []:
                self._online[str(d.get("id", "")).upper()] = bool(d.get("ol"))
            self._hass.loop.call_soon_threadsafe(self._notify)
            return
        if payload.get("type") == "epp" and payload.get("data"):
            # topic: User/<token>/Ext/Push/<devId>
            devid = msg.topic.rsplit("/", 1)[-1].upper()
            try:
                frame = base64.b64decode(payload["data"])
            except Exception:  # noqa: BLE001
                return
            if len(frame) >= 12 and frame[9] in (0x02, 0x06):
                self._frames[devid] = frame
                self._online[devid] = True
                self._hass.loop.call_soon_threadsafe(self._notify)

    # ------------------------------------------------------------------ publish

    def _publish_epp(self, devid: str, frame: bytes) -> None:
        if not self._client or not self._token:
            return
        self._sn += 1
        self._client.publish(
            f"User/{self._token}/Ext/Req/{devid.upper()}",
            json.dumps(
                {"sn": str(self._sn), "type": "epp", "data": base64.b64encode(frame).decode()}
            ),
        )

    async def async_poll(self, devid: str) -> None:
        from .codec import POLL_FRAME

        await self._hass.async_add_executor_job(self._publish_epp, devid, POLL_FRAME)

    async def async_send_frame(self, devid: str, frame: bytes) -> None:
        await self._hass.async_add_executor_job(self._publish_epp, devid, frame)

    async def async_stop(self) -> None:
        self._stopped = True
        if self._refresh_unsub:
            self._refresh_unsub.cancel()
        if self._client:
            await self._hass.async_add_executor_job(self._client.loop_stop)
            try:
                self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass


class CloudAuthError(Exception):
    """Login/token failure."""
