"""NVR Discovery module - Auto-discover cameras from various NVR brands."""

import asyncio
import aiohttp
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import base64
import hashlib
import time

logger = logging.getLogger(__name__)


class NVRBrand(str, Enum):
    HIKVISION = "hikvision"
    DAHUA = "dahua"
    UNIVIEW = "uniview"
    AXIS = "axis"
    MILESIGHT = "milesight"
    BOSCH = "bosch"
    HANWHA = "hanwha"  # Samsung Wisenet
    ONVIF = "onvif"  # Generic ONVIF
    AUTO = "auto"  # Auto-detect


@dataclass
class DiscoveredCamera:
    """Represents a discovered camera/channel."""
    channel_id: int
    name: str
    rtsp_url_main: str
    rtsp_url_sub: Optional[str] = None
    resolution: Optional[str] = None
    status: str = "online"
    model: Optional[str] = None
    serial: Optional[str] = None


@dataclass
class NVRInfo:
    """Information about the discovered NVR."""
    brand: str
    model: Optional[str] = None
    serial: Optional[str] = None
    firmware: Optional[str] = None
    channels: int = 0
    cameras: List[DiscoveredCamera] = field(default_factory=list)
    error: Optional[str] = None


class NVRDiscovery:
    """Discover cameras from NVR devices."""

    def __init__(self):
        self.timeout = aiohttp.ClientTimeout(total=15)

    async def discover(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 80,
        rtsp_port: int = 554,
        brand: str = "auto"
    ) -> NVRInfo:
        """
        Discover cameras from an NVR.

        Args:
            host: NVR IP address or hostname
            username: Admin username
            password: Admin password
            port: HTTP port (default 80)
            rtsp_port: RTSP port (default 554)
            brand: NVR brand or "auto" for auto-detection

        Returns:
            NVRInfo with discovered cameras
        """
        if brand == "auto" or brand == NVRBrand.AUTO:
            brand = await self._detect_brand(host, port, username, password)
            if not brand:
                return NVRInfo(brand="unknown", error="Could not detect NVR brand. Please select manually.")

        logger.info(f"Discovering cameras from {brand} NVR at {host}")

        try:
            if brand == NVRBrand.HIKVISION:
                return await self._discover_hikvision(host, port, rtsp_port, username, password)
            elif brand == NVRBrand.DAHUA:
                return await self._discover_dahua(host, port, rtsp_port, username, password)
            elif brand == NVRBrand.UNIVIEW:
                return await self._discover_uniview(host, port, rtsp_port, username, password)
            elif brand == NVRBrand.AXIS:
                return await self._discover_axis(host, port, rtsp_port, username, password)
            elif brand == NVRBrand.MILESIGHT:
                return await self._discover_milesight(host, port, rtsp_port, username, password)
            elif brand == NVRBrand.BOSCH:
                return await self._discover_bosch(host, port, rtsp_port, username, password)
            elif brand == NVRBrand.HANWHA:
                return await self._discover_hanwha(host, port, rtsp_port, username, password)
            elif brand == NVRBrand.ONVIF:
                return await self._discover_onvif(host, port, rtsp_port, username, password)
            else:
                return NVRInfo(brand=brand, error=f"Unsupported NVR brand: {brand}")
        except Exception as e:
            logger.exception(f"Error discovering NVR: {e}")
            return NVRInfo(brand=brand, error=str(e))

    async def _detect_brand(self, host: str, port: int, username: str, password: str) -> Optional[str]:
        """Auto-detect NVR brand by probing various endpoints."""
        checks = [
            (self._check_hikvision, NVRBrand.HIKVISION),
            (self._check_dahua, NVRBrand.DAHUA),
            (self._check_uniview, NVRBrand.UNIVIEW),
            (self._check_axis, NVRBrand.AXIS),
            (self._check_milesight, NVRBrand.MILESIGHT),
        ]

        for check_func, brand in checks:
            try:
                if await check_func(host, port, username, password):
                    logger.info(f"Detected NVR brand: {brand}")
                    return brand
            except Exception as e:
                logger.debug(f"Brand check failed for {brand}: {e}")
                continue

        return None

    async def _check_hikvision(self, host: str, port: int, username: str, password: str) -> bool:
        """Check if device is Hikvision."""
        url = f"http://{host}:{port}/ISAPI/System/deviceInfo"
        auth = aiohttp.BasicAuth(username, password)
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url, auth=auth, ssl=False) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    return "hikvision" in text.lower() or "DeviceInfo" in text
        return False

    async def _check_dahua(self, host: str, port: int, username: str, password: str) -> bool:
        """Check if device is Dahua."""
        url = f"http://{host}:{port}/cgi-bin/magicBox.cgi?action=getDeviceType"
        auth = aiohttp.helpers.BasicAuth(username, password)
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url, auth=auth, ssl=False) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    return "type=" in text.lower()
        return False

    async def _check_uniview(self, host: str, port: int, username: str, password: str) -> bool:
        """Check if device is Uniview."""
        url = f"http://{host}:{port}/LAPI/V1.0/System/DeviceInfo"
        auth = aiohttp.BasicAuth(username, password)
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url, auth=auth, ssl=False) as resp:
                if resp.status == 200:
                    return True
        return False

    async def _check_axis(self, host: str, port: int, username: str, password: str) -> bool:
        """Check if device is Axis."""
        url = f"http://{host}:{port}/axis-cgi/basicdeviceinfo.cgi"
        auth = aiohttp.BasicAuth(username, password)
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url, auth=auth, ssl=False) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    return "axis" in text.lower() or "Brand" in text
        return False

    async def _check_milesight(self, host: str, port: int, username: str, password: str) -> bool:
        """Check if device is Milesight."""
        url = f"http://{host}:{port}/api/system/info"
        auth = aiohttp.BasicAuth(username, password)
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url, auth=auth, ssl=False) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    return "milesight" in text.lower()
        return False

    # ==================== HIKVISION ====================
    async def _discover_hikvision(
        self, host: str, port: int, rtsp_port: int, username: str, password: str
    ) -> NVRInfo:
        """Discover cameras from Hikvision NVR using ISAPI."""
        info = NVRInfo(brand=NVRBrand.HIKVISION)
        auth = aiohttp.BasicAuth(username, password)

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            # Get device info
            try:
                url = f"http://{host}:{port}/ISAPI/System/deviceInfo"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        info.model = self._extract_xml_value(text, "model")
                        info.serial = self._extract_xml_value(text, "serialNumber")
                        info.firmware = self._extract_xml_value(text, "firmwareVersion")
            except Exception as e:
                logger.warning(f"Failed to get Hikvision device info: {e}")

            # Get channel count and status
            try:
                url = f"http://{host}:{port}/ISAPI/ContentMgmt/InputProxy/channels"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        channels = re.findall(r"<InputProxyChannel>.*?</InputProxyChannel>", text, re.DOTALL)
                        info.channels = len(channels)

                        for ch_xml in channels:
                            ch_id = self._extract_xml_value(ch_xml, "id")
                            ch_name = self._extract_xml_value(ch_xml, "name") or f"Channel {ch_id}"
                            ch_status = self._extract_xml_value(ch_xml, "online")

                            if ch_id:
                                camera = DiscoveredCamera(
                                    channel_id=int(ch_id),
                                    name=ch_name,
                                    rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/Streaming/Channels/{ch_id}01",
                                    rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/Streaming/Channels/{ch_id}02",
                                    status="online" if ch_status == "true" else "offline"
                                )
                                info.cameras.append(camera)
            except Exception as e:
                logger.warning(f"Failed to get Hikvision channels via InputProxy: {e}")

            # Fallback: Try streaming channels directly
            if not info.cameras:
                try:
                    url = f"http://{host}:{port}/ISAPI/Streaming/channels"
                    async with session.get(url, auth=auth, ssl=False) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            # Parse channel IDs (format: 101, 102, 201, 202 where first digit is channel)
                            channel_ids = set()
                            for match in re.finditer(r"<id>(\d+)</id>", text):
                                ch_id = match.group(1)
                                if ch_id.endswith("01"):  # Main stream
                                    channel_ids.add(int(ch_id[:-2]))

                            for ch_id in sorted(channel_ids):
                                camera = DiscoveredCamera(
                                    channel_id=ch_id,
                                    name=f"Camera {ch_id}",
                                    rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/Streaming/Channels/{ch_id}01",
                                    rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/Streaming/Channels/{ch_id}02",
                                )
                                info.cameras.append(camera)
                            info.channels = len(channel_ids)
                except Exception as e:
                    logger.warning(f"Failed to get Hikvision streaming channels: {e}")

            # Last fallback: Assume 16 channels
            if not info.cameras:
                info.channels = 16
                for ch_id in range(1, 17):
                    camera = DiscoveredCamera(
                        channel_id=ch_id,
                        name=f"Camera {ch_id}",
                        rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/Streaming/Channels/{ch_id}01",
                        rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/Streaming/Channels/{ch_id}02",
                        status="unknown"
                    )
                    info.cameras.append(camera)

        return info

    # ==================== DAHUA ====================
    async def _discover_dahua(
        self, host: str, port: int, rtsp_port: int, username: str, password: str
    ) -> NVRInfo:
        """Discover cameras from Dahua NVR."""
        info = NVRInfo(brand=NVRBrand.DAHUA)
        auth = aiohttp.BasicAuth(username, password)

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            # Get device type/info
            try:
                url = f"http://{host}:{port}/cgi-bin/magicBox.cgi?action=getDeviceType"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        match = re.search(r"type=(.+)", text)
                        if match:
                            info.model = match.group(1).strip()
            except Exception as e:
                logger.warning(f"Failed to get Dahua device info: {e}")

            # Get serial number
            try:
                url = f"http://{host}:{port}/cgi-bin/magicBox.cgi?action=getSerialNo"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        match = re.search(r"sn=(.+)", text)
                        if match:
                            info.serial = match.group(1).strip()
            except Exception as e:
                logger.warning(f"Failed to get Dahua serial: {e}")

            # Get channel count
            try:
                url = f"http://{host}:{port}/cgi-bin/magicBox.cgi?action=getProductDefinition&name=MaxRemoteInputChannels"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        match = re.search(r"MaxRemoteInputChannels=(\d+)", text)
                        if match:
                            info.channels = int(match.group(1))
            except Exception as e:
                logger.warning(f"Failed to get Dahua channel count: {e}")

            # Get channel names and status
            if info.channels == 0:
                info.channels = 16  # Default

            for ch_id in range(1, info.channels + 1):
                ch_name = f"Camera {ch_id}"

                # Try to get channel name
                try:
                    url = f"http://{host}:{port}/cgi-bin/configManager.cgi?action=getConfig&name=ChannelTitle[{ch_id-1}]"
                    async with session.get(url, auth=auth, ssl=False) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            match = re.search(r"Name=(.+)", text)
                            if match:
                                ch_name = match.group(1).strip()
                except:
                    pass

                camera = DiscoveredCamera(
                    channel_id=ch_id,
                    name=ch_name,
                    rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/cam/realmonitor?channel={ch_id}&subtype=0",
                    rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/cam/realmonitor?channel={ch_id}&subtype=1",
                )
                info.cameras.append(camera)

        return info

    # ==================== UNIVIEW ====================
    async def _discover_uniview(
        self, host: str, port: int, rtsp_port: int, username: str, password: str
    ) -> NVRInfo:
        """Discover cameras from Uniview NVR."""
        info = NVRInfo(brand=NVRBrand.UNIVIEW)
        auth = aiohttp.BasicAuth(username, password)

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            # Get device info via LAPI
            try:
                url = f"http://{host}:{port}/LAPI/V1.0/System/DeviceInfo"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "Response" in data:
                            info.model = data["Response"].get("DeviceModel")
                            info.serial = data["Response"].get("SerialNumber")
                            info.firmware = data["Response"].get("SoftwareVersion")
            except Exception as e:
                logger.warning(f"Failed to get Uniview device info: {e}")

            # Get channels
            try:
                url = f"http://{host}:{port}/LAPI/V1.0/Channels"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        channels = data.get("Response", {}).get("ChannelList", [])
                        info.channels = len(channels)

                        for ch in channels:
                            ch_id = ch.get("ID", 0)
                            ch_name = ch.get("Name", f"Camera {ch_id}")

                            camera = DiscoveredCamera(
                                channel_id=ch_id,
                                name=ch_name,
                                rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/unicast/c{ch_id}/s0/live",
                                rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/unicast/c{ch_id}/s1/live",
                            )
                            info.cameras.append(camera)
            except Exception as e:
                logger.warning(f"Failed to get Uniview channels: {e}")

            # Fallback
            if not info.cameras:
                info.channels = 16
                for ch_id in range(1, 17):
                    camera = DiscoveredCamera(
                        channel_id=ch_id,
                        name=f"Camera {ch_id}",
                        rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/unicast/c{ch_id}/s0/live",
                        rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/unicast/c{ch_id}/s1/live",
                        status="unknown"
                    )
                    info.cameras.append(camera)

        return info

    # ==================== AXIS ====================
    async def _discover_axis(
        self, host: str, port: int, rtsp_port: int, username: str, password: str
    ) -> NVRInfo:
        """Discover cameras from Axis device."""
        info = NVRInfo(brand=NVRBrand.AXIS)
        auth = aiohttp.BasicAuth(username, password)

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            # Get device info
            try:
                url = f"http://{host}:{port}/axis-cgi/basicdeviceinfo.cgi"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        for line in text.split("\n"):
                            if "ProdNbr" in line:
                                info.model = line.split("=")[-1].strip().strip('"')
                            elif "SerialNumber" in line:
                                info.serial = line.split("=")[-1].strip().strip('"')
            except Exception as e:
                logger.warning(f"Failed to get Axis device info: {e}")

            # Get number of video sources
            try:
                url = f"http://{host}:{port}/axis-cgi/param.cgi?action=list&group=Properties.Image.NbrOfViews"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        match = re.search(r"NbrOfViews=(\d+)", text)
                        if match:
                            info.channels = int(match.group(1))
            except Exception as e:
                logger.warning(f"Failed to get Axis channel count: {e}")

            if info.channels == 0:
                info.channels = 1  # Single camera

            for ch_id in range(1, info.channels + 1):
                camera = DiscoveredCamera(
                    channel_id=ch_id,
                    name=f"Camera {ch_id}" if info.channels > 1 else (info.model or "Axis Camera"),
                    rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/axis-media/media.amp?camera={ch_id}",
                    rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/axis-media/media.amp?camera={ch_id}&resolution=640x480",
                )
                info.cameras.append(camera)

        return info

    # ==================== MILESIGHT ====================
    async def _discover_milesight(
        self, host: str, port: int, rtsp_port: int, username: str, password: str
    ) -> NVRInfo:
        """Discover cameras from Milesight NVR."""
        info = NVRInfo(brand=NVRBrand.MILESIGHT)
        auth = aiohttp.BasicAuth(username, password)

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            # Get device info
            try:
                url = f"http://{host}:{port}/api/system/info"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        info.model = data.get("model")
                        info.serial = data.get("serialNumber")
                        info.firmware = data.get("firmwareVersion")
            except Exception as e:
                logger.warning(f"Failed to get Milesight device info: {e}")

            # Get channels
            try:
                url = f"http://{host}:{port}/api/channels"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        channels = data.get("channels", [])
                        info.channels = len(channels)

                        for ch in channels:
                            ch_id = ch.get("id", 0)
                            ch_name = ch.get("name", f"Camera {ch_id}")

                            camera = DiscoveredCamera(
                                channel_id=ch_id,
                                name=ch_name,
                                rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/main/{ch_id}",
                                rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/sub/{ch_id}",
                            )
                            info.cameras.append(camera)
            except Exception as e:
                logger.warning(f"Failed to get Milesight channels: {e}")

            # Fallback
            if not info.cameras:
                info.channels = 8
                for ch_id in range(1, 9):
                    camera = DiscoveredCamera(
                        channel_id=ch_id,
                        name=f"Camera {ch_id}",
                        rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/main/{ch_id}",
                        rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/sub/{ch_id}",
                        status="unknown"
                    )
                    info.cameras.append(camera)

        return info

    # ==================== BOSCH ====================
    async def _discover_bosch(
        self, host: str, port: int, rtsp_port: int, username: str, password: str
    ) -> NVRInfo:
        """Discover cameras from Bosch device."""
        info = NVRInfo(brand=NVRBrand.BOSCH)
        auth = aiohttp.BasicAuth(username, password)

        # Bosch uses various APIs depending on device type
        # Common RTSP format
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                url = f"http://{host}:{port}/rcp.xml?command=0x0001&type=T_DWORD&direction=READ"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        # Try to parse channel count
                        pass
            except:
                pass

        # Fallback to common Bosch RTSP URLs
        info.channels = 8
        for ch_id in range(1, 9):
            camera = DiscoveredCamera(
                channel_id=ch_id,
                name=f"Camera {ch_id}",
                rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/?inst={ch_id}",
                rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/?inst={ch_id}&res=low",
                status="unknown"
            )
            info.cameras.append(camera)

        return info

    # ==================== HANWHA (Samsung Wisenet) ====================
    async def _discover_hanwha(
        self, host: str, port: int, rtsp_port: int, username: str, password: str
    ) -> NVRInfo:
        """Discover cameras from Hanwha/Samsung Wisenet NVR."""
        info = NVRInfo(brand=NVRBrand.HANWHA)
        auth = aiohttp.BasicAuth(username, password)

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                url = f"http://{host}:{port}/stw-cgi/system.cgi?msubmenu=deviceinfo&action=view"
                async with session.get(url, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        info.model = data.get("Model")
                        info.serial = data.get("SerialNumber")
            except:
                pass

        # Hanwha RTSP format
        info.channels = 16
        for ch_id in range(1, 17):
            camera = DiscoveredCamera(
                channel_id=ch_id,
                name=f"Camera {ch_id}",
                rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/profile{ch_id}/media.smp",
                rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/profile{ch_id}/media.smp?streamType=1",
                status="unknown"
            )
            info.cameras.append(camera)

        return info

    # ==================== ONVIF (Generic) ====================
    async def _discover_onvif(
        self, host: str, port: int, rtsp_port: int, username: str, password: str
    ) -> NVRInfo:
        """Discover cameras using ONVIF protocol."""
        info = NVRInfo(brand=NVRBrand.ONVIF)

        # ONVIF requires SOAP requests, simplified implementation
        # For full ONVIF support, consider using python-onvif-zeep library

        try:
            # Basic ONVIF GetDeviceInformation
            soap_envelope = f'''<?xml version="1.0" encoding="UTF-8"?>
            <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
                <s:Body xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
                    <GetDeviceInformation xmlns="http://www.onvif.org/ver10/device/wsdl"/>
                </s:Body>
            </s:Envelope>'''

            headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
            auth = aiohttp.BasicAuth(username, password)

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                url = f"http://{host}:{port}/onvif/device_service"
                async with session.post(url, data=soap_envelope, headers=headers, auth=auth, ssl=False) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        info.model = self._extract_xml_value(text, "Model")
                        info.serial = self._extract_xml_value(text, "SerialNumber")
                        info.firmware = self._extract_xml_value(text, "FirmwareVersion")
        except Exception as e:
            logger.warning(f"ONVIF device info failed: {e}")

        # For ONVIF, we'd need to query profiles to get actual RTSP URLs
        # Simplified fallback
        info.channels = 8
        for ch_id in range(1, 9):
            camera = DiscoveredCamera(
                channel_id=ch_id,
                name=f"Camera {ch_id}",
                rtsp_url_main=f"rtsp://{username}:{password}@{host}:{rtsp_port}/onvif-media/media.amp?profile=profile{ch_id}_stream1",
                rtsp_url_sub=f"rtsp://{username}:{password}@{host}:{rtsp_port}/onvif-media/media.amp?profile=profile{ch_id}_stream2",
                status="unknown"
            )
            info.cameras.append(camera)

        return info

    def _extract_xml_value(self, xml_string: str, tag: str) -> Optional[str]:
        """Extract value from XML tag."""
        # Try case-insensitive match
        pattern = rf"<{tag}[^>]*>([^<]+)</{tag}>"
        match = re.search(pattern, xml_string, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None


# Global instance
nvr_discovery = NVRDiscovery()
