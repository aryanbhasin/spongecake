import docker
from docker.errors import NotFound, ImageNotFound, APIError
import requests
import time
import base64
import logging
from openai import OpenAI

# Set up logger
logger = logging.getLogger(__name__)

import os
import requests
import subprocess  # Import subprocess module

from . import _exceptions
from .agent import Agent

# -------------------------
# Container Management Functions
# -------------------------
class Desktop:

    def __init__(self, name: str = "newdesktop", docker_image: str = "spongebox/spongecake:latest", vnc_port: int = 5900, api_port: int = 8000, openai_api_key: str = None, create_agent: bool = True):
        # Set container info
        self.container_name = name  # Set container name for use in methods
        self.docker_image = docker_image # Set image name to start container
        self.display = ":99"

        # Set up access ports
        self.vnc_port = vnc_port
        self.api_port = api_port

        # Create a Docker client from environment
        self.docker_client = docker.from_env()

        # Ensure OpenAI API key is available to use
        if openai_api_key is None:
            openai_api_key = os.environ.get("OPENAI_API_KEY")
        if openai_api_key is None:
            raise _exceptions.SpongecakeException("The openai_api_key client option must be set either by passing openai_api_key to the client or by setting the OPENAI_API_KEY environment variable")
        self.openai_api_key = openai_api_key

        # Set up OpenAI API key
        self.openai_client = OpenAI(api_key=openai_api_key)
        
        # Initialize agent if requested
        self._agent = None
        if create_agent:
            self._agent = Agent(desktop=self, openai_api_key=openai_api_key)

    def start(self):
        """
        Starts the container if it's not already running.
        Maps the VNC port and API port.
        """
        try:
            # Check to see if the container already exists
            container = self.docker_client.containers.get(self.container_name)
            logger.info(f"⏰ Container '{self.container_name}' found with status '{container.status}'.")

            # If it's not running, start it
            if container.status != "running":
                logger.info(f"Container '{self.container_name}' is not running. Starting...")
                container.start()
            else:
                logger.info(f"Container '{self.container_name}' is already running.")

        except NotFound:
            # The container does not exist yet. Create it and pull the image first.
            logger.info(f"⏰ Creating and starting a new container '{self.container_name}'...")

            # Always attempt to pull the latest version of the image
            try:
                self.docker_client.images.pull(self.docker_image)
            except APIError as e:
                logger.info("Failed to pull image. Attempting to start container...")

            # Try running a new container from the (hopefully just-pulled) image
            try:
                container = self.docker_client.containers.run(
                    self.docker_image,
                    detach=True,
                    name=self.container_name,
                    ports={
                        f"{self.vnc_port}/tcp": self.vnc_port,
                        f"{self.api_port}/tcp": self.api_port,
                    }
                )
            except ImageNotFound:
                # If for some reason the image is still not found locally,
                # try pulling again explicitly and run once more.
                logger.info(f"Pulling image '{self.docker_image}' now...")
                try:
                    self.docker_client.images.pull(self.docker_image)
                except APIError as e:
                    raise RuntimeError(
                        f"Failed to find or pull image '{self.docker_image}'. Unable to start container."
                        f"Docker reported: {str(e)}"
                    ) from e

                container = self.docker_client.containers.run(
                    self.docker_image,
                    detach=True,
                    name=self.container_name,
                    ports={
                        f"{self.vnc_port}/tcp": self.vnc_port,
                        f"{self.api_port}/tcp": self.api_port,
                    }
                )

        # Give the container a brief moment to initialize its services
        time.sleep(2)
        return container

    def stop(self):
        """
        Stops and removes the container.
        """
        try:
            container = self.docker_client.containers.get(self.container_name)
            container.stop()
            container.remove()
            logger.info(f"Container '{self.container_name}' stopped and removed.")
        except docker.errors.NotFound:
            logger.info(f"Container '{self.container_name}' not found.")

    # -------------------------
    # DESKTOP ACTIONS
    # -------------------------

    # ----------------------------------------------------------------
    # RUN COMMANDS IN DESKTOP
    # ----------------------------------------------------------------
    def exec(self, command):
        # Wrap docker exec
        container = self.docker_client.containers.get(self.container_name)
        # Use /bin/sh -c to execute shell commands
        result = container.exec_run(["/bin/sh", "-c", command], stdout=True, stderr=True)
        if result.output:
            logger.debug(f"Command Output: {result.output.decode()}")

        return {
            "result": result.output.decode() if result.output else "",
            "returncode": result.exit_code
        }

    # ----------------------------------------------------------------
    # CLICK
    # ----------------------------------------------------------------
    def click(self, x: int, y: int, click_type: str = "left"):
        """
        Move the mouse to (x, y) and click the specified button.
        click_type can be 'left', 'middle', or 'right'.
        """
        click_type_map = {"left": 1, "middle": 2, "wheel": 2, "right": 3}
        t = click_type_map.get(click_type.lower(), 1)

        logger.info(f"Action: click at ({x}, {y}) with button '{click_type}' -> mapped to {t}")
        cmd = f"export DISPLAY={self.display} && xdotool mousemove {x} {y} click {t}"
        self.exec(cmd)

    # ----------------------------------------------------------------
    # SCROLL
    # ----------------------------------------------------------------
    def scroll(self, x: int, y: int, scroll_x: int = 0, scroll_y: int = 0):
        """
        Move to (x, y) and scroll horizontally (scroll_x) or vertically (scroll_y).
        Negative scroll_y -> scroll up, positive -> scroll down.
        Negative scroll_x -> scroll left, positive -> scroll right (button 6 or 7).
        """
        logger.info(f"Action: scroll at ({x}, {y}) with offsets (scroll_x={scroll_x}, scroll_y={scroll_y})")
        # Move mouse to position
        move_cmd = f"export DISPLAY={self.display} && xdotool mousemove {x} {y}"
        self.exec(move_cmd)

        # Vertical scroll (button 4 = up, button 5 = down)
        if scroll_y != 0:
            button = 4 if scroll_y < 0 else 5
            clicks = int(abs(scroll_y)/100)
            for _ in range(4):
                scroll_cmd = f"export DISPLAY={self.display} && xdotool click {button}"
                self.exec(scroll_cmd)

        # Horizontal scroll (button 6 = left, button 7 = right)
        if scroll_x != 0:
            button = 6 if scroll_x < 0 else 7
            clicks = int(abs(scroll_x)/100)
            for _ in range(4):
                scroll_cmd = f"export DISPLAY={self.display} && xdotool click {button}"
                self.exec(scroll_cmd)

    # ----------------------------------------------------------------
    # KEYPRESS
    # ----------------------------------------------------------------
    def keypress(self, keys: list[str]):
        """
        Press (and possibly hold) keys in sequence. Allows pressing
        Ctrl/Shift down, pressing other keys, then releasing them.
        Example: keys=["CTRL","F"] -> Ctrl+F
        """
        logger.info(f"Action: keypress with keys: {keys}")

        ctrl_pressed = False
        shift_pressed = False

        for k in keys:
            logger.info(f"  - key '{k}'")

            # Check modifiers
            if k.upper() == 'CTRL':
                logger.info("    => holding down CTRL")
                self.exec(f"export DISPLAY={self.display} && xdotool keydown ctrl")
                ctrl_pressed = True
            elif k.upper() == 'SHIFT':
                logger.info("    => holding down SHIFT")
                self.exec(f"export DISPLAY={self.display} && xdotool keydown shift")
                shift_pressed = True
            # Check special keys
            elif k.lower() == "enter":
                self.exec(f"export DISPLAY={self.display} && xdotool key Return")
            elif k.lower() == "space":
                self.exec(f"export DISPLAY={self.display} && xdotool key space")
            else:
                # For normal alphabetic or punctuation
                lower_k = k.lower()  # xdotool keys are typically lowercase
                self.exec(f"export DISPLAY={self.display} && xdotool key '{lower_k}'")

        # Release modifiers
        if ctrl_pressed:
            logger.info("    => releasing CTRL")
            self.exec(f"export DISPLAY={self.display} && xdotool keyup ctrl")
        if shift_pressed:
            logger.info("    => releasing SHIFT")
            self.exec(f"export DISPLAY={self.display} && xdotool keyup shift")

    # ----------------------------------------------------------------
    # TYPE
    # ----------------------------------------------------------------
    def type_text(self, text: str):
        """
        Type a string of text (like using a keyboard) at the current cursor location.
        """
        logger.info(f"Action: type text: {text}")
        cmd = f"export DISPLAY={self.display} && xdotool type '{text}'"
        self.exec(cmd)
    
    # ----------------------------------------------------------------
    # TAKE SCREENSHOT
    # ----------------------------------------------------------------
    def get_screenshot(self):
        """
        Takes a screenshot of the current desktop.
        Returns the base64-encoded PNG screenshot as a string.
        """
        # The command:
        # 1) Sets DISPLAY to :99 (as Xvfb is running on :99 in your Dockerfile)
        # 2) Runs 'import -window root png:- | base64'
        # 3) The -w 0 option on base64 ensures no line wrapping (optional)
        
        command = (
            "export DISPLAY=:99 && "
            "import -window root png:- | base64 -w 0"
        )

        # We run docker exec, passing the above shell command
        # Note: we add 'bash -c' so we can use shell pipes
        proc = subprocess.run(
            ["docker", "exec", self.container_name, "bash", "-c", command],
            capture_output=True,
            text=True
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"Screenshot command failed:\nSTDERR: {proc.stderr}\n"
            )

        # proc.stdout is now our base64-encoded screenshot
        return proc.stdout.strip()

    # -------------------------
    # Agent Integration
    # -------------------------
    
    def get_agent(self, create_if_none=True):
        """
        Get the agent associated with this desktop, or create one if it doesn't exist.
        
        Args:
            create_if_none: If True and no agent exists, create a new one
            
        Returns:
            An Agent instance
        """
        if self._agent is None and create_if_none:
            self._agent = Agent(desktop=self, openai_api_key=self.openai_api_key)
        return self._agent
    
    def set_agent(self, agent):
        """
        Set the agent for this desktop.
        
        Args:
            agent: An Agent instance
        """
        self._agent = agent
        if agent is not None:
            agent.set_desktop(self)
            
    def action(self, input_text=None, acknowledged_safety_checks=False, ignore_safety_and_input=False,
              complete_handler=None, needs_input_handler=None, needs_safety_check_handler=None, error_handler=None):
        """
        Execute an action in the desktop environment. This method delegates to the agent's action method.
        
        Args:
            input_text: Text input from the user. This can be:
                       - A new command to start a conversation
                       - A response to an agent's request for input
                       - None if acknowledging safety checks
            acknowledged_safety_checks: Whether safety checks have been acknowledged
                                       (only relevant if there's a pending call)
            ignore_safety_and_input: If True, automatically handle safety checks and input requests
                                    without requiring user interaction
            complete_handler: Function to handle COMPLETE status
                             Signature: (data) -> None
                             Returns: None (terminal state)
            needs_input_handler: Function to handle NEEDS_INPUT status
                                Signature: (messages) -> str
                                Returns: User input to continue with
            needs_safety_check_handler: Function to handle NEEDS_SAFETY_CHECK status
                                       Signature: (safety_checks, pending_call) -> bool
                                       Returns: Whether to proceed with the call (True) or not (False)
            error_handler: Function to handle ERROR status
                          Signature: (error_message) -> None
                          Returns: None (terminal state)
        
        Returns:
            Tuple of (status, data), where:
            - status is an AgentStatus enum value indicating the result
            - data contains relevant information based on the status
        """
        agent = self.get_agent()
        return agent.action(
            input_text=input_text, 
            acknowledged_safety_checks=acknowledged_safety_checks, 
            ignore_safety_and_input=ignore_safety_and_input,
            complete_handler=complete_handler,
            needs_input_handler=needs_input_handler,
            needs_safety_check_handler=needs_safety_check_handler,
            error_handler=error_handler
        )
