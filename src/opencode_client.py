# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3
"""
Lightweight Python client for running questions through an OpenCode session.

Starts an OpenCode server, creates a session, sends a question, waits for
the final response, and optionally exports the session to a JSON file.

Usage:
    python opencode_client.py --question "What entities are related to Q42?" \
        --workspace /path/to/workspace \
        --export session_output.json

Requirements:
    - opencode CLI installed (https://opencode.ai/install)
    - requests (pip install requests)
"""

import json
import logging
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_dotenv(workspace_dir: Path) -> dict:
    """
    Load variables from a .env file in the workspace directory into a dict.
    Returns the current environment merged with any .env variables.
    Variables already set in the environment take precedence over .env values.
    """
    env = os.environ.copy()
    dotenv_path = workspace_dir / ".env"
    if dotenv_path.exists():
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith("#"):
                        continue
                    # Parse KEY=VALUE (handle optional quotes)
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        # Remove surrounding quotes if present
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        # Only set if not already in environment (env takes precedence)
                        if key not in env:
                            env[key] = value
            logger.debug(f"Loaded .env from {dotenv_path}")
        except Exception as e:
            logger.warning(f"Could not load .env file: {e}")
    return env


def find_free_port() -> int:
    """Find a free TCP port by binding to port 0 and reading the assigned port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


class OpencodeClient:
    """
    Lightweight client that starts an OpenCode server, sends a question,
    and retrieves the response.
    """

    def __init__(
        self,
        workspace_dir: str,
        port: Optional[int] = None,
        config_path: Optional[str] = None,
        log_level: str = "INFO",
        timeout: int = 1500,
        password: Optional[str] = None,
        username: str = "opencode",
    ):
        """
        Args:
            workspace_dir: Directory to use as the OpenCode workspace.
                           Must exist. OpenCode loads AGENTS.md, skills, etc. from here.
            port: Port for the OpenCode server. If None, a free port is chosen automatically.
            config_path: Optional path to an opencode.json config file.
                         If provided, it will be copied into the workspace.
            log_level: Log level for the OpenCode server.
            timeout: Max seconds to wait for a response from the model.
            password: Server password for HTTP Basic Auth. If None, reads from
                      OPENCODE_SERVER_PASSWORD env var. If empty/unset, no auth is used.
            username: Server username for HTTP Basic Auth (default: "opencode").
                      Can also be set via OPENCODE_SERVER_USERNAME env var.
        """
        self.workspace_dir = Path(workspace_dir).resolve()
        self.port = port if port is not None else find_free_port()
        self.config_path = Path(config_path).resolve() if config_path else None
        self.log_level = log_level
        self.timeout = timeout
        self.server_url = f"http://127.0.0.1:{self.port}"
        self._process: Optional[subprocess.Popen] = None

        # Set up auth
        resolved_password = password or os.environ.get("OPENCODE_SERVER_PASSWORD", "")
        resolved_username = os.environ.get("OPENCODE_SERVER_USERNAME", username)
        if resolved_password:
            self._auth = (resolved_username, resolved_password)
        else:
            self._auth = None

    def _prepare_workspace(self):
        """Ensure workspace exists and optionally copy config into it."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        if self.config_path and self.config_path.exists():
            dest = self.workspace_dir / "opencode.json"
            if not dest.exists() or dest.read_text() != self.config_path.read_text():
                shutil.copy2(self.config_path, dest)
                logger.info(f"Copied config to {dest}")

    def start_server(self, startup_timeout: int = 60) -> None:
        """Start the OpenCode server subprocess."""
        self._prepare_workspace()

        cmd = [
            "opencode",
            "serve",
            "--port", str(self.port),
        ]

        logger.info(f"Starting OpenCode server in {self.workspace_dir} on port {self.port}")

        # Load environment from .env file (env vars take precedence over .env)
        server_env = _load_dotenv(self.workspace_dir)

        # Write server output to a log file to avoid pipe buffer deadlocks
        self._log_file_path = self.workspace_dir / ".opencode_server.log"
        self._log_file = open(self._log_file_path, "w")

        self._process = subprocess.Popen(
            cmd,
            cwd=str(self.workspace_dir),
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            env=server_env,
        )

        # Wait for server to be healthy
        if not self._wait_for_health(startup_timeout):
            # Print server log for debugging
            self._log_file.flush()
            try:
                log_content = self._log_file_path.read_text()
                if log_content.strip():
                    logger.error(f"Server log output:\n{log_content[-2000:]}")
            except Exception:
                pass
            self.stop_server()
            raise RuntimeError(
                f"OpenCode server did not become healthy within {startup_timeout}s. "
                f"Check {self._log_file_path} for details."
            )

        logger.info("OpenCode server is ready")

    def stop_server(self) -> None:
        """Stop the OpenCode server subprocess."""
        if self._process is None:
            return

        logger.info("Stopping OpenCode server...")
        try:
            self._process.terminate()
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Server did not stop gracefully, killing...")
            self._process.kill()
            self._process.wait(timeout=5)
        finally:
            self._process = None
            if hasattr(self, "_log_file") and self._log_file:
                try:
                    self._log_file.close()
                except Exception:
                    pass

    def is_healthy(self) -> bool:
        """Check if the server is responding. Tries known health endpoints."""
        for path in ("/global/health", "/health", "/session"):
            try:
                resp = requests.get(
                    f"{self.server_url}{path}", timeout=3, auth=self._auth
                )
                if resp.status_code == 200:
                    return True
            except requests.RequestException:
                continue
        return False

    def _wait_for_health(self, timeout: int) -> bool:
        """Wait for server health with backoff."""
        start = time.time()
        delay = 0.5
        attempts = 0
        while time.time() - start < timeout:
            if self._process and self._process.poll() is not None:
                logger.error(
                    f"Server process exited with code {self._process.returncode}"
                )
                return False
            if self.is_healthy():
                return True
            attempts += 1
            if attempts % 5 == 0:
                elapsed = int(time.time() - start)
                logger.debug(f"Still waiting for server... ({elapsed}s elapsed)")
            time.sleep(delay)
            delay = min(delay * 1.5, 3.0)
        return False

    def create_session(self, title: Optional[str] = None) -> str:
        """Create a new session and return its ID."""
        body = {}
        if title:
            body["title"] = title

        resp = requests.post(
            f"{self.server_url}/session", json=body, timeout=10, auth=self._auth
        )
        resp.raise_for_status()
        session = resp.json()
        session_id = session["id"]
        logger.info(f"Created session: {session_id}")
        return session_id

    def send_message(self, session_id: str, question: str) -> dict:
        """
        Send a message to a session and wait for the complete response.

        This uses the synchronous POST /session/:id/message endpoint,
        which blocks until the model finishes responding.

        Returns:
            The full message response dict with 'info' and 'parts'.
        """
        body = {
            "parts": [{"type": "text", "text": question}],
        }

        logger.info(f"Sending question (waiting up to {self.timeout}s for response)...")

        resp = requests.post(
            f"{self.server_url}/session/{session_id}/message",
            json=body,
            timeout=self.timeout,
            auth=self._auth,
        )
        resp.raise_for_status()
        return resp.json()

    def get_session_messages(self, session_id: str) -> list:
        """Get all messages in a session."""
        resp = requests.get(
            f"{self.server_url}/session/{session_id}/message",
            timeout=10,
            auth=self._auth,
        )
        resp.raise_for_status()
        return resp.json()

    def get_session(self, session_id: str) -> dict:
        """Get session details."""
        resp = requests.get(
            f"{self.server_url}/session/{session_id}",
            timeout=10,
            auth=self._auth,
        )
        resp.raise_for_status()
        return resp.json()

    def export_session(self, session_id: str, output_path: str) -> None:
        """Export the full session (metadata + messages) to a JSON file."""
        session = self.get_session(session_id)
        messages = self.get_session_messages(session_id)

        export_data = {
            "session": session,
            "messages": messages,
        }

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(export_data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        logger.info(f"Session exported to {output}")

    def extract_final_text(self, response: dict) -> str:
        """Extract the final text content from a message response."""
        # Check for errors in the response (e.g., LLM auth failures)
        info = response.get("info", {})
        error = info.get("error")
        if error:
            error_name = error.get("name", "UnknownError")
            error_data = error.get("data", {})
            error_msg = error_data.get("message", str(error))
            logger.error(f"LLM error: {error_name} - {error_msg}")
            return f"ERROR: {error_name} - {error_msg}"

        parts = response.get("parts", [])
        text_parts = []
        for part in parts:
            if part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        return "\n".join(text_parts) if text_parts else "(no text response)"

    def run(
        self,
        question: str,
        session_title: Optional[str] = None,
        export_path: Optional[str] = None,
    ) -> str:
        """
        Full workflow: start server, create session, ask question, get answer.

        Args:
            question: The question to ask.
            session_title: Optional title for the session.
            export_path: If provided, export the session JSON to this path.

        Returns:
            The final text response from OpenCode.
        """
        session_id = None
        try:
            self.start_server()
            session_id = self.create_session(title=session_title)
            response = self.send_message(session_id, question)
            final_text = self.extract_final_text(response)

            if export_path:
                self.export_session(session_id, export_path)

            return final_text

        except (requests.exceptions.Timeout, requests.exceptions.ReadTimeout) as e:
            logger.warning(f"Request timed out: {e}")
            if export_path and session_id:
                logger.info("Exporting partial session despite timeout...")
                try:
                    self.export_session(session_id, export_path)
                except Exception as export_err:
                    logger.error(f"Failed to export session after timeout: {export_err}")
            return f"ERROR: Request timed out after {self.timeout}s."

        except Exception as e:
            if export_path and session_id:
                logger.info("Exporting partial session after error...")
                try:
                    self.export_session(session_id, export_path)
                except Exception as export_err:
                    logger.error(f"Failed to export session after error: {export_err}")
            raise

        finally:
            self.stop_server()
