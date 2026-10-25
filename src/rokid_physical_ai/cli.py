"""Operator commands. Secrets and calibration live outside the repository."""

import argparse
import asyncio
import base64
import datetime
import hashlib
import ipaddress
import json
import logging
import os
import subprocess
import time
from pathlib import Path

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from platformdirs import user_data_path

from .app import Settings, create_app
from .gateway import HttpGateway
from .store import Store


def ensure_tls(directory: Path, host: str) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = directory / "server.pem", directory / "server.key"
    if cert_path.exists() != key_path.exists():
        raise ValueError("Incomplete TLS identity; inspect it instead of replacing it")
    if not cert_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Rokid Physical AI")])
        now = datetime.datetime.now(datetime.UTC)
        san: x509.GeneralName
        try:
            san = x509.IPAddress(ipaddress.ip_address(host))
        except ValueError:
            san = x509.DNSName(host)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([san]), critical=False)
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        key_path.chmod(0o600)
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-dir", type=Path, default=user_data_path("RokidPhysicalAI", appauthor=False)
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8768)
    serve.add_argument("--diagnostic", action="store_true")
    serve.add_argument("--vosk-model", type=Path)
    serve.add_argument("--workspace-calibration", type=Path)
    serve.add_argument("--glasses-calibration", type=Path)
    pair = sub.add_parser("pair")
    pair.add_argument("--endpoint", required=True)
    pair.add_argument("--adb", type=Path, required=True)
    pair.add_argument("--serial", required=True)
    pair.add_argument("--adb-port", type=int, default=15048)
    sub.add_parser("doctor")
    reconcile = sub.add_parser(
        "reconcile", help="Reconcile one uncertain task with a checked gateway"
    )
    reconcile.add_argument("task_id")
    intrinsics = sub.add_parser("calibrate-intrinsics")
    intrinsics.add_argument("--images", type=Path, required=True)
    intrinsics.add_argument("--output", type=Path, required=True)
    intrinsics.add_argument("--square-size", type=float, required=True)
    intrinsics.add_argument("--columns", type=int, default=7)
    intrinsics.add_argument("--rows", type=int, default=5)
    schema = sub.add_parser("schemas")
    schema.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "serve":
        cert, key = ensure_tls(args.state_dir, args.host)
        gateway = None
        if os.environ.get("ROBOT_GATEWAY_URL"):
            gateway = HttpGateway(
                os.environ["ROBOT_GATEWAY_URL"],
                os.environ["ROBOT_GATEWAY_TOKEN"],
                os.environ.get("ROBOT_GATEWAY_CA", True),
            )
        settings = Settings(
            args.state_dir,
            args.diagnostic,
            args.vosk_model,
            args.workspace_calibration,
            args.glasses_calibration,
        )
        uvicorn.run(
            create_app(settings, gateway),
            host=args.host,
            port=args.port,
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
            ws_max_size=450_000,
            ws_max_queue=4,
            access_log=False,
        )
    elif args.command == "pair":
        from urllib.parse import urlparse

        uri = urlparse(args.endpoint)
        if uri.scheme != "https" or not uri.hostname or uri.path not in ("", "/"):
            raise ValueError("Endpoint must be an HTTPS origin")
        certificate = x509.load_pem_x509_certificate((args.state_dir / "server.pem").read_bytes())
        pin = hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
        store = Store(args.state_dir / "agent.sqlite3")
        try:
            payload = {
                "endpoint": args.endpoint.rstrip("/"),
                "pin": pin,
                "code": store.pairing_code(),
            }
        finally:
            store.close()
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        command = [
            str(args.adb),
            "-P",
            str(args.adb_port),
            "-s",
            args.serial,
            "shell",
            "am",
            "start",
            "-n",
            "io.github.ykshv.rokidphysicalai/.ProvisionActivity",
            "--es",
            "provision",
            encoded,
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode or "Error:" in result.stdout or "Error:" in result.stderr:
            raise RuntimeError("ADB provisioning failed; pairing payload was not logged")
        print("Provisioning sent. No camera or microphone was started.")
    elif args.command == "doctor":
        import platform

        print(
            json.dumps(
                {
                    "python": platform.python_version(),
                    "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
                    "gateway_configured": bool(os.getenv("ROBOT_GATEWAY_URL")),
                    "state_directory": str(args.state_dir),
                },
                indent=2,
            )
        )
    elif args.command == "reconcile":
        from .contracts import TaskState

        async def reconcile_task() -> None:
            gateway = HttpGateway(
                os.environ["ROBOT_GATEWAY_URL"],
                os.environ["ROBOT_GATEWAY_TOKEN"],
                os.environ.get("ROBOT_GATEWAY_CA", True),
            )
            store = Store(args.state_dir / "agent.sqlite3")
            try:
                task = store.get(args.task_id)
                if task.state != TaskState.UNCERTAIN:
                    raise ValueError("Only an uncertain task needs reconciliation")
                result = await gateway.status(task.id)
                if result.state in ("uncertain", "executing"):
                    raise ValueError("Inspect the robot and reconcile its local gateway first")
                store.put(
                    task.model_copy(
                        update={
                            "state": TaskState(result.state),
                            "updated_at": time.time(),
                            "reason": "operator_reconciled_with_gateway: "
                            + (result.reason or result.state),
                        }
                    )
                )
                print(f"Reconciled {task.id}: {result.state}. No motion was requested.")
            finally:
                await gateway.close()
                store.close()

        asyncio.run(reconcile_task())
    elif args.command == "schemas":
        from .contracts import (
            MotionRequest,
            RobotCapabilities,
            SceneObservation,
            TaskExecution,
            TaskIntent,
        )
        from .perception import Calibration, GlassesCalibration

        args.output.mkdir(parents=True, exist_ok=True)
        for model in (
            MotionRequest,
            RobotCapabilities,
            SceneObservation,
            TaskExecution,
            TaskIntent,
            Calibration,
            GlassesCalibration,
        ):
            (args.output / f"{model.__name__}.json").write_text(
                json.dumps(model.model_json_schema(), indent=2) + "\n", encoding="utf-8"
            )
    elif args.command == "calibrate-intrinsics":
        from .perception import calibrate_intrinsics

        if args.output.exists():
            raise ValueError(
                "Choose a new output path; existing calibration will not be overwritten"
            )
        if not 0.005 <= args.square_size <= 0.2 or min(args.rows, args.columns) < 3:
            raise ValueError("Invalid measured ChArUco board dimensions")
        images = sorted(p for p in args.images.iterdir() if p.suffix.lower() in (".jpg", ".png"))
        calibrate_intrinsics(images, args.output, (args.columns, args.rows), args.square_size)


if __name__ == "__main__":
    main()
